"""MCP wrapper for hca_schema_validator.HCAValidator."""

import os

from hca_anndata_tools.write import resolve_latest
from hca_schema_validator import HCAValidator


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
