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

The chunk iterator is public on purpose: #677 (duplicate cells by row hash)
walks the same matrix through it, so the two tools share one bounded read
path rather than two. Each is still its own pass over the file; a shared
per-chunk driver that runs several consumers in one pass is a possibility the
sibling reports (#687 per-cell totals, #688 gene-subset fractions) may
justify, not something ``_walk`` provides today.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import h5py
import numpy as np
import scipy.sparse as sp
from anndata.io import sparse_dataset

from ._errors import Refusal, failure_result
from ._io import MatrixFormat, describe_matrix, gate_h5ad_paths, obs_index_name, read_index
from .inspect import resolve_count_matrix
from .write import resolve_latest

# Stored entries per chunk. Bounds peak memory by the chunk, not the matrix,
# whatever the cell count: one chunk is data + indices (float32 + int32, 8
# bytes an entry, 160 MB here), and the walk's working set was measured at
# about 2x that — the masks built over the chunk, plus the next slab arriving
# while they are still live — so ~350 MB at this default. A single row or
# column holding more than this is read whole: the bound is per chunk, and a
# chunk is never smaller than one row.
DEFAULT_CHUNK_NNZ = 20_000_000

# IDs reported per finding. Enough to recognise a pattern (one sample, one
# prefix), not enough to fill a caller's context.
SAMPLE_ID_LIMIT = 20

_VALUE_CODES = ("negative_values", "non_finite_values", "non_integer_values")


@dataclass(frozen=True)
class MatrixChunk:
    """One slab of the matrix, as scipy sparse, with where it sits.

    ``axis`` says which dimension the slab spans: ``"row"`` for CSR and dense
    matrices (``matrix`` is rows ``start:start+n`` x all columns), ``"col"``
    for CSC (all rows x columns ``start:start+n``).
    """

    axis: Literal["row", "col"]
    start: int
    matrix: sp.csr_matrix | sp.csc_matrix


def chunk_bounds(indptr: np.ndarray, chunk_nnz: int) -> Iterator[tuple[int, int]]:
    """Consecutive ``(start, stop)`` ranges along the compressed axis whose
    stored entries fit in ``chunk_nnz``. A range is never empty: a single row
    or column over budget is yielded alone."""
    # int64 on purpose: scipy keeps indptr int32 while nnz fits, and under
    # NumPy 2 an int32 scalar plus a Python int stays int32 — near 2^31 the
    # bound wraps negative and every remaining row becomes its own chunk.
    indptr = np.asarray(indptr, dtype=np.int64)
    n = len(indptr) - 1
    start = 0
    while start < n:
        stop = int(np.searchsorted(indptr, indptr[start] + chunk_nnz, side="right")) - 1
        stop = max(stop, start + 1)
        yield start, stop
        start = stop


def iter_matrix_chunks(
    f: h5py.File, key: str, chunk_nnz: int = DEFAULT_CHUNK_NNZ, *, axis: Literal["row", "any"] = "row"
) -> Iterator[MatrixChunk]:
    """Walk the matrix at ``key`` in slabs of at most ``chunk_nnz`` stored entries.

    ``axis`` is what the consumer needs. ``"row"`` (the default, and what a
    per-cell consumer such as #677's row hash wants) refuses a CSC matrix by
    name: CSC stores columns contiguously, so a bounded row slab is not
    available from it. ``"any"`` accepts CSC and walks it by column, for a
    consumer that only needs every stored entry once, whichever way it
    arrives — this gate.

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
    if not isinstance(chunk_nnz, int) or chunk_nnz < 1:
        raise ValueError(f"chunk_nnz must be a positive int, got {chunk_nnz!r}")
    item = f[key]
    fmt, (n_rows, n_cols), _ = describe_matrix(item, key)

    if fmt == "dense":
        assert isinstance(item, h5py.Dataset)
        rows_per_block = max(1, chunk_nnz // max(n_cols, 1))
        for start in range(0, n_rows, rows_per_block):
            yield MatrixChunk("row", start, dense_block_as_csr(item[start : start + rows_per_block, :]))
        return

    if fmt == "csc" and axis == "row":
        raise Refusal(
            f"{key} is csc_matrix, which cannot be walked by row in bounded memory; "
            f"pass axis='any' to walk it by column"
        )

    assert isinstance(item, h5py.Group)
    ds = sparse_dataset(item)
    indptr = np.asarray(item["indptr"][:])  # pyright: ignore[reportIndexIssue]
    along: Literal["row", "col"] = "row" if fmt == "csr" else "col"
    for start, stop in chunk_bounds(indptr, chunk_nnz):
        slab = ds[start:stop] if along == "row" else ds[:, start:stop]
        yield MatrixChunk(along, start, slab)  # pyright: ignore[reportArgumentType]
        del slab  # otherwise it lives until the next read completes: two chunks resident


def dense_block_as_csr(block: np.ndarray) -> sp.csr_matrix:
    """A dense row block as CSR, the one shape every consumer sees.

    float16 is upcast first: anndata writes and reads it, scipy.sparse will
    not hold it. A zero on disk carries no information a count check needs,
    so dropping it is what makes the per-row "any value at all" question the
    same for every format.
    """
    if block.dtype == np.float16:
        block = block.astype(np.float32)
    return sp.csr_matrix(block)


def finding(code: str, count: int, ids: np.ndarray | list, matrix: str, **detail) -> dict:
    """One finding: what, how many, which cells (or genes, or columns), on which element.

    ``matrix`` is the HDF5 element the finding was computed from — a count
    matrix (``X``, ``raw/X``), an embedding (``obsm/<key>``), or an index
    (``obs/<name>``, #679) — so a renderer can say *where* without knowing
    the code. The name predates the non-matrix users and is kept for the
    released JSON. ``sample_ids`` always names what ``count`` counts, capped,
    so the same renderer can say "which". A finding about the element as a
    whole (``empty_matrix``, ``wrong_shape``) has ``count`` 1 and an empty
    ``sample_ids``: the ``matrix`` field already names it. ``detail`` is
    additive structure a code may carry beyond that (a duplicate finding's
    groups, say) and never replaces it.
    """
    return {
        "code": code,
        "count": int(count),
        "sample_ids": [str(v) for v in ids[:SAMPLE_ID_LIMIT]],
        "matrix": matrix,
        **detail,
    }


def run_read(path: str, body: Callable[[str], dict]) -> dict:
    """The handler every read-only check shares: resolve, run, report.

    Nothing here is matrix-specific — the embedding gate (#685) and the
    barcode report (#679) use it too.

    ``body`` gets the resolved path and returns the result dict; anything it
    raises comes back through :func:`failure_result`, so a refusal keeps its
    words and an accident keeps its traceback.
    """
    try:
        path = resolve_latest(path)
        if not Path(path).is_file():
            return {"error": f"File not found: {path}"}
        return body(path)
    except Exception as e:
        return failure_result(e)


def run_read_check(path: str, chunk_nnz: int, body: Callable[[str, int], dict]) -> dict:
    """:func:`run_read` for the chunked checks: validates ``chunk_nnz`` first, then hands it to ``body``."""
    if error := positive_int_error("chunk_nnz", chunk_nnz):
        return {"error": error}
    return run_read(path, lambda resolved: body(resolved, chunk_nnz))


def positive_int_error(name: str, value: object) -> str | None:
    """Why ``value`` is not a positive int for the ``name`` argument, or None when it is.

    The one wording every tool knob (``chunk_nnz``, ``shapes``) refuses with.
    ``bool`` is rejected explicitly: ``isinstance(True, int)`` holds, and a
    knob set to ``True`` meaning ``1`` is a mistake, not a request.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return f"{name} must be a positive int, got {value!r}"
    return None


def _walk(f: h5py.File, key: str, n_obs: int, n_var: int, chunk_nnz: int, check_integers: bool) -> tuple:
    """The single pass. Returns ``(counts, flagged, genes_per_cell, gene_seen)``:
    per-code value counts, per-code cell flags, non-zero entries per cell
    (genes detected — explicit zeros are eliminated first), and whether each
    gene has a non-zero entry anywhere.

    Nothing here is sized by the chunk's entry count except the masks over
    ``data``: flagged cells come from ``searchsorted`` on ``indptr`` for the
    few hits, and the per-cell / per-gene tallies come from ``indptr`` and a
    boolean scatter of ``indices``. Building a per-entry row array was
    measured at 3x the whole walk's cost on a 20M-entry chunk.
    """
    counts: dict[str, int] = dict.fromkeys(_VALUE_CODES, 0)
    flagged = {code: np.zeros(n_obs, dtype=bool) for code in _VALUE_CODES}
    genes_per_cell = np.zeros(n_obs, dtype=np.int64)
    gene_seen = np.zeros(n_var, dtype=bool)

    for chunk in iter_matrix_chunks(f, key, chunk_nnz, axis="any"):
        m = chunk.matrix
        m.eliminate_zeros()  # an explicit zero is not a count; NaN survives (NaN != 0)
        data = m.data
        if data.size == 0:
            del chunk, m, data  # nothing to tally, but still the last reference to the slab
            continue
        indptr = np.asarray(m.indptr)
        indices = np.asarray(m.indices)

        finite = np.isfinite(data)
        masks = {"negative_values": finite & (data < 0), "non_finite_values": ~finite}
        if check_integers and data.dtype.kind == "f":
            masks["non_integer_values"] = finite & (data != np.floor(data))
        for code, mask in masks.items():
            hits = np.flatnonzero(mask)
            if hits.size:
                counts[code] += int(hits.size)
                if chunk.axis == "row":
                    flagged[code][np.searchsorted(indptr, hits, side="right") - 1 + chunk.start] = True
                else:
                    flagged[code][indices[hits]] = True

        stored = np.diff(indptr)
        if chunk.axis == "row":
            genes_per_cell[chunk.start : chunk.start + stored.size] += stored
            gene_seen[indices] = True
        else:
            gene_seen[chunk.start : chunk.start + stored.size] |= stored > 0
            genes_per_cell += np.bincount(indices, minlength=n_obs)
        # The loop variable is the last reference to the slab; without dropping
        # it too, the previous chunk stays resident while the next one is read.
        del chunk, m, data, indices, indptr, stored, finite, masks

    return counts, flagged, genes_per_cell, gene_seen


@dataclass(frozen=True)
class CountMatrix:
    """The count matrix a read-only check walks, with what every such check
    needs to know before its first chunk. See :func:`open_count_matrix`."""

    key: str
    integer_check: dict
    format: MatrixFormat
    n_obs: int
    n_var: int
    dtype: str
    nnz: int | None
    obs_ids: np.ndarray

    @property
    def var_key(self) -> str:
        """The dataframe that names this matrix's columns."""
        return "raw/var" if self.key == "raw/X" else "var"

    def read_var_ids(self, f: h5py.File) -> np.ndarray:
        """The var index that names this matrix's columns, refused by name when it cannot.

        The var half of the preamble ``open_count_matrix`` does for obs: the
        dataframe must exist and its index must be as wide as the matrix.
        anndata's backed open checks neither for ``raw/var``.
        """
        if self.var_key not in f:
            raise Refusal(f"{self.key} is present but {self.var_key} is not, so its genes cannot be named")
        var = f[self.var_key]
        var_ids = read_index(var, obs_index_name(var), self.var_key.replace("/", "."))
        if len(var_ids) != self.n_var:
            raise Refusal(f"{self.var_key} has {len(var_ids)} IDs but {self.key} has {self.n_var} columns")
        return var_ids

    def envelope(self, path: str) -> dict:
        """The result keys every count-matrix check reports, in one order."""
        return {
            "filename": Path(path).name,
            "matrix": self.key,
            "format": self.format,
            "dtype": self.dtype,
            "n_obs": self.n_obs,
            "n_var": self.n_var,
            "nnz": self.nnz,
        }


def open_count_matrix(f: h5py.File) -> CountMatrix:
    """Resolve, describe, and index-check the count matrix in an open file.

    The preamble every count-matrix check shares (this gate, #677's duplicate
    hash): which matrix, its format and shape, and the obs index that names
    its rows. anndata's backed open does not check the index against the
    matrix, so a shortened obs passes the gate; it is read here and refused
    by name, rather than IndexError on the first finding or name the wrong
    cell when none fires.
    """
    key, integer_check = resolve_count_matrix(f)
    item = f[key]
    fmt, (n_obs, n_var), dtype = describe_matrix(item, key)
    nnz = None
    if isinstance(item, h5py.Group):
        indptr = item["indptr"]
        assert isinstance(indptr, h5py.Dataset)
        nnz = int(indptr[-1])
    obs = f["obs"]
    obs_ids = read_index(obs, obs_index_name(obs), "obs")
    if len(obs_ids) != n_obs:
        raise Refusal(f"obs has {len(obs_ids)} IDs but {key} has {n_obs} rows")
    return CountMatrix(key, integer_check, fmt, n_obs, n_var, dtype, nnz, obs_ids)


def _check_raw_counts_at_path(path: str, chunk_nnz: int) -> dict:
    with h5py.File(path, "r") as f:
        cm = open_count_matrix(f)
        var_ids = cm.read_var_ids(f)

        findings = []
        if cm.n_obs == 0 or cm.n_var == 0:
            findings.append(finding("empty_matrix", 1, [], cm.key))
        else:
            counts, flagged, genes_per_cell, gene_seen = _walk(
                f, cm.key, cm.n_obs, cm.n_var, chunk_nnz, cm.integer_check["status"] == "applied"
            )
            for code in _VALUE_CODES:
                if counts[code]:
                    findings.append(finding(code, counts[code], cm.obs_ids[flagged[code]], cm.key))
            zero_rows = np.flatnonzero(genes_per_cell == 0)
            if zero_rows.size:
                findings.append(finding("zero_count_cells", zero_rows.size, cm.obs_ids[zero_rows], cm.key))
            unseen = np.flatnonzero(~gene_seen)
            if unseen.size:
                findings.append(finding("undetected_genes", unseen.size, var_ids[unseen], cm.key))

    return {**cm.envelope(path), "integer_check": cm.integer_check, "findings": findings}


@gate_h5ad_paths
def check_raw_counts(path: str, chunk_nnz: int = DEFAULT_CHUNK_NNZ) -> dict:
    """Walk the raw count matrix once and report the values a count cannot hold.

    Gates ``raw.X`` when present, otherwise ``X``. Read-only: never writes,
    never loads the matrix — one streaming pass in chunks of at most
    ``chunk_nnz`` stored entries.

    ``raw.X`` is asserted to be counts, not classified: the schema gives it no
    other meaning, so a ``raw.X`` holding normalized values is a defect and
    comes back as ``non_integer_values`` with ``count`` equal to every stored
    entry. (``normalize_raw`` samples the same matrix and refuses instead —
    it is about to write on top of it; this tool exists to report it.) A lone
    ``X`` is different: the schema allows it to be normalized, so there the
    classifier decides whether the integer criterion applies.

    Args:
        path: Path to an .h5ad file.
        chunk_nnz: Stored entries per chunk; bounds peak memory. Must be >= 1.

    Returns:
        Dict with ``filename``, ``matrix`` (``"raw/X"`` or ``"X"``),
        ``format`` (``csr`` / ``csc`` / ``dense``), ``dtype``, ``n_obs``,
        ``n_var``, ``nnz`` (``None`` for dense), ``integer_check``
        (``status`` ``applied`` / ``not_applicable`` with its ``reason``),
        and ``findings``. Empty findings with ``integer_check.status ==
        "applied"`` means the counts are clean; with ``not_applicable`` it
        means the file has no raw matrix and ``X`` is not counts, so only the
        criteria that hold for any matrix were run. Each finding:
        ``code``, ``count``, ``sample_ids`` (at most 20), ``matrix``. Codes:

        - ``negative_values`` — count of values below zero; IDs of cells holding one
        - ``non_finite_values`` — count of NaN / Inf; IDs of cells holding one
        - ``non_integer_values`` — count of fractional values; IDs of cells
          holding one. Not applied when ``X`` is the gated matrix and
          ``check_x_normalization`` calls it normalized.
        - ``zero_count_cells`` — cells whose every value is zero
        - ``undetected_genes`` — genes that are zero in every cell
        - ``empty_matrix`` — ``n_obs`` or ``n_var`` is zero; nothing else runs

        On failure, ``error`` is returned instead.
    """
    return run_read_check(path, chunk_nnz, _check_raw_counts_at_path)
