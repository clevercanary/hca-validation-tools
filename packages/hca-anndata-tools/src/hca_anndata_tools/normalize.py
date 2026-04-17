"""Normalize raw counts in X to standard CXG layout (normalized in X, raw in raw.X)."""

from __future__ import annotations

from ._io import open_h5ad
from .inspect import inspect_x
from .write import make_edit_entry, resolve_latest, write_h5ad

_TARGET_SUM = 1e4


def normalize_raw(path: str) -> dict:
    """Normalize raw counts in X, moving originals to raw.X.

    Produces the standard CXG layout: raw integer counts in raw.X, and
    library-size-normalized, log1p-transformed values in X. Uses the
    scanpy recipe `normalize_total(target_sum=1e4)` + `log1p`.

    Fails if raw.X already exists, or if a sample of X (up to 2000 values)
    contains negative or non-integer values (which would indicate it's
    already normalized). The X check is a fail-fast heuristic, not a
    full-matrix guarantee — a file that looks like raw counts in its first
    few thousand entries but has fractional values elsewhere will pass
    this check. This is an explicit wrangler action — there is no force
    flag.

    The output is written as an edit snapshot (`<stem>-edit-<ts>.h5ad`)
    and the operation is logged in `uns['provenance']['edit_history']`.

    Args:
        path: Path to an .h5ad file.

    Returns:
        Dict with 'output_path', 'n_obs', 'n_vars', 'target_sum' on success,
        or {'error': ...} on failure.
    """
    try:
        import scanpy as sc

        path = resolve_latest(path)

        check = inspect_x(path)
        if "error" in check:
            return check
        if check["has_raw_x"]:
            return {"error": "raw.X already exists — refusing to overwrite"}
        if check["has_negative"]:
            return {"error": "X sample contains negative values — not raw counts"}
        if check["nonzero_count"] > 0 and not check["is_integer_valued"]:
            return {"error": "X sample contains non-integer values — appears already normalized"}

        with open_h5ad(path, backed=None) as adata:
            # CXG schema forbids feature_is_filtered in raw.var.
            raw_source = adata.copy()
            raw_source.var = raw_source.var.drop(
                columns=["feature_is_filtered"], errors="ignore"
            )
            adata.raw = raw_source
            sc.pp.normalize_total(adata, target_sum=_TARGET_SUM)
            sc.pp.log1p(adata)
            # scanpy stamps uns['log1p'] = {'base': None}; None drops on h5ad
            # write, leaving {} which CXG rejects.
            adata.uns.pop("log1p", None)

            n_obs, n_vars = adata.n_obs, adata.n_vars
            entry = make_edit_entry(
                operation="normalize_raw",
                description=(
                    f"Moved raw counts to raw.X and normalized X with "
                    f"normalize_total(target_sum={_TARGET_SUM:g}) + log1p"
                ),
                details={
                    "target_sum": _TARGET_SUM,
                    "n_obs": n_obs,
                    "n_vars": n_vars,
                },
            )

            result = write_h5ad(adata, path, [entry])

        if "error" in result:
            return result

        return {
            "output_path": result["output_path"],
            "n_obs": n_obs,
            "n_vars": n_vars,
            "target_sum": _TARGET_SUM,
        }

    except Exception as e:
        return {"error": str(e)}
