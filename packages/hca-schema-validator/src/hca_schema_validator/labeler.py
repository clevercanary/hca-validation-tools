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
_FORBIDDEN_UNS_KEYS = ("schema_version", "schema_reference")


@functools.lru_cache(maxsize=None)
def _organism_for_feature(feature_id: str):
    # HCA is human-only. Probe HOMO_SAPIENS directly instead of scanning all
    # supported organisms — the base's get_organism_from_feature_id loads
    # every GENCODE table in turn, which wastes memory and time on files
    # with deprecated IDs. Any new organism = code change.
    human = SupportedOrganisms.HOMO_SAPIENS
    return human if get_gene_checker(human).is_valid_id(feature_id) else None


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
                if "add_labels" in col_def and col_name not in df.columns:
                    issues.append(f"Missing required column '{col_name}' in {component_name}")
        for key in _FORBIDDEN_UNS_KEYS:
            if key in self.adata.uns:
                issues.append(
                    f"uns['{key}'] must not be present on input "
                    "(file appears to have been processed by cellxgene-schema add-labels already)"
                )
        if issues:
            raise ValueError("HCALabeler preflight failed:\n  - " + "\n  - ".join(issues))

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
        # Base uses the ERCC prefix only and never touches organism, but we
        # still NaN unknown-organism IDs so all five feature_* columns stay
        # in sync — same rows NaN everywhere.
        return self._map_by_organism(ids, lambda i, _o: "spike-in" if i.startswith("ERCC") else "gene")

    def write_labels(self, output_path: str) -> None:
        self._preflight()

        self._add_labels()
        self._remove_categories_with_zero_values()

        organism_col = self.adata.obs.get(_ORGANISM_COL)
        if organism_col is not None:
            vals = organism_col.dropna().unique()
            if len(vals) == 1:
                self.adata.uns[_ORGANISM_COL] = str(vals[0])

        self.adata.obs["observation_joinid"] = get_hash_digest_column(self.adata.obs)

        self.adata.write_h5ad(output_path, compression="gzip")
