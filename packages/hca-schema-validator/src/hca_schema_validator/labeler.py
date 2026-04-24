"""HCA labeler: NaN-tolerant AnnDataLabelAppender with HCA preflight checks."""

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
_OBSERVATION_JOINID_COL = "observation_joinid"
_HUMAN_TAXON = "NCBITaxon:9606"
_NON_REQUIRED_LEVELS = {"optional", "strongly_recommended"}
# Derived obs label columns the HCA labeler writes from `<field>_ontology_term_id`.
# Exported for callers (e.g. the MCP `label_h5ad` wrapper) that summarize which
# columns will be populated. Preflight rejects any of these that are already
# present on input, so callers no longer need to track pre-existing values for
# overwrite reporting. `cell_type` is included — it is written only when
# `cell_type_ontology_term_id` is present (optional per schema).
HCA_DERIVED_OBS_LABELS = (
    "tissue",
    "cell_type",
    "assay",
    "disease",
    "sex",
    "organism",
    "development_stage",
    "self_reported_ethnicity",
)
# Keys that signal the input has already been through cellxgene-schema
# add-labels. `citation` (also in the schema's reserved_columns list) is
# added at Discover publish, not by add-labels, so we don't reject on it
# — narrower check matches the intent of R7.
_POST_ADDLABELS_UNS_KEYS = ("schema_version", "schema_reference")
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
        self._preflight_done = False

    def _preflight(self) -> None:
        issues: List[str] = []
        for component_name in ("obs", "var", "raw.var"):
            df = getattr_anndata(self.adata, component_name)
            if df is None:
                continue
            component = self.schema_def.get("components", {}).get(component_name, {})
            for col_name, col_def in component.get("columns", {}).items():
                if "add_labels" not in col_def:
                    continue
                # Reserved-column check fires regardless of source presence:
                # if a target label column already exists, the labeler refuses
                # to run rather than risk silent overwrite. Matches cellxgene-
                # schema's `Validator(ignore_labels=False)` behavior.
                issues.extend(self._reserved_collisions(df, component_name, col_def["add_labels"]))
                # Required-source check: source column missing on a default-
                # required field is a hard fail. Optional / strongly-recommended
                # source columns missing just mean we skip writing that field
                # (see _add_column below).
                if col_name not in df.columns:
                    level = str(col_def.get("requirement_level", "")).lower()
                    if level not in _NON_REQUIRED_LEVELS:
                        issues.append(f"Missing required column '{col_name}' in {component_name}")
            # Index- and key-driven labels (var.index → feature_name etc.)
            # always have a "source" present, so the labeler will always write
            # them; reject if their target columns/keys already exist.
            index_def = component.get("index")
            if isinstance(index_def, dict) and "add_labels" in index_def:
                issues.extend(self._reserved_collisions(df, component_name, index_def["add_labels"]))
            for key_def in component.get("keys", {}).values():
                if "add_labels" in key_def:
                    issues.extend(self._reserved_collisions(df, component_name, key_def["add_labels"]))
            # Component-level reserved_columns (e.g. obs['observation_joinid'])
            # are written by `label()` outside the schema's add_labels machinery,
            # so they need their own collision check. Wording omits the "Add
            # labels error:" prefix to match cellxgene-schema's split between
            # add_labels-target and reserved_columns errors. uns is excluded
            # here — its `citation` reserved key is added by Discover post-
            # publish, not by the labeler, so we don't reject on it (see
            # _POST_ADDLABELS_UNS_KEYS for the narrower uns check).
            for reserved in component.get("reserved_columns", []):
                if reserved in df.columns:
                    issues.append(
                        f"Column '{reserved}' is a reserved column name "
                        f"of '{component_name}'. Remove it from h5ad and try again."
                    )
        for key in _POST_ADDLABELS_UNS_KEYS:
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

    @staticmethod
    def _reserved_collisions(df, component_name: str, add_labels_def: List[Dict]) -> List[str]:
        """Return one error string per ``add_labels`` target already on ``df``.

        Mirrors the vendored validator's reserved-column wording so curators
        see the same message whether they hit the validator or the labeler.

        DataFrame components only — caller (`_preflight`) iterates obs/var/
        raw.var. Schema directives that target a uns key (``to_key``) would
        need a different membership check and are intentionally out of
        scope; the HCA schema doesn't use them.
        """
        issues: List[str] = []
        for label_def in add_labels_def:
            target = label_def.get("to_column")
            if target is not None and target in df.columns:
                issues.append(
                    f"Add labels error: Column '{target}' is a reserved column name "
                    f"of '{component_name}'. Remove it from h5ad and try again."
                )
        return issues

    def _add_labels(self):
        # Defensive gate: callers reaching the inherited mutation point
        # directly (e.g. ``super().write_labels(...)`` or a private-API call)
        # bypass the public ``label()`` flow. Re-running preflight is cheap
        # because it's idempotent — the public path still pays only once.
        self.preflight()
        super()._add_labels()

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

    def preflight(self) -> None:
        """Raise ``ValueError`` if the input fails HCA preflight checks.

        Exposes the preflight phase publicly so callers (e.g. the MCP
        ``label_h5ad`` wrapper) can distinguish an input-rejected failure
        from a runtime labeling error — both raise ``ValueError`` from
        ``label()``, but only preflight is recoverable by fixing inputs.

        Idempotent — ``label()`` calls this internally, so a caller that
        already invoked ``preflight()`` doesn't pay the cost twice (the
        organism-column scan is O(n_obs)). Instantiate a fresh
        ``HCALabeler`` to re-run after mutating ``adata``.
        """
        if self._preflight_done:
            return
        self._preflight()
        self._preflight_done = True

    def label(self):
        """Run preflight, apply labels, write observation_joinid. Return mutated adata.

        In-memory equivalent of ``write_labels`` without the file write — lets
        callers drive the output themselves (e.g. the MCP ``label_h5ad``
        wrapper writes via ``hca_anndata_tools.write.write_h5ad`` so the
        edit-log snapshot convention matches every other edit tool).
        """
        self.preflight()

        self._add_labels()
        self._remove_categories_with_zero_values()

        self.adata.obs[_OBSERVATION_JOINID_COL] = get_hash_digest_column(self.adata.obs)

        return self.adata

    def write_labels(self, output_path: str) -> None:
        self.label()
        self.adata.write_h5ad(output_path, compression="gzip")
