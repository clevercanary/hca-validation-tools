"""Read-only count gate: one streaming pass over the raw count matrix (#686).

The matrix is the one part of an h5ad nothing inspects value by value.
``check_x_normalization`` samples it to say raw-or-normalized; this module
walks the whole of it, in bounded chunks, and reports the defects that have
an objective right answer: negative, non-finite, or non-integer values, cells
with no counts at all, and genes detected in no cell.

Two things it is not. It is not the producer's QC — no thresholds, no
biology, no verdict on a cell being *bad*, only on a value being *impossible*
for a count. And it is not a writer: it returns findings and touches nothing,
so it runs on every file anndata can open, including the nullable-string
files the write tools refuse.

The chunk iterator is public on purpose. #677 (duplicate cells by row hash)
needs exactly this pass and must not pay for a second one; it hashes each
chunk's rows as they go by.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import h5py
import numpy as np
import scipy.sparse as sp
from anndata.io import sparse_dataset

from ._errors import Refusal, failure_result
from ._io import encoding_of, gate_h5ad_paths, obs_index_name, read_index
from ._serialize import make_serializable
from .inspect import _DEFAULT_SAMPLE_SIZE, _classify_x_at_path
from .write import resolve_latest

# Stored entries per chunk. Bounds peak memory by the size of one chunk's
# data + indices (float32 + int32: ~8 bytes an entry, so ~160 MB here) rather
# than by the matrix, whatever the cell count. A single row or column holding
# more than this is read whole — the bound is per chunk, and a chunk is never
# smaller than one row.
DEFAULT_CHUNK_NNZ = 20_000_000

# IDs reported per finding. Enough to recognise a pattern (one sample, one
# prefix), not enough to fill a caller's context.
SAMPLE_ID_LIMIT = 20

MatrixFormat = Literal["csr", "csc", "dense"]

_SPARSE_ENCODINGS: dict[str, MatrixFormat] = {"csr_matrix": "csr", "csc_matrix": "csc"}


@dataclass(frozen=True)
class MatrixChunk:
    """One slab of the matrix, as scipy sparse, with where it sits.

    ``axis`` says which dimension the slab spans: ``"row"`` for CSR and dense
    matrices (``matrix`` is rows ``start:start+n`` x all columns), ``"col"``
    for CSC (all rows x columns ``start:start+n``). CSC is walked by column
    because that is the axis it stores contiguously; slicing it by row reads
    the whole matrix per slice.
    """

    axis: Literal["row", "col"]
    start: int
    matrix: sp.csr_matrix | sp.csc_matrix


def describe_matrix(
    item: h5py.Group | h5py.Dataset | h5py.Datatype, key: str
) -> tuple[MatrixFormat, tuple[int, int], str]:
    """The walkable format, shape, and stored dtype of the matrix at ``key``.

    Raises:
        Refusal: The element is neither a dense 2-D dataset nor a sparse
            group stamped ``csr_matrix`` / ``csc_matrix``. Not reachable
            through today's anndata pin, which reads nothing else into ``X``;
            named here so that an anndata that learns a new format fails this
            gate loudly instead of being walked as if it were CSR.
    """
    if isinstance(item, h5py.Dataset):
        if item.ndim != 2:
            raise Refusal(f"{key} is a {item.ndim}-D dataset; the count gate walks 2-D matrices only")
        return "dense", (int(item.shape[0]), int(item.shape[1])), str(item.dtype)
    if isinstance(item, h5py.Group) and (fmt := _SPARSE_ENCODINGS.get(encoding_of(item) or "")):
        shape = tuple(int(n) for n in item.attrs["shape"])
        data = item["data"]
        assert isinstance(data, h5py.Dataset)
        return fmt, (shape[0], shape[1]), str(data.dtype)
    raise Refusal(
        f"{key} has encoding {encoding_of(item)!r}; the count gate reads csr_matrix, csc_matrix, and dense arrays"
    )


def _chunk_bounds(indptr: np.ndarray, chunk_nnz: int) -> Iterator[tuple[int, int]]:
    """Consecutive ``(start, stop)`` ranges along the compressed axis whose
    stored entries fit in ``chunk_nnz``. A range is never empty: a single row
    or column over budget is yielded alone."""
    n = len(indptr) - 1
    start = 0
    while start < n:
        stop = int(np.searchsorted(indptr, indptr[start] + chunk_nnz, side="right")) - 1
        stop = max(stop, start + 1)
        yield start, min(stop, n)
        start = stop


def iter_matrix_chunks(f: h5py.File, key: str, chunk_nnz: int = DEFAULT_CHUNK_NNZ) -> Iterator[MatrixChunk]:
    """Walk the matrix at ``key`` in slabs of at most ``chunk_nnz`` stored entries.

    Sparse matrices are read through anndata's backed classes
    (``anndata.io.sparse_dataset``): a range slice on the compressed axis is
    one contiguous read of ``data`` and ``indices``, which is the access the
    HDF5 layout was written for. Dense matrices are read as row blocks from the
    h5py dataset — the raw read the contract permits when the job is the
    storage layer itself, and it is here: anndata offers no chunked view of a
    dense ``X`` short of loading it. A dense block is handed on as CSR so every
    consumer sees one shape; a value that is zero on disk carries no
    information a count check needs, and dropping it is what makes the
    per-row "any value at all" test the same question for every format.
    """
    item = f[key]
    fmt, (n_rows, n_cols), _ = describe_matrix(item, key)

    if fmt == "dense":
        assert isinstance(item, h5py.Dataset)
        rows_per_block = max(1, chunk_nnz // max(n_cols, 1))
        for start in range(0, n_rows, rows_per_block):
            block = np.asarray(item[start : start + rows_per_block, :])
            yield MatrixChunk("row", start, sp.csr_matrix(block))
        return

    assert isinstance(item, h5py.Group)
    ds = sparse_dataset(item)
    indptr = np.asarray(item["indptr"][:])  # pyright: ignore[reportIndexIssue]
    if fmt == "csr":
        for start, stop in _chunk_bounds(indptr, chunk_nnz):
            yield MatrixChunk("row", start, ds[start:stop])  # pyright: ignore[reportArgumentType]
    else:
        for start, stop in _chunk_bounds(indptr, chunk_nnz):
            yield MatrixChunk("col", start, ds[:, start:stop])  # pyright: ignore[reportArgumentType]


def _entry_positions(chunk: MatrixChunk) -> tuple[np.ndarray, np.ndarray]:
    """Global ``(row, col)`` of every stored entry in the chunk, in data order."""
    indptr = np.asarray(chunk.matrix.indptr)
    along = np.repeat(np.arange(len(indptr) - 1), np.diff(indptr)) + chunk.start
    across = np.asarray(chunk.matrix.indices)
    return (along, across) if chunk.axis == "row" else (across, along)


def _finding(code: str, count: int, ids: np.ndarray, matrix: str) -> dict:
    return {
        "code": code,
        "count": int(count),
        "sample_ids": [str(v) for v in ids[:SAMPLE_ID_LIMIT]],
        "matrix": matrix,
    }


def _walk(f: h5py.File, key: str, n_obs: int, n_var: int, dtype: str, chunk_nnz: int, check_integers: bool) -> dict:
    """The single pass. Returns per-code value counts, per-row flags, and
    per-column seen flags; the caller turns them into findings."""
    integer_dtype = np.dtype(dtype).kind in "iu"
    counts = {"negative_values": 0, "non_finite_values": 0, "non_integer_values": 0}
    flagged = {code: np.zeros(n_obs, dtype=bool) for code in counts}
    row_nonzero = np.zeros(n_obs, dtype=np.int64)
    col_seen = np.zeros(n_var, dtype=bool)
    chunks = 0

    for chunk in iter_matrix_chunks(f, key, chunk_nnz):
        chunks += 1
        data = np.asarray(chunk.matrix.data)
        if data.size == 0:
            continue
        rows, cols = _entry_positions(chunk)

        finite = np.ones(data.shape, dtype=bool) if integer_dtype else np.isfinite(data)
        masks = {"negative_values": finite & (data < 0)}
        if not integer_dtype:
            masks["non_finite_values"] = ~finite
            if check_integers:
                # Same test check_x_normalization applies to its sample.
                masks["non_integer_values"] = finite & (np.mod(data, 1) != 0)
        for code, mask in masks.items():
            if mask.any():
                counts[code] += int(mask.sum())
                flagged[code][rows[mask]] = True

        nonzero = data != 0  # NaN != 0: a non-finite entry still counts as "a value is here"
        row_nonzero += np.bincount(rows[nonzero], minlength=n_obs)
        col_seen |= np.bincount(cols[nonzero], minlength=n_var) > 0

    return {"counts": counts, "flagged": flagged, "row_nonzero": row_nonzero, "col_seen": col_seen, "chunks": chunks}


def _check_raw_counts_at_path(path: str, chunk_nnz: int) -> dict:
    with h5py.File(path, "r") as f:
        key = "raw/X" if "raw/X" in f else "X"
        item = f[key]
        fmt, (n_obs, n_var), dtype = describe_matrix(item, key)
        nnz = None
        if isinstance(item, h5py.Group):
            indptr = item["indptr"]
            assert isinstance(indptr, h5py.Dataset)
            nnz = int(indptr[-1])

    # Without raw.X the integer criterion has meaning only if X still holds
    # counts. The package's own classifier decides; its verdict is the
    # reason, verbatim, so the result never hedges.
    integer_check = {"status": "applied", "reason": f"{key} is gated as the raw count matrix"}
    if key == "X":
        verdict = _classify_x_at_path(path, _DEFAULT_SAMPLE_SIZE)["verdict"]
        if verdict == "normalized":
            integer_check = {
                "status": "not_applicable",
                "reason": "no raw.X, and check_x_normalization classifies X as normalized",
            }

    result = {
        "filename": Path(path).name,
        "matrix": key,
        "format": fmt,
        "dtype": dtype,
        "n_obs": n_obs,
        "n_var": n_var,
        "nnz": nnz,
        "integer_check": integer_check,
        "chunks": 0,
        "findings": [],
    }
    if n_obs == 0 or n_var == 0:
        result["findings"] = [_finding("empty_matrix", 1, np.asarray([]), key)]
        return result

    with h5py.File(path, "r") as f:
        obs = f["obs"]
        obs_ids = read_index(obs, obs_index_name(obs), "obs")
        var = f["raw/var"] if key == "raw/X" else f["var"]
        var_ids = read_index(var, obs_index_name(var), "raw.var" if key == "raw/X" else "var")
        walked = _walk(f, key, n_obs, n_var, dtype, chunk_nnz, integer_check["status"] == "applied")

    findings = []
    for code in ("negative_values", "non_finite_values", "non_integer_values"):
        if walked["counts"][code]:
            findings.append(_finding(code, walked["counts"][code], obs_ids[walked["flagged"][code]], key))
    zero_rows = np.flatnonzero(walked["row_nonzero"] == 0)
    if zero_rows.size:
        findings.append(_finding("zero_count_cells", zero_rows.size, obs_ids[zero_rows], key))
    # On X this is the vendored validator's check (feature_is_filtered), and
    # two tools disagreeing about one gene helps nobody; raw.X has no such
    # check anywhere else.
    if key == "raw/X":
        unseen = np.flatnonzero(~walked["col_seen"])
        if unseen.size:
            findings.append(_finding("undetected_genes", unseen.size, var_ids[unseen], key))

    result["chunks"] = walked["chunks"]
    result["findings"] = findings
    return cast(dict, make_serializable(result))


@gate_h5ad_paths
def check_raw_counts(path: str, chunk_nnz: int = DEFAULT_CHUNK_NNZ) -> dict:
    """Walk the raw count matrix once and report the values a count cannot hold.

    Gates ``raw.X`` when present, otherwise ``X``. Read-only: never writes,
    never loads the matrix — one streaming pass in chunks of at most
    ``chunk_nnz`` stored entries.

    Args:
        path: Path to an .h5ad file.
        chunk_nnz: Stored entries per chunk; bounds peak memory. Must be >= 1.

    Returns:
        Dict with ``filename``, ``matrix`` (``"raw/X"`` or ``"X"``),
        ``format`` (``csr`` / ``csc`` / ``dense``), ``dtype``, ``n_obs``,
        ``n_var``, ``nnz`` (``None`` for dense), ``integer_check``
        (``status`` ``applied`` / ``not_applicable`` with its ``reason``),
        ``chunks`` read, and ``findings`` — empty when the matrix is clean.
        Each finding: ``code``, ``count``, ``sample_ids`` (at most 20),
        ``matrix``. Codes:

        - ``negative_values`` — count of values below zero; IDs of cells holding one
        - ``non_finite_values`` — count of NaN / Inf; IDs of cells holding one
        - ``non_integer_values`` — count of fractional values; IDs of cells
          holding one. Not applied when ``X`` is the gated matrix and
          ``check_x_normalization`` calls it normalized.
        - ``zero_count_cells`` — cells whose every value is zero
        - ``undetected_genes`` — genes that are zero in every cell; ``raw.X``
          only, since the vendored validator already checks ``X``
        - ``empty_matrix`` — ``n_obs`` or ``n_var`` is zero; nothing else runs

        On failure, ``error`` is returned instead.
    """
    try:
        if not isinstance(chunk_nnz, int) or chunk_nnz < 1:
            return {"error": f"chunk_nnz must be a positive int, got {chunk_nnz!r}"}
        path = resolve_latest(path)
        if not Path(path).is_file():
            return {"error": f"File not found: {path}"}
        return _check_raw_counts_at_path(path, chunk_nnz)
    except Exception as e:
        return failure_result(e)
