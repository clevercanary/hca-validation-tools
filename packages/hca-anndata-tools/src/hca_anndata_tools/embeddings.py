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

from ._io import encoding_of, gate_h5ad_paths, obs_index_name, read_group, read_index
from .qc import DEFAULT_CHUNK_NNZ, finding, run_read_check

# obsm encodings this check reads; None is an unstamped dataset from an
# older anndata. A DataFrame or sparse group is reported as skipped.
_ARRAY_ENCODINGS = ("array", None)
# numpy dtype kinds an embedding can have: float, signed and unsigned int.
# Bool masks, complex, strings, and objects are stored in obsm too, but they
# are not embeddings and are reported as skipped rather than judged.
_NUMERIC_KINDS = "fiu"


@gate_h5ad_paths
def check_embeddings(path: str, chunk_nnz: int = DEFAULT_CHUNK_NNZ) -> dict:
    """Check every embedding in ``obsm`` for the shapes an embedding cannot have.

    Read-only: one pass per array-encoded ``obsm`` key, in row chunks of at
    most ``chunk_nnz`` values, so the scan's own memory is bounded whatever
    the array's size. The gate's anndata open (#667) materialises ``obsm``
    once before that, as it does for every tool. The count matrix is never
    touched.

    Args:
        path: Path to an .h5ad file.
        chunk_nnz: Values per chunk; bounds peak memory. Must be >= 1.

    Returns:
        Dict with ``filename``, ``n_obs``, ``embeddings`` (each checked key
        → ``shape``, ``dtype``, ``encoding``), ``skipped`` (entries that are
        not numeric arrays — a DataFrame, a sparse matrix, a bool mask, a
        string or complex array — each with ``key``, ``encoding``,
        ``reason``), and ``findings``. Empty ``findings`` and
        empty ``skipped`` means every embedding passed; no ``obsm`` at all is
        a clean result with an empty map (#526 owns whether one must exist).
        Each finding: ``code``, ``count``, ``sample_ids`` (at most 20),
        ``matrix`` (``obsm/<key>``). Every offending key is reported. Codes:

        - ``wrong_shape`` — not 2-D, or no columns; ``shape`` carried.
          Nothing else runs on that key.
        - ``non_finite_values`` — rows holding a NaN or Inf; IDs of those cells.
        - ``all_zero`` — every finite value is zero; count and IDs are the
          columns.
        - ``constant`` — every finite value is one non-zero ``value``;
          columns as above.
        - ``zero_variance_columns`` — some columns hold one finite value
          each (or every column does, but not the same value); count and
          IDs are those columns.

        The degeneracy codes are decided as min == max per column over the
        finite values, exactly, so a key with NaN rows can carry one beside
        its ``non_finite_values`` finding. A column with no finite value at
        all is left to ``non_finite_values``.

        The three degeneracy codes are mutually exclusive per key; the most
        specific wins. On failure, ``error`` is returned instead.
    """
    return run_read_check(path, chunk_nnz, _check_embeddings_at_path)


def _check_embeddings_at_path(path: str, chunk_nnz: int) -> dict:
    embeddings: dict[str, dict] = {}
    skipped: list[dict] = []
    findings: list[dict] = []
    with h5py.File(path, "r") as f:
        obs = f["obs"]
        obs_ids = read_index(obs, obs_index_name(obs), "obs")
        obsm = read_group(f, "obsm")
        for key in sorted(obsm.keys()) if obsm is not None else []:
            item = obsm[key]  # pyright: ignore[reportOptionalSubscript]
            encoding = encoding_of(item)
            label = f"obsm/{key}"
            if not isinstance(item, h5py.Dataset) or encoding not in _ARRAY_ENCODINGS:
                skipped.append(
                    {
                        "key": key,
                        "encoding": encoding,
                        "reason": f"{label} is stored as {encoding or 'an unstamped group'}, not an array",
                    }
                )
                continue
            if item.dtype.kind not in _NUMERIC_KINDS:
                skipped.append(
                    {"key": key, "encoding": encoding, "reason": f"{label} has dtype {item.dtype}, not a numeric array"}
                )
                continue
            embeddings[key] = {"shape": list(item.shape), "dtype": str(item.dtype), "encoding": encoding or "unstamped"}
            if item.ndim != 2 or item.shape[1] == 0:
                findings.append(finding("wrong_shape", 1, [], label, shape=list(item.shape)))
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
    """One chunked pass: rows with a non-finite value, and per-column min/max over finite values.

    Reads row slabs straight from the h5py dataset: anndata offers no chunked
    view of a dense array short of loading it whole (the same reason
    :func:`qc.iter_matrix_chunks` gives), and the gate has already proven the
    file opens.
    """
    n_rows, n_cols = ds.shape
    rows_per_chunk = max(1, chunk_nnz // n_cols)
    is_float = ds.dtype.kind == "f"
    # Accumulate in the dataset's own dtype so integers compare exactly
    # (a float64 accumulator would merge int64 values above 2**53).
    if is_float:
        col_min, col_max = np.full(n_cols, np.inf), np.full(n_cols, -np.inf)
    else:
        info = np.iinfo(ds.dtype)
        col_min, col_max = np.full(n_cols, info.max, ds.dtype), np.full(n_cols, info.min, ds.dtype)
    bad_rows: list[np.ndarray] = []
    for start in range(0, n_rows, rows_per_chunk):
        block = np.asarray(ds[start : start + rows_per_chunk])
        if is_float:
            finite = np.isfinite(block)
            bad = ~finite.all(axis=1)
            if bad.any():
                bad_rows.append(np.flatnonzero(bad) + start)
                # fmin / fmax ignore NaN, so masking Inf to NaN in place folds
                # each column's finite range without a warning or a copy.
                block[~finite] = np.nan
            del finite, bad
        col_min = np.fmin(col_min, np.fmin.reduce(block, axis=0))
        col_max = np.fmax(col_max, np.fmax.reduce(block, axis=0))
        del block  # release the slab and its masks before the next read

    findings: list[dict] = []
    if bad_rows:
        rows = np.concatenate(bad_rows)
        findings.append(finding("non_finite_values", len(rows), obs_ids[rows], label))
    has_finite = col_min <= col_max  # a column with no finite value keeps its +inf / -inf seeds
    dead = has_finite & (col_min == col_max)
    if dead.any():
        columns = np.flatnonzero(dead)
        values = col_min[dead]
        if dead.all() and np.all(values == values[0]):
            value = float(values[0])
            findings.append(
                finding("all_zero", n_cols, columns, label)
                if value == 0
                else finding("constant", n_cols, columns, label, value=value)
            )
        else:
            findings.append(finding("zero_variance_columns", len(columns), columns, label))
    return findings
