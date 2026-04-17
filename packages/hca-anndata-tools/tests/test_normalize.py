"""Tests for normalize_raw."""

import json

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp
from hca_anndata_tools.normalize import normalize_raw


def _write_raw_counts(path, *, density=0.3, n_obs=40, n_vars=15) -> None:
    """Write an h5ad with raw integer counts in X and no raw.X."""
    rng = np.random.default_rng(7)
    dense = rng.integers(1, 10, size=(n_obs, n_vars)).astype(np.float32)
    mask = rng.random((n_obs, n_vars)) < density
    masked = dense * mask
    # Guarantee at least one nonzero per row so normalize_total doesn't warn.
    masked[np.arange(n_obs), rng.integers(0, n_vars, size=n_obs)] = dense[
        np.arange(n_obs), rng.integers(0, n_vars, size=n_obs)
    ]
    X = sp.csr_matrix(masked)
    obs = pd.DataFrame(
        {"cell_type": pd.Categorical(rng.choice(["A", "B"], n_obs))},
        index=[f"c{i}" for i in range(n_obs)],  # pyright: ignore[reportArgumentType]
    )
    var = pd.DataFrame(index=[f"g{i}" for i in range(n_vars)])  # pyright: ignore[reportArgumentType]
    adata = ad.AnnData(X=X, obs=obs, var=var)
    adata.write_h5ad(path)


@pytest.fixture
def raw_counts_h5ad(tmp_path):
    path = tmp_path / "raw_counts.h5ad"
    _write_raw_counts(path)
    return path


def test_normalize_raw_moves_counts_and_normalizes(raw_counts_h5ad):
    original = ad.read_h5ad(raw_counts_h5ad)

    result = normalize_raw(str(raw_counts_h5ad))
    assert "error" not in result
    assert result["target_sum"] == 1e4
    assert result["n_obs"] == original.n_obs
    assert result["n_vars"] == original.n_vars

    out = ad.read_h5ad(result["output_path"])
    assert out.raw is not None
    np.testing.assert_array_equal(out.raw.X.toarray(), original.X.toarray())  # pyright: ignore[reportAttributeAccessIssue]

    # X should now be normalized + log1p: non-negative floats, mostly non-integer
    x_dense = out.X.toarray()  # pyright: ignore[reportAttributeAccessIssue]
    assert (x_dense >= 0).all()
    assert not np.all(np.mod(x_dense[x_dense > 0], 1) == 0)


def test_normalize_raw_fails_when_raw_exists(raw_counts_h5ad):
    # First normalize succeeds
    result = normalize_raw(str(raw_counts_h5ad))
    assert "error" not in result
    # Second normalize on the output should fail — raw.X is now present
    result2 = normalize_raw(result["output_path"])
    assert "error" in result2
    assert "raw" in result2["error"].lower()


def test_normalize_raw_fails_when_x_has_non_integer(tmp_path):
    rng = np.random.default_rng(3)
    X = rng.random((20, 10)).astype(np.float32)  # floats in [0, 1)
    adata = ad.AnnData(
        X=sp.csr_matrix(X),
        obs=pd.DataFrame(index=[f"c{i}" for i in range(20)]),  # pyright: ignore[reportArgumentType]
        var=pd.DataFrame(index=[f"g{i}" for i in range(10)]),  # pyright: ignore[reportArgumentType]
    )
    path = tmp_path / "normalized.h5ad"
    adata.write_h5ad(path)

    result = normalize_raw(str(path))
    assert "error" in result
    assert "non-integer" in result["error"].lower()


def test_normalize_raw_fails_on_negative_values(tmp_path):
    X = np.array([[1.0, -2.0], [3.0, 4.0]], dtype=np.float32)
    adata = ad.AnnData(
        X=sp.csr_matrix(X),
        obs=pd.DataFrame(index=["c0", "c1"]),  # pyright: ignore[reportArgumentType]
        var=pd.DataFrame(index=["g0", "g1"]),  # pyright: ignore[reportArgumentType]
    )
    path = tmp_path / "negatives.h5ad"
    adata.write_h5ad(path)

    result = normalize_raw(str(path))
    assert "error" in result
    assert "negative" in result["error"].lower()


def test_normalize_raw_edit_log_written(raw_counts_h5ad):
    result = normalize_raw(str(raw_counts_h5ad))
    assert "error" not in result

    with h5py.File(result["output_path"], "r") as f:
        log_raw = f["uns/provenance/edit_history"][()]
    log = json.loads(log_raw.decode("utf-8") if isinstance(log_raw, bytes) else log_raw)
    assert len(log) == 1
    entry = log[0]
    assert entry["operation"] == "normalize_raw"
    assert entry["details"]["target_sum"] == 1e4
    assert entry["details"]["n_obs"] == result["n_obs"]
    assert entry["details"]["n_vars"] == result["n_vars"]
    assert "source_sha256" in entry


def test_normalize_raw_missing_file(tmp_path):
    result = normalize_raw(str(tmp_path / "does-not-exist.h5ad"))
    assert "error" in result


def test_normalize_raw_strips_log1p_uns_stamp(raw_counts_h5ad):
    """scanpy's uns['log1p'] stamp roundtrips to an empty dict that CXG rejects (#327)."""
    result = normalize_raw(str(raw_counts_h5ad))
    assert "error" not in result

    out = ad.read_h5ad(result["output_path"])
    assert "log1p" not in out.uns


def test_normalize_raw_strips_feature_is_filtered_from_raw_var(tmp_path):
    """raw.var must not contain feature_is_filtered per CXG schema (#326)."""
    rng = np.random.default_rng(13)
    n_obs, n_vars = 30, 10
    X = rng.integers(0, 10, size=(n_obs, n_vars)).astype(np.float32)
    var = pd.DataFrame(
        {
            "feature_is_filtered": [False] * n_vars,
            "gene_symbol": [f"G{i}" for i in range(n_vars)],
        },
        index=[f"ENSG{i:011d}" for i in range(n_vars)],  # pyright: ignore[reportArgumentType]
    )
    adata = ad.AnnData(
        X=sp.csr_matrix(X),
        obs=pd.DataFrame(index=[f"c{i}" for i in range(n_obs)]),  # pyright: ignore[reportArgumentType]
        var=var,
    )
    path = tmp_path / "with_feature_is_filtered.h5ad"
    adata.write_h5ad(path)

    result = normalize_raw(str(path))
    assert "error" not in result

    out = ad.read_h5ad(result["output_path"])
    assert "feature_is_filtered" not in out.raw.var.columns  # pyright: ignore[reportOptionalMemberAccess]
    # Other var columns preserved in raw.var
    assert "gene_symbol" in out.raw.var.columns  # pyright: ignore[reportOptionalMemberAccess]
    # Normalized var still has feature_is_filtered
    assert "feature_is_filtered" in out.var.columns


def test_normalize_raw_dense_x(tmp_path):
    """Dense X with integer values should also work."""
    rng = np.random.default_rng(11)
    X = rng.integers(0, 10, size=(20, 8)).astype(np.float32)
    adata = ad.AnnData(
        X=X,
        obs=pd.DataFrame(index=[f"c{i}" for i in range(20)]),  # pyright: ignore[reportArgumentType]
        var=pd.DataFrame(index=[f"g{i}" for i in range(8)]),  # pyright: ignore[reportArgumentType]
    )
    path = tmp_path / "dense.h5ad"
    adata.write_h5ad(path)

    result = normalize_raw(str(path))
    assert "error" not in result

    out = ad.read_h5ad(result["output_path"])
    assert out.raw is not None
    np.testing.assert_array_equal(np.asarray(out.raw.X), X)
