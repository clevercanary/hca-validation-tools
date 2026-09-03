"""Embedding gate: every obsm array is finite and non-degenerate (#685).

Not a Lattice port. This check is our own, split out of the matrix QC
report (#644) because it is obs-sized and needs none of the count pass.

An embedding that survived a subset without being recomputed, or a
transplant that mis-aligned rows, leaves NaN rows, dead columns, or a
constant array behind while the file stays structurally valid. #645
(embedding agrees with labels) assumes this gate has passed: label purity
on an embedding with NaN rows is noise.

The row count is anndata's check, not ours. ``ad.read_h5ad`` refuses an
obsm array whose rows do not match obs ("Values of obsm must match
dimensions ('obs',) of parent") in both backed and in-memory mode, so the
gate every tool opens through (#667) reports that before this code runs.
What anndata does accept — a 1-D array, a NaN row, a constant array — is
what this check is for.
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np

from ._io import encoding_of, gate_h5ad_paths, obs_index_name, read_index
from .qc import DEFAULT_CHUNK_NNZ, finding, run_count_check

# obsm encodings this check reads; None is an unstamped dataset from an
# older anndata. A DataFrame or sparse group is reported as skipped.
_ARRAY_ENCODINGS = ("array", None)


@gate_h5ad_paths
def check_embeddings(path: str, chunk_nnz: int = DEFAULT_CHUNK_NNZ) -> dict:
    """Check every embedding in ``obsm`` for the shapes an embedding cannot have.

    Read-only: one pass per array-encoded ``obsm`` key, in row chunks of at
    most ``chunk_nnz`` values, so peak memory is bounded whatever the
    array's size. The count matrix is never touched.

    Args:
        path: Path to an .h5ad file.
        chunk_nnz: Values per chunk; bounds peak memory. Must be >= 1.

    Returns:
        Dict with ``filename``, ``n_obs``, ``embeddings`` (each checked key
        → ``shape``, ``dtype``, ``encoding``), ``skipped`` (entries that are
        not arrays — a DataFrame or sparse matrix — each with ``key``,
        ``encoding``, ``reason``), and ``findings``. Empty ``findings`` and
        empty ``skipped`` means every embedding passed; no ``obsm`` at all is
        a clean result with an empty map (#526 owns whether one must exist).
        Each finding: ``code``, ``count``, ``sample_ids`` (at most 20),
        ``matrix`` (``obsm/<key>``). Every offending key is reported. Codes:

        - ``wrong_shape`` — not 2-D, or no columns; ``shape`` carried.
          Nothing else runs on that key.
        - ``non_finite_values`` — rows holding a NaN or Inf; IDs of those cells.
        - ``all_zero`` — every value is zero; count and IDs are the columns.
        - ``constant`` — every value is one non-zero ``value``; columns as above.
        - ``zero_variance_columns`` — some columns hold one value each (or
          every column does, but not the same value); count and IDs are
          those columns. Decided as min == max over finite values, exactly.
          A column with no finite value at all is left to
          ``non_finite_values``.

        The three degeneracy codes are mutually exclusive per key; the most
        specific wins. On failure, ``error`` is returned instead.
    """
    return run_count_check(path, chunk_nnz, _check_embeddings_at_path)


def _check_embeddings_at_path(path: str, chunk_nnz: int) -> dict:
    embeddings: dict[str, dict] = {}
    skipped: list[dict] = []
    findings: list[dict] = []
    with h5py.File(path, "r") as f:
        obs = f["obs"]
        obs_ids = read_index(obs, obs_index_name(obs), "obs")
        obsm = f.get("obsm")
        for key in sorted(obsm.keys()) if isinstance(obsm, h5py.Group) else []:
            item = obsm[key]  # pyright: ignore[reportOptionalSubscript]
            label = f"obsm/{key}"
            if not isinstance(item, h5py.Dataset | h5py.Group):
                skipped.append({"key": key, "encoding": None, "reason": f"{label} is a link, not an array"})
                continue
            encoding = encoding_of(item)
            if not isinstance(item, h5py.Dataset) or encoding not in _ARRAY_ENCODINGS:
                skipped.append(
                    {
                        "key": key,
                        "encoding": encoding,
                        "reason": f"{label} is stored as {encoding or 'an unstamped group'}, not an array",
                    }
                )
                continue
            embeddings[key] = {"shape": list(item.shape), "dtype": str(item.dtype), "encoding": encoding or "unstamped"}
            if item.ndim != 2 or item.shape[1] == 0:
                findings.append(finding("wrong_shape", 1, [key], label, shape=list(item.shape)))
                continue
            findings.extend(_scan_embedding(item, label, obs_ids, chunk_nnz))
    return {
        "filename": Path(path).name,
        "n_obs": len(obs_ids),
        "embeddings": embeddings,
        "skipped": skipped,
        "findings": findings,
    }


def _scan_embedding(ds: h5py.Dataset, label: str, obs_ids: np.ndarray, chunk_nnz: int) -> list[dict]:
    """One chunked pass: rows with a non-finite value, and per-column min/max over finite values."""
    n_rows, n_cols = ds.shape
    rows_per_chunk = max(1, chunk_nnz // n_cols)
    is_float = ds.dtype.kind == "f"
    col_min = np.full(n_cols, np.inf)
    col_max = np.full(n_cols, -np.inf)
    bad_rows: list[np.ndarray] = []
    for start in range(0, n_rows, rows_per_chunk):
        block = np.asarray(ds[start : start + rows_per_chunk])
        if is_float:
            finite = np.isfinite(block)
            bad = ~finite.all(axis=1)
            if bad.any():
                bad_rows.append(np.flatnonzero(bad) + start)
            # fmin / fmax ignore NaN, so masking non-finite values to NaN
            # folds each column's finite range without a warning.
            block = np.where(finite, block, np.nan)
        col_min = np.fmin(col_min, np.fmin.reduce(block, axis=0))
        col_max = np.fmax(col_max, np.fmax.reduce(block, axis=0))

    findings: list[dict] = []
    if bad_rows:
        rows = np.concatenate(bad_rows)
        findings.append(finding("non_finite_values", len(rows), obs_ids[rows], label))
    has_finite = np.isfinite(col_min)  # a column with no finite value stays at +inf
    dead = has_finite & (col_min == col_max)
    if dead.any():
        columns = np.flatnonzero(dead)
        values = col_min[dead]
        if dead.all() and np.all(values == 0):
            findings.append(finding("all_zero", n_cols, columns, label))
        elif dead.all() and np.all(values == values[0]):
            findings.append(finding("constant", n_cols, columns, label, value=float(values[0])))
        else:
            findings.append(finding("zero_variance_columns", len(columns), columns, label))
    return findings
