"""HCA Cell Annotation validator — structural conformance to the HCA Cell Annotation schema.

Phase 1 (see issue #362) performs four structural checks:

1. At least one CAP annotation set present (``uns['cellannotation_metadata']``
   is a non-empty dict).
2. ``uns['cellannotation_schema_version']`` is present and well-formed.
3. ``uns['cellannotation_metadata']`` is a dict and each per-set value is a
   dict with a ``title`` key.
4. Each annotation set has the CAP-required per-set obs columns.

Marker-gene coverage (Phase 2) and CL-term validity (Phase 3) are out of
scope for this module.
"""

from __future__ import annotations

import logging
import re
from typing import List

import anndata as ad


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

# CAP per-set metadata keys required in uns['cellannotation_metadata'][<set>].
_REQUIRED_SET_METADATA_KEYS = ("title",)

_SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+].+)?$")

NO_SETS_ERROR = (
    "No CAP annotation sets present. At least one annotation set conforming "
    "to the HCA Cell Annotation schema is required."
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
            adata = ad.io.read_h5ad(h5ad_path, backed="r")
        except Exception as e:
            self._error(f"Unable to read h5ad file: {e}")
            return False

        try:
            self._check_schema_version(adata.uns)
            sets = self._check_metadata(adata.uns)
            if sets:
                obs_columns = set(adata.obs.columns)
                for set_name in sets:
                    self._check_set_columns(set_name, obs_columns)
        finally:
            adata.file.close()

        return not self.errors

    def _check_schema_version(self, uns) -> None:
        if "cellannotation_schema_version" not in uns:
            self._error(
                "uns['cellannotation_schema_version'] is missing. The HCA Cell "
                "Annotation schema version must be recorded."
            )
            return
        value = uns["cellannotation_schema_version"]
        if not isinstance(value, str) or not _SEMVER_PATTERN.match(value):
            self._error(
                f"uns['cellannotation_schema_version'] must be a semver string "
                f"(e.g. '0.1.0'); got {value!r}."
            )

    def _check_metadata(self, uns) -> List[str]:
        if "cellannotation_metadata" not in uns:
            self._error(NO_SETS_ERROR)
            return []

        metadata = uns["cellannotation_metadata"]
        if not isinstance(metadata, dict):
            self._error(
                f"uns['cellannotation_metadata'] must be a dict keyed by "
                f"annotation set name; got {type(metadata).__name__}."
            )
            return []

        if not metadata:
            self._error(NO_SETS_ERROR)
            return []

        annotation_sets: List[str] = []
        for set_name, set_meta in metadata.items():
            if not isinstance(set_meta, dict):
                self._error(
                    f"uns['cellannotation_metadata']['{set_name}'] must be a "
                    f"dict; got {type(set_meta).__name__}."
                )
                continue
            missing_keys = [k for k in _REQUIRED_SET_METADATA_KEYS if k not in set_meta]
            if missing_keys:
                self._error(
                    f"uns['cellannotation_metadata']['{set_name}'] is missing "
                    f"required keys: {missing_keys}."
                )
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
