"""HCA Cell Annotation validator — structural conformance to the HCA Cell Annotation schema.

CAP annotation metadata is nested under ``uns['cap_metadata']`` (canonical
layout). The deprecated top-level layout (``uns['cellannotation_metadata']`` /
``uns['cellannotation_schema_version']``) is rejected — see issue #452.

Phase 1 (see issue #362) performs four structural checks:

1. At least one CAP annotation set present
   (``uns['cap_metadata']['cellannotation_metadata']`` is a non-empty dict).
2. ``uns['cap_metadata']['cellannotation_schema_version']`` is present and
   well-formed.
3. ``uns['cap_metadata']['cellannotation_metadata']`` is a dict and each per-set
   value is a dict. The CAP AnnData schema's per-set required fields
   (``description``, ``annotation_method``, ``algorithm_name``,
   ``algorithm_version``, ``algorithm_repo_url``) are left to the upstream
   CAP-side validator; this check only enforces structural shape.
4. Each annotation set has the CAP-required per-set obs columns.

Marker-gene coverage (Phase 2) and CL-term validity (Phase 3) are out of
scope for this module.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import List, Optional

import anndata as ad
import semver


logger = logging.getLogger(__name__)


# CAP-required per-set obs column suffixes (sans the cell-label column itself,
# which is not enforced as a hard requirement in Phase 1 — rows may be unlabeled).
_REQUIRED_OBS_SUFFIXES = (
    "cell_fullname",
    "cell_ontology_exists",
    "cell_ontology_term_id",
    "cell_ontology_term",
    "rationale",
    "marker_gene_evidence",
)

NO_SETS_ERROR = (
    "No CAP annotation sets present. At least one annotation set conforming "
    "to the HCA Cell Annotation schema is required. "
    "See https://data.humancellatlas.org/metadata/cell-annotation for details."
)

# Raised when CAP metadata is found at the deprecated top level of uns instead
# of nested under uns['cap_metadata'] (issue #452).
LEGACY_LAYOUT_ERROR = (
    "CAP annotation metadata must be nested under uns['cap_metadata']. Found "
    "the deprecated top-level layout (uns['cellannotation_metadata'] / "
    "uns['cellannotation_schema_version']); re-export with the CAP metadata "
    "under uns['cap_metadata']. "
    "See https://data.humancellatlas.org/metadata/cell-annotation for details."
)


class HCACellAnnotationValidator:
    """Validate an h5ad's conformance to the HCA Cell Annotation schema.

    Mirrors the shape of :class:`hca_schema_validator.HCAValidator`: construct
    with no arguments, then call :meth:`validate_adata` with a file path. The
    method populates :attr:`errors` and :attr:`warnings` and returns a bool.
    Errors and warnings are also emitted via the module logger so service
    wrappers can capture them with a ``logging.Handler``.
    """

    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def _error(self, message: str) -> None:
        self.errors.append(message)
        logger.error(message)

    def validate_adata(self, h5ad_path: str) -> bool:
        self.errors = []
        self.warnings = []

        try:
            adata = ad.read_h5ad(h5ad_path, backed="r")
        except Exception as e:
            self._error(f"Unable to read h5ad file: {e}")
            return False

        try:
            # Resolve the canonical CAP block first. A deprecated top-level
            # layout or a missing block is the one actionable message — don't
            # add schema-version noise that a contributor can't meaningfully fix.
            cap = self._resolve_cap_metadata(adata.uns)
            if cap is not None:
                sets = self._check_metadata(cap)
                if sets:
                    self._check_schema_version(cap)
                    obs_columns = set(adata.obs.columns)
                    for set_name in sets:
                        self._check_set_columns(set_name, obs_columns)
        finally:
            # Guard against an unexpected non-backed return so a missing
            # `.file` attribute doesn't mask earlier validation errors.
            if getattr(adata, "file", None) is not None:
                adata.file.close()

        return not self.errors

    def _resolve_cap_metadata(self, uns) -> Optional[Mapping]:
        """Return the canonical ``uns['cap_metadata']`` mapping, or None.

        Strict: CAP metadata must live under ``uns['cap_metadata']``. Any
        deprecated top-level key records ``LEGACY_LAYOUT_ERROR`` — even
        alongside a nested block (a mixed-layout file) — so the contributor
        knows to drop the deprecated keys. A missing block with no deprecated
        keys records ``NO_SETS_ERROR``. Returns None in every error case.
        """
        if "cellannotation_metadata" in uns or "cellannotation_schema_version" in uns:
            self._error(LEGACY_LAYOUT_ERROR)
            return None
        cap = uns.get("cap_metadata")
        if cap is None:
            self._error(NO_SETS_ERROR)
            return None
        if not isinstance(cap, Mapping):
            self._error(
                f"uns['cap_metadata'] must be a dict/group; got "
                f"{type(cap).__name__}."
            )
            return None
        return cap

    def _check_schema_version(self, cap) -> None:
        if "cellannotation_schema_version" not in cap:
            self._error(
                "uns['cap_metadata']['cellannotation_schema_version'] is missing. "
                "The HCA Cell Annotation schema version must be recorded."
            )
            return
        value = cap["cellannotation_schema_version"]
        if not isinstance(value, str):
            self._error(
                f"uns['cap_metadata']['cellannotation_schema_version'] must be a "
                f"semver string (e.g. '0.1.0'); got {value!r}."
            )
            return
        try:
            semver.Version.parse(value)
        except ValueError:
            self._error(
                f"uns['cap_metadata']['cellannotation_schema_version'] must be a "
                f"semver string (e.g. '0.1.0'); got {value!r}."
            )

    def _check_metadata(self, cap) -> List[str]:
        if "cellannotation_metadata" not in cap:
            self._error(NO_SETS_ERROR)
            return []

        metadata = cap["cellannotation_metadata"]
        if not isinstance(metadata, dict):
            self._error(
                f"uns['cap_metadata']['cellannotation_metadata'] must be a dict "
                f"keyed by annotation set name; got {type(metadata).__name__}."
            )
            return []

        if not metadata:
            self._error(NO_SETS_ERROR)
            return []

        annotation_sets: List[str] = []
        for set_name, set_meta in metadata.items():
            if not isinstance(set_meta, dict):
                self._error(
                    f"uns['cap_metadata']['cellannotation_metadata']['{set_name}'] "
                    f"must be a dict; got {type(set_meta).__name__}."
                )
                continue
            annotation_sets.append(set_name)
        return annotation_sets

    def _check_set_columns(self, set_name: str, obs_columns: set) -> None:
        for suffix in _REQUIRED_OBS_SUFFIXES:
            col = f"{set_name}--{suffix}"
            if col not in obs_columns:
                self._error(
                    f"Annotation set '{set_name}' is missing required obs "
                    f"column '{col}'."
                )
