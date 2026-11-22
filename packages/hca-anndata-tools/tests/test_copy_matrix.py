"""Tests for copy_matrix_from_file."""

import json
from pathlib import Path

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp
from anndata.io import write_elem

from hca_anndata_tools import copy_matrix
from hca_anndata_tools.copy_matrix import (
    copy_matrix_from_file,
    first_bad_value,
    first_repeated_entry,
    parse_source_matrix,
    raw_problem,
    row_digests,
    row_offsets,
)

N_SOURCE_CELLS = 30
GENES = [f"ENSG{i:011d}" for i in range(12)]
NON_ENSEMBL = ["antibody_CD3", "antibody_CD4"]


def _counts(rng, n_obs, n_var, density=0.4) -> np.ndarray:
    return (rng.integers(1, 20, size=(n_obs, n_var)) * (rng.random((n_obs, n_var)) < density)).astype(np.float32)


def _write(path: Path, x, obs_ids, var_ids, *, raw_x=None, layers=None, uns=None) -> Path:
    obs = pd.DataFrame(index=pd.Index(obs_ids))
    var = pd.DataFrame(index=pd.Index(var_ids))
    adata = ad.AnnData(X=x, obs=obs, var=var, layers=layers, uns=uns)
    if raw_x is not None:
        adata.raw = ad.AnnData(X=raw_x, obs=obs, var=var)
    adata.write_h5ad(path)
    return path


@pytest.fixture
def pair(tmp_path):
    """A source with every cell and extra genes, and a target holding a shuffled subset of both.

    Returns ``(source_path, target_path, expected)`` where ``expected`` is the
    source counts as a DataFrame over the target's cells and genes.
    """
    rng = np.random.default_rng(3)
    source_obs = [f"cell-{i}" for i in range(N_SOURCE_CELLS)]
    source_var = GENES + NON_ENSEMBL
    counts = _counts(rng, N_SOURCE_CELLS, len(source_var))
    source = _write(tmp_path / "all-cells.h5ad", sp.csr_matrix(counts), source_obs, source_var)

    target_obs = list(rng.permutation(source_obs)[:20])
    target_var = list(rng.permutation(GENES)[:10])
    expected = pd.DataFrame(counts, index=source_obs, columns=source_var).loc[target_obs, target_var]
    raw = expected.to_numpy() + _counts(rng, 20, 10) + (expected.to_numpy() > 0)
    target = _write(
        tmp_path / "target.h5ad",
        sp.csr_matrix(np.log1p(raw)),
        target_obs,
        target_var,
        raw_x=sp.csr_matrix(raw),
    )
    return source, target, expected


def _copy(source, target, source_matrix="X", layer="desouped_counts", chunk_nnz=7):
    return copy_matrix_from_file(str(source), source_matrix, str(target), layer, chunk_nnz=chunk_nnz)


def _no_scratch(path) -> bool:
    return not any(p.name.startswith(".copy-matrix-") for p in Path(path).parent.iterdir())


def _set_value(path: Path, key: str, row: int, col: int, value: float) -> None:
    adata = ad.read_h5ad(path)
    m = (adata.raw.X if key == "raw" else adata.X).toarray()  # pyright: ignore[reportOptionalMemberAccess, reportAttributeAccessIssue]
    m[row, col] = value
    if key == "raw":
        adata.raw = ad.AnnData(X=sp.csr_matrix(m), obs=adata.obs, var=adata.var)
    else:
        adata.X = sp.csr_matrix(m)
    adata.write_h5ad(path)


# --- copying ------------------------------------------------------------------


def test_copies_target_cells_and_genes_in_target_order(pair):
    source, target, expected = pair

    result = _copy(source, target)

    assert "error" not in result, result
    out = ad.read_h5ad(result["output_path"])
    layer = out.layers["desouped_counts"]
    assert isinstance(layer, sp.csr_matrix)
    assert layer.dtype == np.float32
    assert layer.has_sorted_indices
    assert list(out.obs_names) == list(expected.index)
    assert list(out.var_names) == list(expected.columns)
    np.testing.assert_array_equal(layer.toarray(), expected.to_numpy())
    assert (result["n_obs"], result["n_var"], result["nnz"]) == (20, 10, int((expected.to_numpy() != 0).sum()))
    assert (result["source_cells_not_copied"], result["source_genes_not_copied"]) == (10, 4)
    assert _no_scratch(target)


def test_layer_storage_profile(pair):
    source, target, _ = pair

    result = _copy(source, target)

    with h5py.File(result["output_path"], "r") as f:
        group = f["layers/desouped_counts"]
        assert group.attrs["encoding-type"] == "csr_matrix"
        assert f["layers"].attrs["encoding-type"] == "dict"
        for name in ("data", "indices", "indptr"):
            assert (group[name].compression, group[name].compression_opts) == ("gzip", 4)
        assert group["indices"].dtype == np.int32
        assert group["indptr"].dtype == np.int32


def test_edit_log_entry(pair):
    source, target, _ = pair

    result = _copy(source, target)

    log = json.loads(ad.read_h5ad(result["output_path"]).uns["provenance"]["edit_history"])
    entry = log[-1]
    assert entry["operation"] == "copy_matrix_from_file"
    details = entry["details"]
    assert details["source_file"] == "all-cells.h5ad"
    assert len(details["source_sha256"]) == 64
    assert (details["source_matrix"], details["layer"]) == ("X", "desouped_counts")
    assert (details["n_obs"], details["n_var"], details["nnz"]) == (result["n_obs"], result["n_var"], result["nnz"])


@pytest.mark.parametrize("fmt", ["dense", "int32"])
def test_source_dense_or_integer(pair, fmt):
    source, target, expected = pair
    adata = ad.read_h5ad(source)
    adata.X = adata.X.toarray() if fmt == "dense" else adata.X.astype(np.int32)  # pyright: ignore[reportOptionalMemberAccess, reportAttributeAccessIssue]
    adata.write_h5ad(source)

    result = _copy(source, target)

    assert "error" not in result, result
    np.testing.assert_array_equal(ad.read_h5ad(result["output_path"]).layers["desouped_counts"].toarray(), expected)  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.parametrize("source_matrix", ["raw.X", "layers/counts"])
def test_source_raw_or_layer(tmp_path, pair, source_matrix):
    source, target, expected = pair
    adata = ad.read_h5ad(source)
    moved = _write(
        tmp_path / "moved.h5ad",
        sp.csr_matrix(adata.X.shape, dtype=np.float32),  # pyright: ignore[reportOptionalMemberAccess]
        adata.obs_names,
        adata.var_names,
        raw_x=adata.X if source_matrix == "raw.X" else None,
        layers={"counts": adata.X} if source_matrix == "layers/counts" else None,
    )

    result = _copy(moved, target, source_matrix=source_matrix)

    assert "error" not in result, result
    np.testing.assert_array_equal(ad.read_h5ad(result["output_path"]).layers["desouped_counts"].toarray(), expected)  # pyright: ignore[reportAttributeAccessIssue]


def test_target_without_raw(tmp_path, pair):
    source, _, expected = pair
    target = _write(tmp_path / "no-raw.h5ad", sp.csr_matrix(expected.to_numpy()), expected.index, expected.columns)

    result = _copy(source, target)

    assert "error" not in result, result


# --- refusals before writing ----------------------------------------------------


def test_refuses_source_without_ensembl_ids(tmp_path, pair, no_snapshot):
    _, target, _ = pair
    symbols = _write(
        tmp_path / "symbols.h5ad",
        sp.csr_matrix((30, 3), dtype=np.float32),
        [f"c{i}" for i in range(30)],
        ["A", "B", "C"],
    )

    result = _copy(symbols, target)

    assert "must hold Ensembl IDs" in result["error"]
    assert no_snapshot(target)
    assert _no_scratch(target)


def test_refuses_missing_target_cell(tmp_path, pair, no_snapshot):
    source, _, expected = pair
    target = _write(
        tmp_path / "extra-cell.h5ad",
        sp.csr_matrix(np.ones((2, 10), dtype=np.float32)),
        [expected.index[0], "cell-elsewhere"],
        expected.columns,
    )

    result = _copy(source, target)

    assert "1 of 2 target cells are not in the source" in result["error"]
    assert "cell-elsewhere" in result["error"]
    assert no_snapshot(target)


def test_refuses_missing_target_gene_by_name(tmp_path, pair, no_snapshot):
    source, _, expected = pair
    genes = [*expected.columns[:9], "ENSG99999999999"]
    target = _write(
        tmp_path / "extra-gene.h5ad", sp.csr_matrix(np.ones((20, 10), dtype=np.float32)), expected.index, genes
    )

    result = _copy(source, target)

    assert "1 of 10 target genes are not in the source" in result["error"]
    assert "ENSG99999999999" in result["error"]
    assert no_snapshot(target)


@pytest.mark.filterwarnings("ignore:Observation names are not unique:UserWarning")
@pytest.mark.parametrize("side", ["source", "target"])
def test_refuses_duplicate_cell_id(pair, no_snapshot, side):
    source, target, _ = pair
    with h5py.File(source if side == "source" else target, "a") as f:
        index = f["obs/_index"]
        index[1] = index[0]  # pyright: ignore[reportIndexIssue]

    result = _copy(source, target)

    assert f"{side.capitalize()} cells have duplicate IDs" in result["error"]
    assert no_snapshot(target)


@pytest.mark.parametrize(
    ("value", "reason"),
    [(2.5, "a fractional value"), (-3.0, "a negative value"), (np.nan, "a non-finite value")],
)
def test_refuses_value_that_is_not_a_count(pair, no_snapshot, value, reason):
    source, target, expected = pair
    row = int(expected.index[4].split("-")[1])
    col = GENES.index(expected.columns[2])
    _set_value(source, "X", row, col, value)

    result = _copy(source, target)

    assert f"holds {reason}" in result["error"]
    assert f"cell {expected.index[4]}, gene {expected.columns[2]}" in result["error"]
    assert no_snapshot(target)


def test_refuses_value_float32_cannot_hold(pair, no_snapshot):
    source, target, expected = pair
    adata = ad.read_h5ad(source)
    x = adata.X.toarray().astype(np.int64)  # pyright: ignore[reportOptionalMemberAccess, reportAttributeAccessIssue]
    x[int(expected.index[0].split("-")[1]), GENES.index(expected.columns[0])] = 2**24 + 1
    adata.X = sp.csr_matrix(x)
    adata.write_h5ad(source)

    result = _copy(source, target)

    assert "a value float32 cannot hold exactly" in result["error"]
    assert no_snapshot(target)


def test_ignores_bad_values_outside_the_target(pair):
    source, target, expected = pair
    outside_cell = next(i for i in range(N_SOURCE_CELLS) if f"cell-{i}" not in expected.index)
    _set_value(source, "X", outside_cell, 0, -1.0)
    _set_value(source, "X", 0, len(GENES), 0.5)

    result = _copy(source, target)

    assert "error" not in result, result


def test_refuses_value_above_raw(pair, no_snapshot):
    source, target, expected = pair
    row, col = np.argwhere(expected.to_numpy() > 1)[0]
    _set_value(target, "raw", row, col, 1.0)

    result = _copy(source, target)

    assert "is above raw.X (1.0)" in result["error"]
    assert f"cell {expected.index[row]}, gene {expected.columns[col]}" in result["error"]
    assert no_snapshot(target)
    assert _no_scratch(target)


def test_refuses_nonzero_where_raw_is_zero(pair, no_snapshot):
    source, target, expected = pair
    row, col = np.argwhere(expected.to_numpy() > 0)[-1]
    _set_value(target, "raw", row, col, 0.0)

    result = _copy(source, target)

    assert "is where raw.X is zero" in result["error"]
    assert f"cell {expected.index[row]}, gene {expected.columns[col]}" in result["error"]
    assert no_snapshot(target)


def test_refuses_existing_layer(tmp_path, pair, no_snapshot):
    source, _, expected = pair
    x = sp.csr_matrix(expected.to_numpy())
    target = _write(tmp_path / "has-layer.h5ad", x, expected.index, expected.columns, layers={"desouped_counts": x})

    result = _copy(source, target)

    assert "already has layers['desouped_counts']" in result["error"]
    assert no_snapshot(target)


def test_refuses_cellxgene_target(pair, cellxgene_h5ad, no_snapshot):
    source, _, _ = pair

    result = _copy(source, cellxgene_h5ad)

    assert "the target declares CellxGENE schema" in result["error"]
    assert no_snapshot(cellxgene_h5ad)


def test_refuses_legacy_cap_target(pair, no_snapshot):
    source, target, _ = pair
    with h5py.File(target, "a") as f:
        write_elem(f["uns"], "cellannotation_schema_version", "1.0.0")

    result = _copy(source, target)

    assert result["error"].startswith("Refusing to copy: the file uses the deprecated top-level CAP layout")
    assert no_snapshot(target)


def test_refuses_same_file(pair):
    _, target, _ = pair

    assert _copy(target, target)["error"] == "Source and target are the same file"


def test_refuses_absent_source_matrix(pair, no_snapshot):
    source, target, _ = pair

    result = _copy(source, target, source_matrix="layers/missing")

    assert result["error"] == "The source has no layers/missing"
    assert no_snapshot(target)


@pytest.mark.parametrize("layer", ["", "a/b"])
def test_refuses_malformed_layer_name(pair, layer):
    source, target, _ = pair

    assert "layer must be a name" in _copy(source, target, layer=layer)["error"]


# --- readback -------------------------------------------------------------------


def test_tampered_readback_discards_snapshot(pair, monkeypatch, no_snapshot):
    source, target, _ = pair
    write_layer = copy_matrix.write_layer

    def write_then_tamper(f_out, layer, *args):
        write_layer(f_out, layer, *args)
        data = f_out[f"layers/{layer}/data"]
        data[3] = data[3] + 1

    monkeypatch.setattr(copy_matrix, "write_layer", write_then_tamper)

    result = _copy(source, target)

    assert "differs from the copied values" in result["error"]
    assert "the snapshot was discarded" in result["error"]
    assert no_snapshot(target)
    assert _no_scratch(target)


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        (lambda g: g.attrs.__setitem__("shape", (20, 11)), "not the target's shape as CSR"),
        (lambda g: g["indptr"].__setitem__(1, g["indptr"][1] + 1), "a different number of values per cell"),
    ],
    ids=["shape", "indptr"],
)
def test_readback_checks_layer_structure(pair, monkeypatch, no_snapshot, tamper, message):
    source, target, _ = pair
    write_layer = copy_matrix.write_layer

    def write_then_tamper(f_out, layer, *args):
        write_layer(f_out, layer, *args)
        tamper(f_out[f"layers/{layer}"])

    monkeypatch.setattr(copy_matrix, "write_layer", write_then_tamper)

    result = _copy(source, target)

    assert message in result["error"]
    assert no_snapshot(target)


def test_refuses_csc_target_raw(pair, no_snapshot):
    source, target, _ = pair
    adata = ad.read_h5ad(target)
    adata.raw = ad.AnnData(X=sp.csc_matrix(adata.raw.X), obs=adata.obs, var=adata.var)  # pyright: ignore[reportOptionalMemberAccess, reportArgumentType]
    adata.write_h5ad(target)

    result = _copy(source, target)

    assert result["error"] == "The target's raw.X is csc_matrix, which cannot be read by row to check the copy against"
    assert no_snapshot(target)


def test_refuses_target_with_unreadable_edit_log(pair, no_snapshot):
    source, target, _ = pair
    with h5py.File(target, "a") as f:
        write_elem(f["uns"], "provenance", {"edit_history": "not json {"})

    result = _copy(source, target)

    assert "contains invalid JSON" in result["error"]
    assert no_snapshot(target)
    assert _no_scratch(target)


# --- units --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spelling", "key"),
    [("X", "X"), ("raw.X", "raw/X"), ("layers/counts", "layers/counts")],
)
def test_parse_source_matrix(spelling, key):
    assert parse_source_matrix(spelling) == key


@pytest.mark.parametrize("spelling", ["raw/X", "layers/", "layers/a/b", "obsm/X_umap"])
def test_parse_source_matrix_refuses(spelling):
    with pytest.raises(ValueError, match="source_matrix must be"):
        parse_source_matrix(spelling)


def test_first_bad_value_order():
    assert first_bad_value(np.array([1.0, 2.0], dtype=np.float32)) is None
    assert first_bad_value(np.array([1.5, -1.0, np.inf])) == ("a non-finite value", 2)
    assert first_bad_value(np.array([1.5, -1.0])) == ("a negative value", 1)
    assert first_bad_value(np.array([3, -2], dtype=np.int64)) == ("a negative value", 1)


def test_raw_problem():
    layer = sp.csr_matrix(np.array([[1, 0, 2], [0, 3, 0]], dtype=np.float32))
    raw = sp.csr_matrix(np.array([[1, 5, 2], [0, 3, 1]], dtype=np.float32))
    assert raw_problem(layer, raw) is None
    assert raw_problem(layer, sp.csr_matrix(np.array([[1, 0, 1], [0, 3, 0]], dtype=np.float32))) == (
        "above raw.X (1.0)",
        0,
        2,
    )
    assert raw_problem(layer, sp.csr_matrix((2, 3), dtype=np.float32)) == ("where raw.X is zero", 0, 0)
    # Duplicate raw entries that sum to zero are zero, not a raw value of 0.0 to be above.
    summed_to_zero = sp.csr_matrix((np.array([2, -2, 2, 3], dtype=np.float32), [0, 0, 2, 1], [0, 3, 4]), shape=(2, 3))
    assert raw_problem(layer, summed_to_zero) == ("where raw.X is zero", 0, 0)


def test_refuses_target_raw_with_other_genes(tmp_path, pair, no_snapshot):
    source, _, expected = pair
    x = sp.csr_matrix(expected.to_numpy())
    adata = ad.AnnData(X=x, obs=pd.DataFrame(index=expected.index), var=pd.DataFrame(index=expected.columns))
    adata.raw = ad.AnnData(X=x, obs=adata.obs, var=pd.DataFrame(index=expected.columns[::-1]))
    target = tmp_path / "raw-genes-differ.h5ad"
    adata.write_h5ad(target)

    result = _copy(source, target)

    assert "raw.X does not have the target's cells and genes" in result["error"]
    assert no_snapshot(target)


def test_scratch_rows_with_no_values(tmp_path):
    scratch = copy_matrix.Scratch(
        tmp_path / "i",
        tmp_path / "d",
        np.zeros(3, dtype=np.int64),
        np.zeros(4, dtype=np.int64),
        np.zeros(3, dtype=np.uint64),
        4,
    )

    rows = scratch.rows(0, 3)

    assert rows.shape == (3, 4)
    assert rows.nnz == 0


def test_refuses_csc_source(tmp_path, pair, no_snapshot):
    source, target, _ = pair
    adata = ad.read_h5ad(source)
    adata.X = sp.csc_matrix(adata.X)  # pyright: ignore[reportArgumentType]
    adata.write_h5ad(source)

    result = _copy(source, target)

    assert result["error"] == "The source's X is csc_matrix, which cannot be read cell by cell in bounded memory"
    assert no_snapshot(target)


def test_explicit_zeros_in_source_are_dropped(pair):
    source, target, expected = pair
    with h5py.File(source, "a") as f:
        data = f["X/data"]
        data[::2] = 0  # pyright: ignore[reportIndexIssue]

    result = _copy(source, target)

    assert "error" not in result, result
    layer = ad.read_h5ad(result["output_path"]).layers["desouped_counts"]
    assert layer.nnz == int((layer.toarray() != 0).sum())  # pyright: ignore[reportAttributeAccessIssue]


def test_second_copy_replaces_the_first_snapshot(pair):
    source, target, expected = pair
    first = _copy(source, target, layer="first")["output_path"]

    result = _copy(source, target, layer="second")

    assert "error" not in result, result
    assert not Path(first).exists()
    layers = ad.read_h5ad(result["output_path"]).layers
    np.testing.assert_array_equal(layers["first"].toarray(), layers["second"].toarray())  # pyright: ignore[reportAttributeAccessIssue]
    np.testing.assert_array_equal(layers["second"].toarray(), expected)  # pyright: ignore[reportAttributeAccessIssue]


def test_refuses_target_raw_without_raw_var(pair, no_snapshot):
    source, target, _ = pair
    with h5py.File(target, "a") as f:
        del f["raw/var"]

    result = _copy(source, target)

    assert result["error"] == "The target has raw.X but no raw.var, so the copy cannot be checked against it"
    assert no_snapshot(target)


def _store_a_gene_twice(path: Path, key: str, cell: str, genes: list[str]) -> str:
    """Point a second stored entry of ``cell``'s row at the gene of its first; return that gene."""
    with h5py.File(path, "a") as f:
        cells = [c.decode() for c in f["obs/_index"][:]]  # pyright: ignore[reportIndexIssue]
        var_key = "raw/var" if key == "raw/X" else "var"
        var = [g.decode() for g in f[f"{var_key}/_index"][:]]  # pyright: ignore[reportIndexIssue]
        row = cells.index(cell)
        a, b = f[f"{key}/indptr"][row : row + 2]  # pyright: ignore[reportIndexIssue]
        indices = f[f"{key}/indices"]
        stored = [i for i in range(a, b) if var[indices[i]] in genes]  # pyright: ignore[reportIndexIssue]
        indices[stored[1]] = indices[stored[0]]  # pyright: ignore[reportIndexIssue]
        return var[indices[stored[0]]]  # pyright: ignore[reportIndexIssue]


def test_refuses_source_storing_a_gene_twice(pair, no_snapshot):
    source, target, expected = pair
    cell = next(c for c in expected.index if (expected.loc[c] > 0).sum() >= 2)
    gene = _store_a_gene_twice(source, "X", cell, list(expected.columns))

    result = _copy(source, target)

    assert result["error"] == (
        f"Refusing to copy: the source's X stores gene {gene} twice for cell {cell}; "
        f"a count matrix stores each gene once per cell"
    )
    assert no_snapshot(target)


def test_refuses_target_raw_storing_a_gene_twice(pair, no_snapshot):
    source, target, expected = pair
    gene = _store_a_gene_twice(target, "raw/X", expected.index[3], list(expected.columns))

    result = _copy(source, target)

    assert result["error"] == (
        f"Refusing to copy: the target's raw.X stores gene {gene} twice for cell {expected.index[3]}; "
        f"a count matrix stores each gene once per cell"
    )
    assert no_snapshot(target)


def test_first_repeated_entry():
    def csr(indices, indptr):
        return sp.csr_matrix((np.ones(len(indices)), indices, indptr), shape=(len(indptr) - 1, 5))

    assert first_repeated_entry(csr([0, 2, 2, 4], [0, 2, 4])) is None  # gene 2 ends one row and starts the next
    assert first_repeated_entry(csr([1, 3, 3], [0, 3])) == 2
    assert first_repeated_entry(csr([], [0, 0, 0])) is None


def test_refuses_orphaned_snapshot_before_reading_the_source(pair, monkeypatch):
    source, target, _ = pair
    orphan = target.with_name("target-edit-2026-01-01-00-00-00.h5ad")
    target.rename(orphan)
    monkeypatch.setattr(copy_matrix, "stage_source", lambda *a: pytest.fail("the source was read"))

    result = _copy(source, orphan)

    assert "is an edit snapshot but its original (target.h5ad) is not beside it" in result["error"]
    assert [p.name for p in orphan.parent.iterdir() if "-edit-" in p.name] == [orphan.name]


def test_row_offsets_past_int32():
    indptr = np.array([0, 3, 5], dtype=np.int32)

    offsets = row_offsets(2**31 - 2, indptr)

    assert offsets.dtype == np.int64
    assert offsets.tolist() == [2**31 - 2, 2**31 + 1]


def test_misplaced_scratch_rows_are_caught_against_the_source(tmp_path, pair, monkeypatch, no_snapshot):
    source, _, expected = pair
    target = _write(tmp_path / "no-raw.h5ad", sp.csr_matrix(expected.to_numpy()), expected.index, expected.columns)
    offsets = copy_matrix.row_offsets
    monkeypatch.setattr(copy_matrix, "row_offsets", lambda written, indptr: np.roll(offsets(written, indptr), 1))

    result = _copy(source, target)

    assert "does not match the source at cell" in result["error"]
    assert no_snapshot(target)


@pytest.mark.parametrize("seed", range(24))
def test_random_subsets_and_orders_match_scipy(tmp_path, seed):
    rng = np.random.default_rng(seed)
    n_cells, n_genes = int(rng.integers(1, 40)), int(rng.integers(1, 15))
    counts = _counts(rng, n_cells, n_genes, density=float(rng.uniform(0.05, 0.9)))
    cells = np.array([f"c{i}" for i in range(n_cells)])
    genes = np.array([f"ENSG{i:011d}" for i in range(n_genes)])
    source = _write(tmp_path / "source.h5ad", sp.csr_matrix(counts), cells, genes)

    row_pick = rng.permutation(n_cells)[: int(rng.integers(1, n_cells + 1))]
    col_pick = rng.permutation(n_genes)[: int(rng.integers(1, n_genes + 1))]
    if seed % 3 == 0:
        row_pick = np.sort(row_pick)[::-1]
    want = sp.csr_matrix(counts)[row_pick][:, col_pick]
    raw = want.toarray() + (want.toarray() > 0) * rng.integers(0, 3, size=want.shape)
    target = _write(
        tmp_path / "target.h5ad", sp.csr_matrix(raw), cells[row_pick], genes[col_pick], raw_x=sp.csr_matrix(raw)
    )

    result = _copy(source, target, chunk_nnz=int(rng.choice([1, 2, 3, 5, 1000])))

    assert "error" not in result, result
    np.testing.assert_array_equal(
        ad.read_h5ad(result["output_path"]).layers["desouped_counts"].toarray(), want.toarray()
    )  # pyright: ignore[reportAttributeAccessIssue]


def test_row_digests():
    m = sp.csr_matrix(np.array([[1, 2, 0], [3, 1, 0], [1, 2, 0], [0, 0, 0], [0, 1, 2]], dtype=np.float32))

    digests = row_digests(m)

    assert digests.dtype == np.uint64
    assert digests[0] == digests[2]  # the same entries
    assert len({int(d) for d in digests[[0, 1, 3, 4]]}) == 4  # [1, 2] and [3, 1] share a weighted sum
    assert digests[3] == 0


def test_swapped_rows_with_equal_weighted_sums_are_caught(tmp_path, monkeypatch, no_snapshot):
    genes = GENES[:2]
    pair = sp.csr_matrix(np.array([[1, 2], [3, 1]], dtype=np.float32))
    source = _write(tmp_path / "source.h5ad", pair, ["a", "b"], genes)
    target = _write(tmp_path / "target.h5ad", pair, ["a", "b"], genes)
    offsets = copy_matrix.row_offsets
    monkeypatch.setattr(copy_matrix, "row_offsets", lambda written, indptr: offsets(written, indptr)[::-1])

    result = _copy(source, target)

    assert result["error"].startswith("The readback of layers['desouped_counts'] does not match the source at cell a")
    assert no_snapshot(target)


def test_raw_refusal_comes_before_the_snapshot(pair, monkeypatch):
    source, target, expected = pair
    row, col = np.argwhere(expected.to_numpy() > 1)[0]
    _set_value(target, "raw", row, col, 1.0)
    monkeypatch.setattr(copy_matrix, "snapshot_copy_hashed", lambda path: pytest.fail("the target was copied"))

    result = _copy(source, target)

    assert "is above raw.X (1.0)" in result["error"]


@pytest.mark.parametrize("raw_format", ["csr", "dense"])
def test_check_blocks_are_bounded_by_raw_too(tmp_path, monkeypatch, raw_format):
    n_cells, n_genes = 12, 10
    counts = np.zeros((n_cells, n_genes), dtype=np.float32)
    counts[0, 0] = 1
    cells = [f"c{i}" for i in range(n_cells)]
    source = _write(tmp_path / "source.h5ad", sp.csr_matrix(counts), cells, GENES[:n_genes])
    raw = np.ones((n_cells, n_genes), dtype=np.float32)
    raw_x = sp.csr_matrix(raw) if raw_format == "csr" else raw
    target = _write(tmp_path / "target.h5ad", sp.csr_matrix(raw), cells, GENES[:n_genes], raw_x=raw_x)
    rows_read = []
    reader = copy_matrix._raw_block_reader

    def recording_reader(item):
        read = reader(item)
        return lambda start, stop: rows_read.append(stop - start) or read(start, stop)

    monkeypatch.setattr(copy_matrix, "_raw_block_reader", recording_reader)

    result = _copy(source, target, chunk_nnz=25)

    assert "error" not in result, result
    assert sum(rows_read) == n_cells
    assert max(rows_read) * n_genes <= 25
