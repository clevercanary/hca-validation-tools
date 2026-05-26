"""MCP wrappers for hca_schema_validator validators."""

import os

from hca_anndata_tools.write import resolve_latest
from hca_schema_validator import HCACellAnnotationValidator, HCAValidator


def validate_schema(path: str) -> dict:
    """Validate an .h5ad file against the HCA schema.

    Wraps :class:`hca_schema_validator.HCAValidator` and returns a
    structured verdict. Auto-resolves to the latest timestamped edit
    snapshot before validating.

    Args:
        path: Path to an .h5ad file.

    Returns:
        Dict with ``filename``, ``is_valid``, ``error_count``,
        ``warning_count``, ``errors`` (list of str), and ``warnings``
        (list of str, with feature-ID warnings ordered last). On
        failure, ``error`` is returned instead.
    """
    try:
        path = resolve_latest(path)
        if not os.path.isfile(path):
            return {"error": f"File not found: {path}"}
        v = HCAValidator()
        try:
            v.validate_adata(path)
        except SystemExit:
            # Vendored cellxgene code exits on unrecoverable read failures.
            # Surface a generic error if no validator errors were captured.
            if not v.errors:
                return {"error": f"Validator could not read {os.path.basename(path)}"}
        return {
            "filename": os.path.basename(path),
            "is_valid": v.is_valid,
            "error_count": len(v.errors),
            "warning_count": len(v.warnings),
            "errors": v.errors,
            "warnings": v.warnings,
        }
    except Exception as e:
        return {"error": str(e)}


def validate_cell_annotation(path: str) -> dict:
    """Validate an .h5ad file against the HCA Cell Annotation schema.

    Wraps :class:`hca_schema_validator.HCACellAnnotationValidator` —
    Phase 1 structural checks only (presence of at least one CAP
    annotation set, well-formed ``cellannotation_schema_version``, per-set
    metadata is a dict, required per-set ``--<suffix>`` obs columns are
    present). Marker-gene coverage (Phase 2, #363) and CL-term validity
    (Phase 3, #364) are not checked here; per-set required metadata
    fields (``description``, ``algorithm_name``, ...) are the upstream
    CAP-side validator's responsibility.

    Complements :func:`validate_schema` — together they cover what the
    dataset-validator service runs at upload time under the
    ``hcaSchema`` and ``hcaCellAnnotation`` keys. Auto-resolves to the
    latest timestamped edit snapshot before validating.

    Args:
        path: Path to an .h5ad file.

    Returns:
        Dict with ``filename``, ``is_valid``, ``error_count``,
        ``warning_count``, ``errors`` (list of str), and ``warnings``
        (list of str). On failure, ``error`` is returned instead.
    """
    try:
        path = resolve_latest(path)
        if not os.path.isfile(path):
            return {"error": f"File not found: {path}"}
        v = HCACellAnnotationValidator()
        is_valid = v.validate_adata(path)
        return {
            "filename": os.path.basename(path),
            "is_valid": is_valid,
            "error_count": len(v.errors),
            "warning_count": len(v.warnings),
            "errors": v.errors,
            "warnings": v.warnings,
        }
    except Exception as e:
        return {"error": str(e)}
