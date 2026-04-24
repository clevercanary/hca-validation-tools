"""MCP wrapper for hca_schema_validator.check_cosmetic_labels."""

import os

from hca_anndata_tools._io import open_h5ad
from hca_anndata_tools.write import resolve_latest
from hca_schema_validator import check_cosmetic_labels


def check_cosmetic_labels_h5ad(path: str) -> dict:
    """Check producer-supplied obs label columns against their `*_ontology_term_id` siblings.

    Targeted alternative to :func:`validate_schema` — runs only the producer-
    cosmetic-column check (issue #377), skipping the full schema/raw/feature
    validation pipeline. Useful when a curator wants quick feedback on
    label/ID drift without paying for a full validate run.

    For each of the eight controlled HCA obs label columns
    (:data:`hca_schema_validator.HCA_DERIVED_OBS_LABELS`):

    * column present → warning ("delete the column")
    * column present + source `*_ontology_term_id` present → row-level checks:
        - cosmetic value with NaN term ID → error
        - cosmetic value disagrees with canonical ontology label → error

    Args:
        path: Path to an .h5ad file. Auto-resolves to the latest timestamped
            edit snapshot before reading.

    Returns:
        Dict with ``filename``, ``warning_count``, ``error_count``,
        ``warnings`` (list of str), ``errors`` (list of str), and ``is_clean``
        (True iff both lists are empty). On failure, ``error`` is returned
        instead.
    """
    try:
        path = resolve_latest(path)
        if not os.path.isfile(path):
            return {"error": f"File not found: {path}"}
        with open_h5ad(path, backed="r") as adata:
            warnings, errors = check_cosmetic_labels(adata)
        return {
            "filename": os.path.basename(path),
            "warning_count": len(warnings),
            "error_count": len(errors),
            "warnings": warnings,
            "errors": errors,
            "is_clean": not warnings and not errors,
        }
    except Exception as e:
        return {"error": str(e)}
