"""Copy a count matrix from another h5ad into a new layer of an HCA-layout target."""

from __future__ import annotations

import re
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import scipy.sparse as sp
from anndata.io import sparse_dataset

from ._errors import Refusal, failure_result, require_positive_int
from ._io import (
    check_duplicate_ids,
    describe_matrix,
    gate_h5ad_paths,
    obs_index_name,
    read_edit_log_h5py,
    read_index,
    require_stamped_group,
    write_edit_log_h5py,
)
from .cap import cellxgene_schema_version
from .cap_pair import same_file_failure
from .dup_counts import _canonicalize
from .guards import is_malformed_name, legacy_layout_problems, require_obs_group
from .qc import (
    DEFAULT_CHUNK_NNZ,
    SAMPLE_ID_LIMIT,
    chunk_bounds,
    dense_block_as_csr,
    iter_matrix_chunks,
    open_matrix,
)
from .write import (
    _compute_sha256,
    build_edit_log,
    cleanup_previous_version,
    generate_output_path,
    make_edit_entry,
    parse_edit_log,
    resolve_latest,
    snapshot_copy_hashed,
)

OPERATION = "copy_matrix_from_file"

_ENSEMBL_ID = re.compile(r"ENS[A-Z]*G\d{11}(\.\d+)?")

# The layer's storage, whatever the target's other matrices use: CELLxGENE
# fixes the encoding (CSR) and the raw dtype (float32) and nothing else, and
# gzip 4 is compress_h5ad's default.
_COMPRESSION = {"compression": "gzip", "compression_opts": 4}
_INT32_LIMIT = 2**31


@dataclass(frozen=True)
class Target:
    """What the copy needs from the target before its snapshot is taken."""

    obs: np.ndarray
    var: np.ndarray
    raw_log: str


@dataclass(frozen=True)
class Alignment:
    """The target row of each source row (-1 where it is not copied), and the source column of each target gene."""

    rows: np.ndarray
    columns: np.ndarray
    n_source_genes: int
    target_obs: np.ndarray
    target_var: np.ndarray

    def cell(self, target_row: int) -> str:
        return str(self.target_obs[target_row])

    def gene(self, target_col: int) -> str:
        return str(self.target_var[target_col])


@dataclass(frozen=True)
class RemappedRows:
    """One source block's target rows, in source order, as canonical CSR over the target's genes."""

    target_rows: np.ndarray
    matrix: sp.csr_matrix


@dataclass(frozen=True)
class Scratch:
    """The copied rows, uncompressed on disk in source order, and where each target row sits in them.

    ``indptr`` is the layer's, in target order; ``offsets`` is each target
    row's first entry in the scratch files. ``digests`` is each target
    row's :func:`row_digests`, taken from the source block rather than the
    scratch files, so a misplaced row cannot agree with it.
    """

    indices_path: Path
    data_path: Path
    offsets: np.ndarray
    indptr: np.ndarray
    digests: np.ndarray
    n_var: int

    @property
    def nnz(self) -> int:
        return int(self.indptr[-1])

    def rows(self, start: int, stop: int) -> sp.csr_matrix:
        """Target rows ``start:stop`` as canonical CSR with float32 values."""
        indptr = self.indptr[start : stop + 1] - self.indptr[start]
        total = int(indptr[-1])
        shape = (stop - start, self.n_var)
        if total == 0:
            return sp.csr_matrix(shape, dtype=np.float32)
        positions = np.arange(total)
        positions += np.repeat(self.offsets[start:stop] - indptr[:-1], np.diff(indptr))
        indices = np.memmap(self.indices_path, dtype=np.int32, mode="r")[positions]
        data = np.memmap(self.data_path, dtype=np.float32, mode="r")[positions]
        return sp.csr_matrix((data, indices, indptr), shape=shape)


def parse_source_matrix(source_matrix: str) -> str:
    """The HDF5 key of ``"X"``, ``"raw.X"`` or ``"layers/<name>"``.

    Raises:
        Refusal: Any other spelling.
    """
    if source_matrix == "X":
        return "X"
    if source_matrix == "raw.X":
        return "raw/X"
    prefix, _, name = source_matrix.partition("/")
    if prefix == "layers" and not is_malformed_name(name):
        return source_matrix
    raise Refusal(f"source_matrix must be 'X', 'raw.X' or 'layers/<name>', got {source_matrix!r}")


def _listing(ids: np.ndarray) -> str:
    shown = [str(i) for i in ids[:SAMPLE_ID_LIMIT]]
    more = f" (+{len(ids) - SAMPLE_ID_LIMIT} more)" if len(ids) > SAMPLE_ID_LIMIT else ""
    return f"{shown}{more}"


def _index(group: h5py.Group | h5py.Dataset | h5py.Datatype, label: str) -> np.ndarray:
    return read_index(group, obs_index_name(group), label)


def _entry_row(indptr: np.ndarray, entry: int) -> int:
    """The row holding stored entry ``entry`` of a CSR matrix."""
    return int(np.searchsorted(indptr, entry, side="right")) - 1


def read_target(f: h5py.File, layer: str) -> Target:
    """The target's cells, genes and edit log, refusing a target the layer cannot go into.

    Raises:
        Refusal: The target is CellxGENE or legacy CAP layout, already has the layer, or has
            a ``raw.X`` that cannot be checked against (CSC, or a ``raw.var``
            that is absent or differs from ``var``, or the wrong shape).
    """
    if version := cellxgene_schema_version(f):
        raise Refusal(
            f"Refusing to copy: the target declares CellxGENE schema {version}; this tool writes HCA-layout files only"
        )
    uns = f.get("uns")
    if legacy := legacy_layout_problems(uns if isinstance(uns, h5py.Group) else None):
        raise Refusal(f"Refusing to copy: {legacy[0]}")
    layers = f.get("layers")
    if isinstance(layers, h5py.Group) and layer in layers:
        raise Refusal(f"Refusing to copy: the target already has layers['{layer}']")
    obs = _index(require_obs_group(f), "target cells")
    var = _index(f["var"], "target genes")
    if "raw/X" in f:
        if "raw/var" not in f:
            raise Refusal("The target has raw.X but no raw.var, so the copy cannot be checked against it")
        fmt, shape, _ = describe_matrix(f["raw/X"], "raw/X")
        if fmt == "csc":
            raise Refusal("The target's raw.X is csc_matrix, which cannot be read by row to check the copy against")
        if not np.array_equal(_index(f["raw/var"], "target raw genes"), var) or shape != (len(obs), len(var)):
            raise Refusal(
                "The target's raw.X does not have the target's cells and genes, so the copy cannot be checked"
            )
    return Target(obs, var, read_edit_log_h5py(f))


def read_source_ids(f: h5py.File, key: str, source_matrix: str) -> tuple[np.ndarray, np.ndarray]:
    """The source matrix's cell and gene IDs.

    Raises:
        Refusal: The source has no such matrix, it is CSC, or its obs or var
            is absent or does not match its shape.
    """
    if key not in f:
        raise Refusal(f"The source has no {source_matrix}")
    matrix = open_matrix(f, key)
    if matrix.format == "csc":
        raise Refusal(
            f"The source's {source_matrix} is csc_matrix, which cannot be read cell by cell in bounded memory"
        )
    return matrix.obs_ids, matrix.read_var_ids(f)


def align(source_obs: np.ndarray, source_var: np.ndarray, target_obs: np.ndarray, target_var: np.ndarray) -> Alignment:
    """Map each source cell and gene to its target position by ID.

    Raises:
        Refusal: A duplicate ID in either file, a source var index with no
            Ensembl IDs, or a target cell or gene the source lacks.
    """
    source_cells, target_cells = pd.Index(source_obs), pd.Index(target_obs)
    source_genes, target_genes = pd.Index(source_var), pd.Index(target_var)
    for ids, label in (
        (source_cells, "Source cells"),
        (target_cells, "Target cells"),
        (source_genes, "Source genes"),
        (target_genes, "Target genes"),
    ):
        if failure := check_duplicate_ids(ids, label):
            raise Refusal(failure)
    if not source_genes.astype(str).str.fullmatch(_ENSEMBL_ID).any():
        raise Refusal(
            f"The source's var index must hold Ensembl IDs, and it holds none (first entries: "
            f"{[str(g) for g in source_var[:5]]}); re-export the source with Ensembl IDs as its var index"
        )
    cell_pos = source_cells.get_indexer(target_cells)
    if (missing := cell_pos < 0).any():
        raise Refusal(
            f"{int(missing.sum())} of {len(target_obs)} target cells are not in the source: "
            f"{_listing(target_obs[missing])}"
        )
    gene_pos = source_genes.get_indexer(target_genes)
    if (missing := gene_pos < 0).any():
        raise Refusal(
            f"{int(missing.sum())} of {len(target_var)} target genes are not in the source: "
            f"{_listing(target_var[missing])}"
        )
    rows = np.full(len(source_obs), -1, dtype=np.int64)
    rows[cell_pos] = np.arange(len(target_obs))
    return Alignment(rows, gene_pos, len(source_var), target_obs, target_var)


def first_repeated_entry(m: sp.csr_matrix) -> int | None:
    """The first stored entry whose column repeats the previous entry's in the same row; ``m`` has sorted indices."""
    if m.nnz < 2:
        return None
    repeats = np.diff(m.indices) == 0
    starts = m.indptr[1:-1]
    repeats[starts[(starts > 0) & (starts < m.nnz)] - 1] = False
    hits = np.flatnonzero(repeats)
    return int(hits[0]) + 1 if hits.size else None


def refuse_stored_twice(m: sp.csr_matrix, cell: Callable[[int], str], gene: Callable[[int], str], what: str) -> None:
    """Refuse a CSR block that stores one gene twice in a cell's row; ``m`` has sorted indices.

    Raises:
        Refusal: Naming the cell and gene; ``cell`` maps a row of ``m`` to its ID.
    """
    if (i := first_repeated_entry(m)) is not None:
        raise Refusal(
            f"Refusing to copy: {what} stores gene {gene(int(m.indices[i]))} twice for cell "
            f"{cell(_entry_row(m.indptr, i))}; a count matrix stores each gene once per cell"
        )


def remap_block(block: sp.csr_matrix, start: int, alignment: Alignment, source_matrix: str) -> RemappedRows:
    """The target cells in source rows ``start:start+n``, keeping target genes and non-zeros only.

    Raises:
        Refusal: A kept cell's row stores a kept gene twice.
    """
    target_rows = alignment.rows[start : start + len(block.indptr) - 1]
    keep = np.flatnonzero(target_rows >= 0)
    kept = sp.csr_matrix(block[keep][:, alignment.columns])  # pyright: ignore[reportOptionalSubscript]
    kept.sort_indices()
    refuse_stored_twice(
        kept, lambda row: alignment.cell(target_rows[keep][row]), alignment.gene, f"the source's {source_matrix}"
    )
    kept.eliminate_zeros()
    return RemappedRows(target_rows[keep], kept)


def _bad_value_masks(values: np.ndarray) -> Iterator[tuple[str, np.ndarray]]:
    is_float = values.dtype.kind == "f"
    if is_float:
        yield "a non-finite value", ~np.isfinite(values)
    yield "a negative value", values < 0
    if is_float:
        yield "a fractional value", values != np.floor(values)
    if not np.can_cast(values.dtype, np.float32, "safe"):
        yield "a value float32 cannot hold exactly", values.astype(np.float32).astype(values.dtype) != values


def first_bad_value(values: np.ndarray) -> tuple[str, int] | None:
    """The first value that is not a whole, non-negative count float32 holds exactly, and why."""
    for reason, bad in _bad_value_masks(values):
        if bad.any():
            return reason, int(np.argmax(bad))
    return None


def _refuse_bad_values(rows: RemappedRows, alignment: Alignment, source_matrix: str) -> None:
    m = rows.matrix
    if (bad := first_bad_value(m.data)) is None:
        return
    reason, i = bad
    row = rows.target_rows[_entry_row(m.indptr, i)]
    raise Refusal(
        f"Refusing to copy: the source's {source_matrix} holds {reason} ({m.data[i]}) "
        f"at cell {alignment.cell(row)}, gene {alignment.gene(m.indices[i])}"
    )


def row_offsets(written: int, indptr: np.ndarray) -> np.ndarray:
    """Where each row of a block starts in the scratch files, after ``written`` entries, as int64."""
    # scipy keeps indptr int32, and int32 + a Python int stays int32, wrapping past 2^31.
    return written + indptr[:-1].astype(np.int64)


def _splitmix64(x: np.ndarray) -> np.ndarray:
    x = x + np.uint64(0x9E3779B97F4A7C15)
    x = (x ^ (x >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    x = (x ^ (x >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    return x ^ (x >> np.uint64(31))


def row_digests(m: sp.csr_matrix) -> np.ndarray:
    """Each row's 64-bit digest of its (gene, float32 value) entries; rows with the same entries share one."""
    keys = (m.indices.astype(np.uint64) << np.uint64(32)) | m.data.astype(np.float32).view(np.uint32).astype(np.uint64)
    # Summing per-entry hashes, wrapping at 2^64, makes the digest one vectorized cumsum.
    cumulative = np.concatenate(([np.uint64(0)], np.cumsum(_splitmix64(keys), dtype=np.uint64)))
    return cumulative[m.indptr[1:]] - cumulative[m.indptr[:-1]]


def collect_rows(
    f: h5py.File, key: str, source_matrix: str, alignment: Alignment, chunk_nnz: int, scratch_dir: Path
) -> Scratch:
    """Stream the source once, writing the target's rows to uncompressed scratch files.

    Raises:
        Refusal: A copied value is not a whole, non-negative count that
            float32 holds exactly, or a copied row stores a gene twice.
    """
    n_target = len(alignment.target_obs)
    offsets = np.zeros(n_target, dtype=np.int64)
    lengths = np.zeros(n_target, dtype=np.int64)
    digests = np.zeros(n_target, dtype=np.uint64)
    indices_path, data_path = scratch_dir / "indices.i32", scratch_dir / "data.f32"
    written = 0
    with indices_path.open("wb") as indices_out, data_path.open("wb") as data_out:
        for chunk in iter_matrix_chunks(f, key, chunk_nnz):
            rows = remap_block(chunk.matrix, chunk.start, alignment, source_matrix)  # pyright: ignore[reportArgumentType]
            _refuse_bad_values(rows, alignment, source_matrix)
            m = rows.matrix
            offsets[rows.target_rows] = row_offsets(written, m.indptr)
            lengths[rows.target_rows] = np.diff(m.indptr)
            digests[rows.target_rows] = row_digests(m)
            m.indices.astype(np.int32, copy=False).tofile(indices_out)
            m.data.astype(np.float32, copy=False).tofile(data_out)
            written += m.nnz
    indptr = np.concatenate(([0], np.cumsum(lengths)))
    return Scratch(indices_path, data_path, offsets, indptr, digests, len(alignment.target_var))


def stage_source(
    source_path: str, key: str, source_matrix: str, target: Target, chunk_nnz: int, scratch_dir: Path
) -> tuple[Alignment, Scratch]:
    """Align the source to the target and stage the target's rows in ``scratch_dir``.

    Raises:
        Refusal: From :func:`read_source_ids`, :func:`align` and :func:`collect_rows`.
    """
    with h5py.File(source_path, "r") as f:
        alignment = align(*read_source_ids(f, key, source_matrix), target.obs, target.var)
        return alignment, collect_rows(f, key, source_matrix, alignment, chunk_nnz, scratch_dir)


def raw_problem(layer: sp.csr_matrix, raw: sp.csr_matrix) -> tuple[str, int, int] | None:
    """The first layer entry, row-major, above ``raw`` or non-zero where it is zero: why, its row and its column."""
    bad = _canonicalize(sp.csr_matrix(layer > raw))
    if bad.nnz == 0:
        return None
    row = _entry_row(bad.indptr, 0)
    col = int(bad.indices[0])
    raw_value = raw[row, col]
    return ("where raw.X is zero" if raw_value == 0 else f"above raw.X ({raw_value})"), row, col


def _sorted_raw(raw: sp.csr_matrix, start: int, alignment: Alignment) -> sp.csr_matrix:
    raw.sort_indices()
    refuse_stored_twice(raw, lambda row: alignment.cell(start + row), alignment.gene, "the target's raw.X")
    return raw


def _raw_indptr(raw: h5py.Group | h5py.Dataset) -> np.ndarray:
    """Entries stored before each row of ``raw.X``, as int64; a dense matrix stores every gene."""
    if isinstance(raw, h5py.Dataset):
        return np.arange(raw.shape[0] + 1, dtype=np.int64) * raw.shape[1]
    indptr = raw["indptr"]
    assert isinstance(indptr, h5py.Dataset)
    return np.asarray(indptr[:], dtype=np.int64)


def _raw_block_reader(raw: h5py.Group | h5py.Dataset) -> Callable[[int, int], sp.csr_matrix]:
    if isinstance(raw, h5py.Dataset):
        return lambda start, stop: dense_block_as_csr(raw[start:stop])
    backed = sparse_dataset(raw)
    return lambda start, stop: backed[start:stop]  # pyright: ignore[reportReturnType]


def check_against_raw(target_path: str, scratch: Scratch, alignment: Alignment, chunk_nnz: int) -> None:
    """Check the staged rows against the target's ``raw.X``, before any snapshot is taken; a target without one passes.

    Raises:
        Refusal: A copied value is above ``raw.X`` or non-zero where it is
            zero, or ``raw.X`` stores a gene twice in a cell.
    """
    with h5py.File(target_path, "r") as f:
        raw = f.get("raw/X")
        if raw is None:
            return
        read_raw = _raw_block_reader(raw)  # pyright: ignore[reportArgumentType]
        for start, stop in chunk_bounds(scratch.indptr + _raw_indptr(raw), chunk_nnz):  # pyright: ignore[reportArgumentType]
            block = scratch.rows(start, stop)
            if problem := raw_problem(block, _sorted_raw(read_raw(start, stop), start, alignment)):
                reason, row, col = problem
                raise Refusal(
                    f"Refusing to copy: the value {block[row, col]} at cell {alignment.cell(start + row)}, "
                    f"gene {alignment.gene(col)} is {reason}"
                )


def write_layer(f_out: h5py.File, layer: str, scratch: Scratch, chunk_nnz: int) -> None:
    """Write the scratch rows as ``layers/<layer>``.

    Raw h5py rather than anndata's writer: the layer is streamed block by
    block into datasets sized up front, which ``write_elem`` cannot do.
    """
    nnz, indptr = scratch.nnz, scratch.indptr
    index_dtype = np.int32 if max(nnz, scratch.n_var) < _INT32_LIMIT else np.int64
    group = require_stamped_group(f_out, "layers").create_group(layer)
    group.attrs["encoding-type"] = "csr_matrix"
    group.attrs["encoding-version"] = "0.1.0"
    group.attrs["shape"] = (len(indptr) - 1, scratch.n_var)
    data = group.create_dataset("data", shape=(nnz,), dtype=np.float32, **_COMPRESSION)
    indices = group.create_dataset("indices", shape=(nnz,), dtype=index_dtype, **_COMPRESSION)
    for start, stop in chunk_bounds(indptr, chunk_nnz):
        block = scratch.rows(start, stop)
        data[indptr[start] : indptr[stop]] = block.data
        indices[indptr[start] : indptr[stop]] = block.indices
    group.create_dataset("indptr", data=indptr.astype(index_dtype), **_COMPRESSION)


def readback_problem(path: str, layer: str, scratch: Scratch, alignment: Alignment, chunk_nnz: int) -> str | None:
    """Why the written layer differs from the scratch rows or from the source's digests, or None."""
    with h5py.File(path, "r") as f:
        written = sparse_dataset(f[f"layers/{layer}"])  # pyright: ignore[reportArgumentType]
        if written.format != "csr" or written.shape != (len(scratch.indptr) - 1, scratch.n_var):
            return (
                f"The readback of layers['{layer}'] is {written.format} {written.shape}, not the target's shape as CSR"
            )
        indptr = f[f"layers/{layer}/indptr"]
        assert isinstance(indptr, h5py.Dataset)
        if not np.array_equal(indptr[:], scratch.indptr):
            return f"The readback of layers['{layer}'] stores a different number of values per cell than were copied"
        for start, stop in chunk_bounds(scratch.indptr, chunk_nnz):
            got, want = written[start:stop], scratch.rows(start, stop)
            differs = (got.indices != want.indices) | (got.data != want.data)  # pyright: ignore[reportAttributeAccessIssue]
            if differs.any():
                row = start + _entry_row(want.indptr, int(np.argmax(differs)))
                return f"The readback of layers['{layer}'] differs from the copied values at cell {alignment.cell(row)}"
            if (mismatch := row_digests(got) != scratch.digests[start:stop]).any():  # pyright: ignore[reportArgumentType]
                row = start + int(np.argmax(mismatch))
                return f"The readback of layers['{layer}'] does not match the source at cell {alignment.cell(row)}"
    return None


def write_snapshot(
    target_path: str, target: Target, layer: str, scratch: Scratch, alignment: Alignment, details: dict, chunk_nnz: int
) -> str:
    """Write the layer and its edit-log entry into a new snapshot of the target, read it back, and return its path.

    Raises:
        Refusal: The readback differs; the snapshot is removed.
    """
    with snapshot_copy_hashed(target_path) as (output_path, target_sha256):
        with h5py.File(output_path, "a") as f_out:
            write_layer(f_out, layer, scratch, chunk_nnz)
            entry = make_edit_entry(
                operation=OPERATION,
                description=f"Copied {details['source_matrix']} of {details['source_file']} into layers['{layer}']",
                details=details,
            )
            log = build_edit_log(target.raw_log, [entry], target_path, target_sha256)
            if "error" in log:
                raise RuntimeError(log["error"])
            write_edit_log_h5py(f_out, log["json"])
        if problem := readback_problem(output_path, layer, scratch, alignment, chunk_nnz):
            raise Refusal(f"{problem}; the snapshot was discarded")
    return output_path


@gate_h5ad_paths
def copy_matrix_from_file(
    source_path: str,
    source_matrix: str,
    target_path: str,
    layer: str,
    chunk_nnz: int = DEFAULT_CHUNK_NNZ,
) -> dict:
    """Copy a count matrix from a source h5ad into a new layer of an HCA-layout target.

    The target's obs index and var index decide the layer's cells and genes
    and their order: cells are matched by ID and genes by exact Ensembl ID,
    and source cells and genes the target lacks are ignored. Every copied
    value must be a whole, non-negative count that float32 holds exactly
    and, when the target has ``raw.X``, no greater than it and zero where it
    is zero. The layer is written as float32 CSR, gzip 4, in a new snapshot,
    then read back and compared with what was copied.

    Args:
        source_path: The h5ad to copy from. Its var index must hold Ensembl IDs.
        source_matrix: ``"X"``, ``"raw.X"`` or ``"layers/<name>"`` in the source.
        target_path: The HCA-layout h5ad to add the layer to.
        layer: The name of the new layer, such as ``"desouped_counts"``.
        chunk_nnz: Stored entries read per block, which bounds memory.

    Returns:
        ``output_path``, ``layer``, ``n_obs``, ``n_var``, ``nnz`` and the
        counts of source cells and genes not copied; or ``error`` when
        refused, with nothing written.
    """
    try:
        require_positive_int("chunk_nnz", chunk_nnz)
        key = parse_source_matrix(source_matrix)
        if is_malformed_name(layer):
            raise Refusal(f"layer must be a name without '/', got {layer!r}")
        source_path, target_path = resolve_latest(source_path), resolve_latest(target_path)
        for path in (source_path, target_path):
            if not Path(path).is_file():
                raise Refusal(f"File not found: {path}")
        if failure := same_file_failure(source_path, target_path):
            raise Refusal(failure)
        # The snapshot names its output only after the source is staged; refuse an orphaned snapshot first.
        generate_output_path(target_path)
        with h5py.File(target_path, "r") as f:
            target = read_target(f, layer)
        if "error" in (parsed := parse_edit_log(target.raw_log)):
            return parsed

        with tempfile.TemporaryDirectory(dir=Path(target_path).parent, prefix=".copy-matrix-") as tmp:
            alignment, scratch = stage_source(source_path, key, source_matrix, target, chunk_nnz, Path(tmp))
            check_against_raw(target_path, scratch, alignment, chunk_nnz)
            details = {
                "source_file": Path(source_path).name,
                "source_sha256": _compute_sha256(source_path),
                "source_matrix": source_matrix,
                "layer": layer,
                "n_obs": len(target.obs),
                "n_var": len(target.var),
                "nnz": scratch.nnz,
            }
            output_path = write_snapshot(target_path, target, layer, scratch, alignment, details, chunk_nnz)

        cleanup_previous_version(target_path, output_path)
        return {
            "output_path": output_path,
            "layer": layer,
            "n_obs": len(target.obs),
            "n_var": len(target.var),
            "nnz": scratch.nnz,
            "source_cells_not_copied": len(alignment.rows) - len(target.obs),
            "source_genes_not_copied": alignment.n_source_genes - len(target.var),
        }
    except Exception as e:
        # snapshot_copy_hashed removes the snapshot itself on any raise.
        return failure_result(e)
