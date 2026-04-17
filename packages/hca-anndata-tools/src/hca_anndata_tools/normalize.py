"""Normalize raw counts in X to standard CXG layout (normalized in X, raw in raw.X)."""

from __future__ import annotations

from datetime import datetime, timezone

import h5py
import numpy as np

from . import __version__
from ._io import open_h5ad
from .write import resolve_latest, write_h5ad

_TARGET_SUM = 1e4
# Sample ~2000 X entries for the integer/sign pre-check; enough to catch
# normalized data on real files while keeping the h5py read trivial.
_SAMPLE_SIZE = 2000


def _inspect_x_file(path: str) -> tuple[bool, np.ndarray]:
    """Return (has_raw, x_sample) read directly from the h5ad via h5py.

    Fail-fast inspection to avoid loading multi-GB files before checking
    preconditions. For sparse X we sample X/data; for dense X we sample
    the first row.
    """
    with h5py.File(path, "r") as f:
        has_raw = "raw/X" in f
        x = f["X"]
        if isinstance(x, h5py.Group) and "data" in x:
            data = x["data"]
            n = min(_SAMPLE_SIZE, len(data))  # pyright: ignore[reportArgumentType]
            sample = np.asarray(data[:n])  # pyright: ignore[reportIndexIssue]
        else:
            sample = np.asarray(x[:1]).ravel()  # pyright: ignore[reportIndexIssue]
        return has_raw, sample


def normalize_raw(path: str) -> dict:
    """Normalize raw counts in X, moving originals to raw.X.

    Produces the standard CXG layout: raw integer counts in raw.X, and
    library-size-normalized, log1p-transformed values in X. Uses the
    scanpy recipe `normalize_total(target_sum=1e4)` + `log1p`.

    Fails if raw.X already exists, or if X contains negative or non-integer
    values (which would indicate it's already normalized). This is an
    explicit wrangler action — there is no force flag.

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

        has_raw, sample = _inspect_x_file(path)
        if has_raw:
            return {"error": "raw.X already exists — refusing to overwrite"}
        if sample.size > 0:
            if (sample < 0).any():
                return {"error": "X contains negative values — not raw counts"}
            if not np.all(np.mod(sample, 1) == 0):
                return {"error": "X contains non-integer values — appears already normalized"}

        with open_h5ad(path, backed=None) as adata:
            adata.raw = adata.copy()
            sc.pp.normalize_total(adata, target_sum=_TARGET_SUM)
            sc.pp.log1p(adata)

            n_obs, n_vars = adata.n_obs, adata.n_vars
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tool": "hca-anndata-tools",
                "tool_version": __version__,
                "operation": "normalize_raw",
                "description": (
                    f"Moved raw counts to raw.X and normalized X with "
                    f"normalize_total(target_sum={_TARGET_SUM:g}) + log1p"
                ),
                "details": {
                    "target_sum": _TARGET_SUM,
                    "n_obs": n_obs,
                    "n_vars": n_vars,
                },
            }

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
