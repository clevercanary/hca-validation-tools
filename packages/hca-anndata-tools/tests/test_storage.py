"""Tests for the get_storage_info function."""

from hca_anndata_tools.storage import get_storage_info


def test_storage_file_size(sample_h5ad):
    result = get_storage_info(str(sample_h5ad))
    assert "error" not in result
    assert result["file_size_bytes"] > 0
    assert result["file_size_mb"] >= 0


def test_storage_x_info(sample_h5ad):
    result = get_storage_info(str(sample_h5ad))
    # Sample h5ad has a sparse X matrix, stored as a group
    x = result["X"]
    assert x is not None
    assert "format" in x or "dtype" in x


def test_storage_layers(sample_h5ad):
    result = get_storage_info(str(sample_h5ad))
    layers = result["layers"]
    assert layers is not None
    assert "raw_counts" in layers


def test_storage_raw_x_absent(sample_h5ad):
    """Sample file has no raw.X."""
    result = get_storage_info(str(sample_h5ad))
    assert result["raw_X"] is None


def test_storage_non_h5ad():
    result = get_storage_info("/some/path/file.zarr")
    assert "error" in result
    assert "h5ad" in result["error"].lower()


def test_storage_missing_file():
    result = get_storage_info("/nonexistent/file.h5ad")
    assert "error" in result
