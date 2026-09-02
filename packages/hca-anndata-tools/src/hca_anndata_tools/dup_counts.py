"""Duplicated cells by raw count content hash (#677).

A port of ``evaluate_dup_counts`` from Lattice Data Coordination's
lattice-tools, ``cellxgene_resources/cellxgene_mods.py`` at commit
``8778a14f2a5a7039acf3ce74b3da220c24521905``:
https://github.com/Lattice-Data/lattice-tools/blob/8778a14f2a5a7039acf3ce74b3da220c24521905/cellxgene_resources/cellxgene_mods.py

    MIT License — Copyright (c) 2020 Lattice Data Coordination.
    Permission is hereby granted, free of charge, to any person obtaining a
    copy of this software and associated documentation files, to deal in the
    Software without restriction, subject to the condition that the above
    copyright notice and this permission notice be included in all copies or
    substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS",
    WITHOUT WARRANTY OF ANY KIND.

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
   CSC is refused by name (the iterator's ``axis="row"`` contract).

Pass two is bounded by the colliding rows, not the matrix. On real data those
are the duplicates themselves. A pathological file whose every row collides
on hash but differs in content would hold most of the matrix in memory while
grouping; that limit is accepted rather than engineered around.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path

import h5py
import numpy as np
import scipy.sparse as sp
from anndata.io import sparse_dataset

from ._errors import failure_result
from ._io import gate_h5ad_paths
from .qc import DEFAULT_CHUNK_NNZ, SAMPLE_ID_LIMIT, CountMatrix, iter_matrix_chunks, open_count_matrix
from .write import resolve_latest

# Groups reported per finding; each group lists at most SAMPLE_ID_LIMIT IDs.
SAMPLE_GROUP_LIMIT = 20

# Pass-one hash of a row with no stored values. Never grouped (deviation 3).
_EMPTY_ROW = np.int64(-1)


def _row_hash(values: np.ndarray) -> np.int64:
    """A stable 64-bit hash of a row's canonical values (deviation 4)."""
    return np.int64(int.from_bytes(hashlib.blake2b(values.tobytes(), digest_size=8).digest(), "little", signed=True))


def _non_canonical_rows(m: sp.csr_matrix) -> int:
    """Rows whose stored indices are unsorted or repeated, before canonicalizing.

    A row is canonical when its indices strictly increase. ``np.diff`` over the
    whole ``indices`` array with the row boundaries masked out finds every
    violation in one pass; the violating positions map back to rows through
    ``indptr``.
    """
    indices = np.asarray(m.indices)
    indptr = np.asarray(m.indptr)
    if indices.size < 2:
        return 0
    bad = np.flatnonzero(np.diff(indices) <= 0) + 1  # position of the offending entry
    # Positions at a row start compare against the previous row: not a violation.
    bad = bad[~np.isin(bad, indptr[1:-1])]
    if bad.size == 0:
        return 0
    rows = np.searchsorted(indptr, bad, side="right") - 1
    return int(np.unique(rows).size)


def _canonicalize(m: sp.csr_matrix) -> sp.csr_matrix:
    """The original's canonical step, on a chunk we own (deviation 2)."""
    m.sort_indices()
    m.sum_duplicates()
    m.eliminate_zeros()
    return m


def _hash_rows(f: h5py.File, cm: CountMatrix, chunk_nnz: int) -> tuple[np.ndarray, int]:
    """Pass one: a hash per row of the canonical values, and the non-canonical row count."""
    hashes = np.full(cm.n_obs, _EMPTY_ROW, dtype=np.int64)
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
        del m, data, indptr
    return hashes, non_canonical


def _read_rows(f: h5py.File, cm: CountMatrix, rows: np.ndarray) -> sp.csr_matrix:
    """The named rows, as canonical CSR, read through the same paths as pass one."""
    item = f[cm.key]
    if cm.format == "dense":
        assert isinstance(item, h5py.Dataset)
        block = item[np.sort(rows), :]  # h5py wants a sorted selection
        if block.dtype == np.float16:
            block = block.astype(np.float32)
        return _canonicalize(sp.csr_matrix(block))
    assert isinstance(item, h5py.Group)
    slab = sparse_dataset(item)[np.sort(rows)]
    assert isinstance(slab, sp.csr_matrix)
    return _canonicalize(slab)


def _group_duplicates(f: h5py.File, cm: CountMatrix, hashes: np.ndarray, chunk_nnz: int) -> list[np.ndarray]:
    """Pass two: exact groups among the rows whose pass-one hash collides.

    Candidates are read back in batches bounded by ``chunk_nnz`` stored
    entries (their sizes are known from pass one's walk only in aggregate, so
    the batch is sized by row count against the mean row). Each row's
    canonical ``(indices, data)`` bytes is the group key (deviation 4).
    """
    stored = hashes[hashes != _EMPTY_ROW]
    values, counts = np.unique(stored, return_counts=True)
    colliding = values[counts > 1]
    if colliding.size == 0:
        return []
    candidates = np.flatnonzero(np.isin(hashes, colliding))

    groups: dict[bytes, list[int]] = defaultdict(list)
    mean_row = max(1, (cm.nnz or cm.n_obs * cm.n_var) // max(cm.n_obs, 1))
    batch_rows = max(1, chunk_nnz // mean_row)
    for start in range(0, candidates.size, batch_rows):
        rows = np.sort(candidates[start : start + batch_rows])
        m = _read_rows(f, cm, rows)
        indptr, indices, data = np.asarray(m.indptr), np.asarray(m.indices), np.asarray(m.data)
        for i, row in enumerate(rows):
            a, b = int(indptr[i]), int(indptr[i + 1])
            groups[indices[a:b].tobytes() + data[a:b].tobytes()].append(int(row))
        del m, indptr, indices, data
    return [np.asarray(sorted(rows)) for rows in groups.values() if len(rows) > 1]


def _check_duplicate_cells_at_path(path: str, chunk_nnz: int) -> dict:
    with h5py.File(path, "r") as f:
        cm = open_count_matrix(f)
        findings = []
        non_canonical = 0
        if cm.n_obs and cm.n_var:
            hashes, non_canonical = _hash_rows(f, cm, chunk_nnz)
            groups = sorted(_group_duplicates(f, cm, hashes, chunk_nnz), key=lambda g: int(g[0]))
            if groups:
                findings.append(
                    {
                        "code": "duplicate_cells",
                        "count": int(sum(len(g) - 1 for g in groups)),
                        "groups": len(groups),
                        "sample_groups": [
                            [str(v) for v in cm.obs_ids[g][:SAMPLE_ID_LIMIT]] for g in groups[:SAMPLE_GROUP_LIMIT]
                        ],
                        "matrix": cm.key,
                    }
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
        group's size minus one), ``groups``, ``sample_groups`` (at most 20
        groups of at most 20 cell IDs each, in row order), and ``matrix``.
        On failure, ``error`` is returned instead.
    """
    try:
        if not isinstance(chunk_nnz, int) or chunk_nnz < 1:
            return {"error": f"chunk_nnz must be a positive int, got {chunk_nnz!r}"}
        path = resolve_latest(path)
        if not Path(path).is_file():
            return {"error": f"File not found: {path}"}
        return _check_duplicate_cells_at_path(path, chunk_nnz)
    except Exception as e:
        return failure_result(e)
