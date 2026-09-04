"""Tests for the embedding gate (#685).

Every fixture is written through anndata's own writer from numpy — anndata
accepts a 1-D obsm array and a DataFrame obsm entry, so no fixture is patched
with h5py — and each defect fixture is the clean base plus exactly one
change, so "that code and nothing else" is what each case asserts.
"""

from __future__ import annotations

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp

from hca_anndata_tools.embeddings import check_embeddings
from hca_anndata_tools.qc import SAMPLE_ID_LIMIT

N_OBS = 8
RNG = np.random.default_rng(685)


def _ids(n: int) -> list[str]:
    return [f"c{i}" for i in range(n)]


def _write(path, n: int = N_OBS, **obsm):
    adata = ad.AnnData(obs=pd.DataFrame(index=_ids(n)))  # pyright: ignore[reportArgumentType]
    for key, value in obsm.items():
        adata.obsm[key] = value
    adata.write_h5ad(path)
    return path


def _normal(n_cols: int, n: int = N_OBS):
    return RNG.standard_normal((n, n_cols)).astype(np.float32)


def _umap():
    return _normal(2)


def _pca():
    return _normal(10)


def _codes(result: dict) -> dict[str, dict]:
    assert "error" not in result, result
    return {(f["element"], f["code"]): f for f in result["findings"]}


def test_clean_fixture_has_no_findings(tmp_path):
    result = check_embeddings(_write(tmp_path / "a.h5ad", X_umap=_umap(), X_pca=_pca()))
    assert _codes(result) == {}
    assert result["skipped"] == []
    assert result["n_obs"] == N_OBS
    assert {k: v["shape"] for k, v in result["embeddings"].items()} == {"X_pca": [N_OBS, 10], "X_umap": [N_OBS, 2]}
    assert result["embeddings"]["X_umap"] == {"shape": [N_OBS, 2], "dtype": "float32", "encoding": "array"}


def test_no_obsm_is_clean(tmp_path):
    result = check_embeddings(_write(tmp_path / "a.h5ad"))
    assert _codes(result) == {}
    assert result["embeddings"] == {} and result["skipped"] == []


def test_nan_rows_are_counted_with_their_cell_ids(tmp_path):
    umap = _umap()
    umap[2, 0] = np.nan
    umap[5, 1] = np.nan
    result = check_embeddings(_write(tmp_path / "a.h5ad", X_umap=umap, X_pca=_pca()))
    codes = _codes(result)
    assert set(codes) == {("obsm/X_umap", "non_finite_values")}
    assert codes["obsm/X_umap", "non_finite_values"]["count"] == 2
    assert codes["obsm/X_umap", "non_finite_values"]["sample_ids"] == ["c2", "c5"]


def test_inf_counts_the_same_as_nan(tmp_path):
    umap = _umap()
    umap[0, 1] = np.inf
    umap[7, 0] = -np.inf
    codes = _codes(check_embeddings(_write(tmp_path / "a.h5ad", X_umap=umap)))
    assert set(codes) == {("obsm/X_umap", "non_finite_values")}
    assert codes["obsm/X_umap", "non_finite_values"]["sample_ids"] == ["c0", "c7"]


def test_all_zero(tmp_path):
    codes = _codes(check_embeddings(_write(tmp_path / "a.h5ad", X_umap=np.zeros((N_OBS, 2), np.float32))))
    assert set(codes) == {("obsm/X_umap", "all_zero")}
    assert codes["obsm/X_umap", "all_zero"]["count"] == 2
    assert codes["obsm/X_umap", "all_zero"]["sample_ids"] == ["0", "1"]


def test_constant_non_zero(tmp_path):
    codes = _codes(check_embeddings(_write(tmp_path / "a.h5ad", X_umap=np.full((N_OBS, 2), 1.5, np.float32))))
    assert set(codes) == {("obsm/X_umap", "constant")}
    assert codes["obsm/X_umap", "constant"]["value"] == 1.5


def test_one_dead_column(tmp_path):
    pca = _pca()
    pca[:, 3] = 0.25
    codes = _codes(check_embeddings(_write(tmp_path / "a.h5ad", X_pca=pca)))
    assert set(codes) == {("obsm/X_pca", "zero_variance_columns")}
    assert codes["obsm/X_pca", "zero_variance_columns"]["count"] == 1
    assert codes["obsm/X_pca", "zero_variance_columns"]["sample_ids"] == ["3"]


def test_every_column_dead_at_different_values_is_zero_variance_not_constant(tmp_path):
    umap = np.tile(np.array([[1.0, 2.0]], np.float32), (N_OBS, 1))
    codes = _codes(check_embeddings(_write(tmp_path / "a.h5ad", X_umap=umap)))
    assert set(codes) == {("obsm/X_umap", "zero_variance_columns")}
    assert codes["obsm/X_umap", "zero_variance_columns"]["sample_ids"] == ["0", "1"]


def test_one_d_array_is_wrong_shape(tmp_path):
    codes = _codes(check_embeddings(_write(tmp_path / "a.h5ad", flat=np.zeros(N_OBS, np.float32), X_umap=_umap())))
    assert set(codes) == {("obsm/flat", "wrong_shape")}
    assert codes["obsm/flat", "wrong_shape"]["shape"] == [N_OBS]


def test_zero_columns_is_wrong_shape(tmp_path):
    codes = _codes(check_embeddings(_write(tmp_path / "a.h5ad", empty=np.zeros((N_OBS, 0), np.float32))))
    assert set(codes) == {("obsm/empty", "wrong_shape")}


def test_two_broken_keys_are_both_reported(tmp_path):
    umap = _umap()
    umap[1, 0] = np.nan
    codes = _codes(check_embeddings(_write(tmp_path / "a.h5ad", X_umap=umap, X_pca=np.zeros((N_OBS, 10), np.float32))))
    assert set(codes) == {("obsm/X_umap", "non_finite_values"), ("obsm/X_pca", "all_zero")}


def test_degenerate_key_still_gets_its_finiteness_finding(tmp_path):
    umap = np.zeros((N_OBS, 2), np.float32)
    umap[4, 1] = np.nan
    codes = _codes(check_embeddings(_write(tmp_path / "a.h5ad", X_umap=umap)))
    assert set(codes) == {("obsm/X_umap", "non_finite_values"), ("obsm/X_umap", "all_zero")}


def test_column_with_no_finite_value_is_not_dead(tmp_path):
    umap = _umap()
    umap[:, 0] = np.nan
    codes = _codes(check_embeddings(_write(tmp_path / "a.h5ad", X_umap=umap)))
    assert set(codes) == {("obsm/X_umap", "non_finite_values")}
    assert codes["obsm/X_umap", "non_finite_values"]["count"] == N_OBS


def test_chunk_boundary_rows_are_both_counted(tmp_path):
    # chunk_nnz=6 on 2 columns → 3 rows per chunk; rows 2 and 3 straddle the first boundary.
    umap = _umap()
    umap[2, 0] = np.nan
    umap[3, 1] = np.nan
    umap[7, 0] = np.nan
    codes = _codes(check_embeddings(_write(tmp_path / "a.h5ad", X_umap=umap), chunk_nnz=6))
    assert codes["obsm/X_umap", "non_finite_values"]["sample_ids"] == ["c2", "c3", "c7"]


def test_chunking_does_not_change_the_column_verdict(tmp_path):
    pca = _pca()
    pca[:, 7] = -1.0
    for chunk_nnz in (1, 10, 25, 10**9):
        codes = _codes(check_embeddings(_write(tmp_path / f"{chunk_nnz}.h5ad", X_pca=pca), chunk_nnz=chunk_nnz))
        assert codes["obsm/X_pca", "zero_variance_columns"]["sample_ids"] == ["7"], chunk_nnz


def test_integer_embedding_passes_finiteness_and_is_checked_for_variance(tmp_path):
    live = RNG.integers(0, 100, (N_OBS, 3)).astype(np.int64)
    dead = np.full((N_OBS, 3), 7, np.int32)
    codes = _codes(check_embeddings(_write(tmp_path / "a.h5ad", live=live, dead=dead)))
    assert set(codes) == {("obsm/dead", "constant")}
    assert codes["obsm/dead", "constant"]["value"] == 7.0


def test_sample_ids_are_capped(tmp_path):
    n = SAMPLE_ID_LIMIT + 5
    codes = _codes(check_embeddings(_write(tmp_path / "a.h5ad", n, X_umap=np.full((n, 2), np.nan, np.float32))))
    f = codes["obsm/X_umap", "non_finite_values"]
    assert f["count"] == n and len(f["sample_ids"]) == SAMPLE_ID_LIMIT


def test_dataframe_entry_is_skipped_not_checked(tmp_path):
    frame = pd.DataFrame({"a": np.full(N_OBS, np.nan)}, index=_ids(N_OBS))
    result = check_embeddings(_write(tmp_path / "a.h5ad", X_umap=_umap(), table=frame))
    assert _codes(result) == {}
    assert "table" not in result["embeddings"]
    assert [s["key"] for s in result["skipped"]] == ["table"]
    assert result["skipped"][0]["encoding"] == "dataframe"
    assert "not an array" in result["skipped"][0]["reason"]


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(np.zeros((N_OBS, 2), bool), id="bool"),
        pytest.param(np.full((N_OBS, 2), np.nan + 0j, np.complex128), id="complex"),
    ],
)
def test_non_numeric_array_is_skipped_not_judged(tmp_path, value):
    # A bool mask is legitimately all-False and a complex NaN is not an embedding defect;
    # neither is judged, and the real embedding beside it still is.
    result = check_embeddings(_write(tmp_path / "a.h5ad", X_umap=_umap(), other=value))
    assert _codes(result) == {}
    assert list(result["embeddings"]) == ["X_umap"]
    assert [s["key"] for s in result["skipped"]] == ["other"]
    assert str(value.dtype) in result["skipped"][0]["reason"]


def test_legacy_string_dataset_is_skipped_not_crashed(tmp_path):
    # Pre-0.8 anndata wrote obsm arrays with no encoding attrs; a string one must not
    # reach the numeric scan and take every other key down with a traceback.
    path = _write(tmp_path / "a.h5ad", X_umap=np.zeros((N_OBS, 2), np.float32))
    with h5py.File(path, "r+") as f:
        f["obsm"].create_dataset("old", data=np.array([[b"a", b"b"]] * N_OBS))
    with pytest.warns(ad.OldFormatWarning):
        result = check_embeddings(path)
    assert [s["key"] for s in result["skipped"]] == ["old"]
    assert "|S1" in result["skipped"][0]["reason"]
    assert set(_codes(result)) == {("obsm/X_umap", "all_zero")}


def test_sparse_entry_is_skipped_not_checked(tmp_path):
    result = check_embeddings(_write(tmp_path / "a.h5ad", X_umap=_umap(), sparse=sp.csr_matrix(np.zeros((N_OBS, 3)))))
    assert _codes(result) == {}
    assert [(s["key"], s["encoding"]) for s in result["skipped"]] == [("sparse", "csr_matrix")]


def test_unstamped_dataset_is_checked(tmp_path):
    # Older anndata wrote obsm arrays with no encoding attrs at all; anndata still reads
    # those. (A type stamp missing while the version stays is refused at the gate.)
    path = _write(tmp_path / "a.h5ad", X_umap=np.zeros((N_OBS, 2), np.float32))
    with h5py.File(path, "r+") as f:
        for attr in ("encoding-type", "encoding-version"):
            del f["obsm/X_umap"].attrs[attr]
    with pytest.warns(ad.OldFormatWarning, match="without encoding metadata"):
        result = check_embeddings(path)
    assert result["embeddings"]["X_umap"]["encoding"] == "unstamped"
    assert set(_codes(result)) == {("obsm/X_umap", "all_zero")}


def test_wrong_row_count_is_refused_at_the_gate(tmp_path):
    # Decision 1 on #685: anndata enforces the row count, so the file never reaches this check.
    path = _write(tmp_path / "a.h5ad", X_umap=_umap())
    with h5py.File(path, "r+") as f:
        del f["obsm/X_umap"]
        ds = f["obsm"].create_dataset("X_umap", data=np.zeros((N_OBS + 1, 2), np.float32))
        ds.attrs["encoding-type"] = "array"
        ds.attrs["encoding-version"] = "0.2.0"
    result = check_embeddings(path)
    assert "error" in result
    assert "obsm" in result["error"] and "incorrect shape" in result["error"], result


def test_handler_refusals_reach_the_caller(tmp_path):
    # The shared handler's own domain is covered in test_qc; this proves the wiring.
    assert "chunk_nnz must be a positive int" in check_embeddings(_write(tmp_path / "a.h5ad"), chunk_nnz=0)["error"]
    assert "not found" in check_embeddings(str(tmp_path / "nope.h5ad"))["error"].lower()
