"""Duplicated cells by raw count content hash (#677).

A port of ``evaluate_dup_counts`` from Lattice Data Coordination's
lattice-tools, ``cellxgene_resources/cellxgene_mods.py`` at commit
``8778a14f2a5a7039acf3ce74b3da220c24521905``:
https://github.com/Lattice-Data/lattice-tools/blob/8778a14f2a5a7039acf3ce74b3da220c24521905/cellxgene_resources/cellxgene_mods.py

    MIT License

    Copyright (c) 2020 Lattice Data Coordination

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

The original, in two passes over an in-memory CSR matrix: canonicalize
(``sort_indices``, ``sum_duplicates``, reporting how many non-zeros that
dissolved), hash every row's ``data`` slice and keep the rows whose hash
collides, then hash those rows' ``indices`` slice — two rows are duplicates
only when both match, which separates a cell from another that merely shares
its value multiset.

Deviations from the original, each with its reason:

1. **Streaming, not loaded.** Pass one walks :func:`qc.iter_matrix_chunks`;
   pass two re-reads only the colliding rows through anndata's backed class.
   The original loads the object, which the 20-30 GB atlas objects forbid.
2. **Canonicalized in memory, never on disk.** The original sorts and sums
   the object it was handed. This tool is read-only, so each chunk is
   canonicalized after it is read and the file is untouched; the count of
   rows that were non-canonical on disk is reported as information.
3. **Empty rows excluded.** Rows with no stored value all hash alike and are
   not duplicates of each other; ``check_raw_counts`` reports them as
   ``zero_count_cells``. The original has no such rows to worry about after
   its Visium ``in_tissue`` filter.
4. **Colliding rows compared in full.** The original's second pass hashes
   ``indices``; this one compares the canonical ``(indices, data)`` bytes
   exactly, so a hash collision cannot produce a false group. The hash is
   ``blake2b`` (8-byte digest) rather than Python's ``hash``, which is
   randomized per process and would make two runs disagree.
5. **No Visium handling.** HCA has no spatial objects; the ``in_tissue``
   filter is dropped.
6. **Dense matrices accepted.** The original refuses anything but CSR; the
   chunk iterator hands dense blocks on as CSR, so they walk the same way.
   CSC is refused by name.
7. **Explicit zeros dropped before hashing.** scipy's canonical format
   permits a stored zero, so the original hashes ``[1, 0, 2]`` and ``[1, 2]``
   as different rows. A stored zero is not a count; here the two are the same
   cell, and a row of nothing but stored zeros is an empty row (deviation 3).
   ``non_canonical_rows`` does not count them, since scipy does not either.

Pass two is bounded by the colliding rows, not the matrix, and on real data
those are the duplicates themselves: each is re-read once (one HDF5 read per
scattered row, about 1.6 ms on a gzip file) and one copy of each *distinct*
row's bytes is held while grouping. A file with very many duplicates — a
source dataset ingested twice — pays minutes and holds a row per group; a
pathological file whose every row collides on hash but differs in content
would hold most of the matrix. Both are accepted rather than engineered
around: the exact comparison is the point.

Two assumptions, considered and kept, because real atlas cells carry
hundreds of detected genes:

- On a lone ``X`` the classifier calls normalized, identical rows are taken
  to mean identical cells. Two *different* cells become identical under
  per-cell normalization only when every detected gene scales by the same
  factor — a proportional count vector across hundreds of genes, which does
  not occur in practice.
- Pass one hashes values without column positions, as the original does.
  Rows sharing a value sequence but not a gene set (every count equal to 1
  over the same number of genes, say) collide and are all re-read in pass
  two; that is slower, never wrong, and was measured at zero collisions
  across seven gut-v1 source datasets. A QC-filtered cell with 200 or more
  genes essentially never has every count equal to 1.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict

import h5py
import numpy as np
import scipy.sparse as sp
from anndata.io import sparse_dataset

from ._errors import Refusal
from ._io import gate_h5ad_paths
from .qc import (
    DEFAULT_CHUNK_NNZ,
    SAMPLE_ID_LIMIT,
    CountMatrix,
    chunk_bounds,
    dense_block_as_csr,
    finding,
    iter_matrix_chunks,
    open_count_matrix,
    run_count_check,
)

# Groups reported per finding; each group lists at most SAMPLE_ID_LIMIT IDs.
SAMPLE_GROUP_LIMIT = 20


def _row_hash(values: np.ndarray) -> np.int64:
    """A stable 64-bit hash of a row's canonical values (deviation 4).

    Decoded little-endian so the same digest is the same integer on any host."""
    return np.frombuffer(hashlib.blake2b(values.tobytes(), digest_size=8).digest(), dtype="<i8")[0]


def _non_canonical_rows(m: sp.csr_matrix) -> int:
    """Rows whose stored indices are unsorted or repeated, before canonicalizing.

    scipy's own flag answers the common case in one C pass; the per-row count
    is computed only for a chunk that fails it. A row is canonical when its
    indices strictly increase, so every position where ``np.diff`` is not
    positive is a violation unless it is a row start, where the comparison
    crossed into the previous row.
    """
    if m.has_canonical_format:
        return 0
    indices = np.asarray(m.indices)
    indptr = np.asarray(m.indptr)
    bad = np.flatnonzero(np.diff(indices) <= 0) + 1
    rows = np.searchsorted(indptr, bad, side="right") - 1
    rows = rows[indptr[rows] != bad]
    return int(np.unique(rows).size)


def _canonicalize(m: sp.csr_matrix) -> sp.csr_matrix:
    """The original's canonical step, on a chunk we own (deviation 2)."""
    m.sort_indices()
    m.sum_duplicates()
    m.eliminate_zeros()
    return m


def _hash_rows(f: h5py.File, cm: CountMatrix, chunk_nnz: int) -> tuple[np.ndarray, np.ndarray, int]:
    """Pass one: a hash per row of the canonical values, which rows hold a
    value at all (deviation 3), and the non-canonical row count."""
    hashes = np.zeros(cm.n_obs, dtype=np.int64)
    stored = np.zeros(cm.n_obs, dtype=bool)
    non_canonical = 0
    for chunk in iter_matrix_chunks(f, cm.key, chunk_nnz, axis="row"):
        m = chunk.matrix
        assert isinstance(m, sp.csr_matrix)
        non_canonical += _non_canonical_rows(m)
        m = _canonicalize(m)
        indptr = np.asarray(m.indptr)
        data = np.asarray(m.data)
        for i in range(len(indptr) - 1):
            start, stop = int(indptr[i]), int(indptr[i + 1])
            if stop > start:
                hashes[chunk.start + i] = _row_hash(data[start:stop])
                stored[chunk.start + i] = True
        del chunk, m, data, indptr  # the loop variable is the last reference to the slab
    return hashes, stored, non_canonical


class _RowReader:
    """Pass two's access to named rows, opened once: the backed sparse class
    and its ``indptr`` are built a single time rather than per batch (anndata
    re-reads ``indptr`` for every new instance)."""

    def __init__(self, f: h5py.File, cm: CountMatrix):
        self.cm = cm
        item = f[cm.key]
        if cm.format == "dense":
            assert isinstance(item, h5py.Dataset)
            self.dense = item
            self.ds = None
            self.indptr = None
        else:
            assert isinstance(item, h5py.Group)
            self.dense = None
            self.ds = sparse_dataset(item)
            self.indptr = np.asarray(item["indptr"][:], dtype=np.int64)  # pyright: ignore[reportIndexIssue]

    def sizes(self, rows: np.ndarray) -> np.ndarray:
        """Stored entries per named row (dense: every column)."""
        if self.indptr is None:
            return np.full(rows.size, self.cm.n_var, dtype=np.int64)
        return self.indptr[rows + 1] - self.indptr[rows]

    def read(self, rows: np.ndarray) -> sp.csr_matrix:
        """The named rows, ascending, as canonical CSR — the slab comes back in that order."""
        if self.dense is not None:
            return _canonicalize(dense_block_as_csr(self.dense[rows, :]))
        assert self.ds is not None
        slab = self.ds[rows]
        assert isinstance(slab, sp.csr_matrix)
        return _canonicalize(slab)


def _group_duplicates(
    f: h5py.File, cm: CountMatrix, hashes: np.ndarray, stored: np.ndarray, chunk_nnz: int
) -> list[list[int]]:
    """Pass two: exact groups among the rows whose pass-one hash collides.

    Candidates are visited in pass-one hash order, in batches of at most
    ``chunk_nnz`` stored entries sized from their exact row lengths with the
    same bounds the iterator uses. Within a batch each row's canonical
    ``(indices, data)`` bytes is the group key (deviation 4). Because a hash
    bucket is contiguous in that order, every bucket but the one that may
    straddle the batch boundary is complete when the batch ends and is
    emitted and released then — so memory is one batch plus one bucket, not
    one copy of every distinct duplicated row. The key holds indices and data
    as separate members, so two rows group only when both match exactly.
    Groups come back ascending by first member.
    """
    values, counts = np.unique(hashes[stored], return_counts=True)
    colliding = values[counts > 1]
    if colliding.size == 0:
        return []
    candidates = np.flatnonzero(stored & np.isin(hashes, colliding))
    candidates = candidates[np.argsort(hashes[candidates], kind="stable")]  # hash order, rows ascending within

    reader = _RowReader(f, cm)
    offsets = np.concatenate([[0], np.cumsum(reader.sizes(candidates))])
    groups: list[list[int]] = []
    pending: dict[tuple[int, bytes, bytes], list[int]] = defaultdict(list)

    def emit(complete_before: int | None) -> None:
        """Move every bucket whose hash is not ``complete_before`` out of ``pending``."""
        for key in [k for k in pending if k[0] != complete_before]:
            members = pending.pop(key)
            if len(members) > 1:
                groups.append(sorted(members))

    for start, stop in chunk_bounds(offsets, chunk_nnz):
        batch = candidates[start:stop]
        ascending = np.sort(batch)  # the reader wants rows ascending; hash order is restored by key
        m = reader.read(ascending)
        indptr, indices, data = np.asarray(m.indptr), np.asarray(m.indices), np.asarray(m.data)
        for i, row in enumerate(ascending):
            a, b = int(indptr[i]), int(indptr[i + 1])
            pending[(int(hashes[row]), indices[a:b].tobytes(), data[a:b].tobytes())].append(int(row))
        del m, indptr, indices, data
        emit(complete_before=int(hashes[batch[-1]]))  # the last hash may continue into the next batch
    emit(complete_before=None)
    return sorted(groups)


def _check_duplicate_cells_at_path(path: str, chunk_nnz: int) -> dict:
    with h5py.File(path, "r") as f:
        cm = open_count_matrix(f)
        if cm.format == "csc":
            raise Refusal(
                f"{cm.key} is stored csc_matrix, and duplicate rows cannot be read from it in bounded "
                f"memory; re-store the matrix as csr_matrix to check it"
            )
        hashes, stored, non_canonical = _hash_rows(f, cm, chunk_nnz)
        groups = _group_duplicates(f, cm, hashes, stored, chunk_nnz)
    findings = []
    if groups:
        surplus = [row for g in groups for row in g[1:]]
        findings.append(
            finding(
                "duplicate_cells",
                len(surplus),
                cm.obs_ids[surplus],
                cm.key,
                groups=len(groups),
                sample_groups=[[str(v) for v in cm.obs_ids[g[:SAMPLE_ID_LIMIT]]] for g in groups[:SAMPLE_GROUP_LIMIT]],
            )
        )
    return {**cm.envelope(path), "non_canonical_rows": non_canonical, "findings": findings}


@gate_h5ad_paths
def check_duplicate_cells(path: str, chunk_nnz: int = DEFAULT_CHUNK_NNZ) -> dict:
    """Find cells whose raw count rows are identical.

    A port of Lattice's ``evaluate_dup_counts`` (see the module docstring for
    provenance and deviations). Hashes the matrix ``check_raw_counts`` gates —
    ``raw.X`` when present, otherwise ``X`` — once, in bounded chunks, then
    re-reads only the rows whose hash collides and groups those that are
    byte-identical after canonicalization. Read-only.

    Two rows are duplicates only when their sorted column indices and values
    match exactly. Cells with no stored values are never grouped. CSC storage
    is refused by name: a row slab cannot be read from it in bounded memory.

    Args:
        path: Path to an .h5ad file.
        chunk_nnz: Stored entries per chunk; bounds peak memory. Must be >= 1.

    Returns:
        Dict with ``filename``, ``matrix``, ``format``, ``dtype``, ``n_obs``,
        ``n_var``, ``nnz`` (``None`` for dense), ``non_canonical_rows`` (rows
        stored with unsorted or repeated indices — information, not a
        defect), and ``findings``: empty when no two cells share a row, else
        one ``duplicate_cells`` finding with ``count`` (surplus cells: each
        group's size minus one), ``sample_ids`` (those surplus cells, at most
        20), ``groups``, ``sample_groups`` (at most 20 groups of at most 20
        cell IDs each, ascending by first member), and ``matrix``. On
        failure, ``error`` is returned instead.
    """
    return run_count_check(path, chunk_nnz, _check_duplicate_cells_at_path)
