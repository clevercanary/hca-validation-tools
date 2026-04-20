"""HCA labeler: NaN-tolerant AnnDataLabelAppender with HCA-flavored uns handling."""

import functools
from pathlib import Path
from typing import Callable, Dict, List

import pandas as pd
import yaml

from hca_schema_validator._vendored.cellxgene_schema.gencode import SupportedOrganisms, get_gene_checker
from hca_schema_validator._vendored.cellxgene_schema.utils import get_hash_digest_column, getattr_anndata
from hca_schema_validator._vendored.cellxgene_schema.write_labels import AnnDataLabelAppender

_SCHEMA_PATH = Path(__file__).parent / "schema_definitions" / "hca_schema_definition.yaml"
_ORGANISM_COL = "organism_ontology_term_id"
_HUMAN_TAXON = "NCBITaxon:9606"
_FORBIDDEN_UNS_KEYS = ("schema_version", "schema_reference")
_NON_REQUIRED_LEVELS = {"optional", "strongly_recommended"}
# Human GENCODE 48 has ~79k genes + 92 ERCC. Bound large enough to cache
# several GENCODE vintages of deprecated IDs without leaking unboundedly
# in long-running processes (e.g. the MCP server).
_ORGANISM_CACHE_SIZE = 200_000


_SUPPORTED_ORGANISMS = (SupportedOrganisms.HOMO_SAPIENS, SupportedOrganisms.ERCC)


@functools.lru_cache(maxsize=_ORGANISM_CACHE_SIZE)
def _organism_for_feature(feature_id: str):
    # HCA supports human genes + ERCC spike-ins only. Probe these two tables
    # directly instead of scanning all 16 organisms the vendored base knows
    # about — that base loads every GENCODE table in turn, which is wasted
    # memory/time on files with deprecated IDs. Adding a new organism is a
    # code change.
    for organism in _SUPPORTED_ORGANISMS:
        if get_gene_checker(organism).is_valid_id(feature_id):
            return organism
    return None


class HCALabeler(AnnDataLabelAppender):
    def __init__(self, adata):
        super().__init__(adata)
        with open(_SCHEMA_PATH) as f:
            self.schema_def = yaml.safe_load(f)

    def _preflight(self) -> None:
        issues: List[str] = []
        for component_name in ("obs", "var", "raw.var"):
            df = getattr_anndata(self.adata, component_name)
            if df is None:
                continue
            component = self.schema_def.get("components", {}).get(component_name, {})
            for col_name, col_def in component.get("columns", {}).items():
                if "add_labels" not in col_def or col_name in df.columns:
                    continue
                # Honor the schema's requirement_level: only default-required
                # columns trigger preflight failure. Optional / strongly-
                # recommended columns missing here just mean we skip labeling
                # for that field — see _add_column below.
                level = str(col_def.get("requirement_level", "")).lower()
                if level not in _NON_REQUIRED_LEVELS:
                    issues.append(f"Missing required column '{col_name}' in {component_name}")
        for key in _FORBIDDEN_UNS_KEYS:
            if key in self.adata.uns:
                issues.append(
                    f"uns['{key}'] must not be present on input "
                    "(file appears to have been processed by cellxgene-schema add-labels already)"
                )
        if _ORGANISM_COL in self.adata.obs.columns:
            non_human = sorted(
                v for v in self.adata.obs[_ORGANISM_COL].dropna().unique() if v != _HUMAN_TAXON
            )
            if non_human:
                issues.append(
                    f"obs['{_ORGANISM_COL}'] contains non-human values {non_human}; "
                    f"HCALabeler supports only {_HUMAN_TAXON}"
                )
        if issues:
            raise ValueError("HCALabeler preflight failed:\n  - " + "\n  - ".join(issues))

    def _add_column(self, component: str, column: str, column_definition: dict) -> None:
        # Skip silently when the source column isn't on the target dataframe.
        # Preflight has already rejected missing required columns, so this
        # only fires for optional / strongly-recommended ones (e.g. the
        # HCA schema marks cell_type_ontology_term_id optional).
        if column != "index":
            df = getattr_anndata(self.adata, component)
            if df is None or column not in df.columns:
                return
        super()._add_column(component, column, column_definition)

    def _map_by_organism(
        self,
        ids: List[str],
        fn: Callable[[str, SupportedOrganisms], object],
    ) -> Dict[str, object]:
        out: Dict[str, object] = {}
        for i in ids:
            organism = _organism_for_feature(i)
            out[i] = pd.NA if organism is None else fn(i, organism)
        return out

    def _get_mapping_dict_feature_id(self, ids):
        return self._map_by_organism(ids, lambda i, o: get_gene_checker(o).get_symbol(i))

    def _get_mapping_dict_feature_reference(self, ids):
        return self._map_by_organism(ids, lambda i, o: o.value)

    def _get_mapping_dict_feature_type(self, ids):
        return self._map_by_organism(ids, lambda i, o: get_gene_checker(o).get_type(i))

    def _get_mapping_dict_feature_length(self, ids):
        return self._map_by_organism(ids, lambda i, o: get_gene_checker(o).get_length(i))

    def _get_mapping_dict_feature_biotype(self, ids):
        # Use organism == ERCC rather than the base's ID-prefix check, so
        # anything in the ERCC table is "spike-in" regardless of its literal
        # ID shape. Unknown-organism IDs still NaN (via _map_by_organism) so
        # all five feature_* columns stay in sync — same rows NaN everywhere.
        return self._map_by_organism(
            ids, lambda _i, o: "spike-in" if o == SupportedOrganisms.ERCC else "gene"
        )

    def write_labels(self, output_path: str) -> None:
        self._preflight()

        self._add_labels()
        self._remove_categories_with_zero_values()

        self.adata.obs["observation_joinid"] = get_hash_digest_column(self.adata.obs)

        self.adata.write_h5ad(output_path, compression="gzip")
