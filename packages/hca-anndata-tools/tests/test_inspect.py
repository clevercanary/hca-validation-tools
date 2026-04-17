"""Tests for check_x_normalization."""

import anndata as ad
import numpy as np
import pandas as pd
import scipy.sparse as sp
from hca_anndata_tools.inspect import check_x_normalization


def _write_h5ad(path, X, include_raw=False):
    adata = ad.AnnData(
        X=X,
        obs=pd.DataFrame(index=[f"c{i}" for i in range(X.shape[0])]),  # pyright: ignore[reportArgumentType]
        var=pd.DataFrame(index=[f"g{i}" for i in range(X.shape[1])]),  # pyright: ignore[reportArgumentType]
    )
    if include_raw:
        adata.raw = adata.copy()
    adata.write_h5ad(path)
    return path


def test_check_x_normalization_detects_raw_counts(tmp_path):
    rng = np.random.default_rng(5)
    X = sp.csr_matrix(rng.integers(0, 10, size=(20, 15)).astype(np.float32))
    path = _write_h5ad(tmp_path / "raw.h5ad", X)

    result = check_x_normalization(str(path))
    assert "error" not in result
    assert result["verdict"] == "raw_counts"
    assert result["is_integer_valued"] is True
    assert result["has_negative"] is False
    assert result["has_raw_x"] is False
    assert result["nonzero_count"] > 0
    assert result["nonzero_min"] >= 1.0
    assert "dtype" in result


def test_check_x_normalization_detects_normalized_floats(tmp_path):
    rng = np.random.default_rng(5)
    X = sp.csr_matrix(rng.random((20, 15)).astype(np.float32))  # floats in [0, 1)
    path = _write_h5ad(tmp_path / "normalized.h5ad", X)

    result = check_x_normalization(str(path))
    assert "error" not in result
    assert result["verdict"] == "normalized"
    assert result["is_integer_valued"] is False


def test_check_x_normalization_detects_negative_values(tmp_path):
    X = sp.csr_matrix(np.array([[1.0, -2.0], [3.0, 4.0]], dtype=np.float32))
    path = _write_h5ad(tmp_path / "neg.h5ad", X)

    result = check_x_normalization(str(path))
    assert result["verdict"] == "normalized"
    assert result["has_negative"] is True


def test_check_x_normalization_reports_has_raw_x(tmp_path):
    rng = np.random.default_rng(5)
    X = sp.csr_matrix(rng.integers(0, 10, size=(10, 8)).astype(np.float32))
    path = _write_h5ad(tmp_path / "with_raw.h5ad", X, include_raw=True)

    result = check_x_normalization(str(path))
    assert result["has_raw_x"] is True


def test_check_x_normalization_indeterminate_when_all_zero(tmp_path):
    X = sp.csr_matrix(np.zeros((10, 5), dtype=np.float32))
    path = _write_h5ad(tmp_path / "empty.h5ad", X)

    result = check_x_normalization(str(path))
    assert result["verdict"] == "indeterminate"
    assert result["nonzero_count"] == 0
    assert "nonzero_min" not in result
    assert "nonzero_max" not in result


def test_check_x_normalization_dense_x(tmp_path):
    rng = np.random.default_rng(5)
    X = rng.integers(0, 10, size=(10, 8)).astype(np.float32)
    path = _write_h5ad(tmp_path / "dense.h5ad", X)

    result = check_x_normalization(str(path))
    assert "error" not in result
    assert result["verdict"] == "raw_counts"


def test_check_x_normalization_custom_sample_size(tmp_path):
    rng = np.random.default_rng(5)
    X = sp.csr_matrix(rng.integers(0, 10, size=(30, 20)).astype(np.float32))
    path = _write_h5ad(tmp_path / "sized.h5ad", X)

    result = check_x_normalization(str(path), sample_size=5)
    assert result["sample_size"] <= 5


def test_check_x_normalization_missing_file():
    result = check_x_normalization("/nonexistent/does-not-exist.h5ad")
    assert "error" in result


def test_check_x_normalization_filters_nan_from_min_max(tmp_path):
    """NaN/inf in X must not leak into nonzero_min/max (breaks strict JSON)."""
    X = sp.csr_matrix(np.array([[1.0, np.nan], [np.inf, 3.0]], dtype=np.float32))
    path = _write_h5ad(tmp_path / "nan.h5ad", X)

    result = check_x_normalization(str(path))
    assert result["nonzero_min"] == 1.0
    assert result["nonzero_max"] == 3.0
