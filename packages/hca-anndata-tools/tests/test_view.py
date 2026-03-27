"""Tests for the view_data function."""

from hca_anndata_tools.view import view_data


def test_view_obs(sample_h5ad):
    result = view_data(str(sample_h5ad), attribute="obs", row_start=0, row_end=5)
    assert result["type"] == "dataframe"
    assert result["slice_shape"] == [5, 4]
    assert result["full_shape"] == [50, 4]
    assert len(result["index"]) == 5


def test_view_obs_columns(sample_h5ad):
    result = view_data(str(sample_h5ad), attribute="obs", columns=["sex", "tissue"], row_end=3)
    assert result["type"] == "dataframe"
    assert result["columns"] == ["sex", "tissue"]
    assert result["slice_shape"][0] == 3


def test_view_var(sample_h5ad):
    result = view_data(str(sample_h5ad), attribute="var", row_end=5)
    assert result["type"] == "dataframe"
    assert "gene_name" in result["columns"]


def test_view_X(sample_h5ad):
    result = view_data(str(sample_h5ad), attribute="X", row_end=3, col_end=5)
    assert result["type"] == "array"
    assert result["slice_shape"] == [3, 5]
    assert result["full_shape"] == [50, 20]


def test_view_obsm(sample_h5ad):
    result = view_data(str(sample_h5ad), attribute="obsm", key="X_umap", row_end=5)
    assert result["type"] == "array"
    assert result["full_shape"] == [50, 2]


def test_view_layer(sample_h5ad):
    result = view_data(str(sample_h5ad), attribute="layers", key="raw_counts", row_end=3, col_end=5)
    assert result["type"] == "array"
    assert result["slice_shape"] == [3, 5]


def test_view_uns(sample_h5ad):
    result = view_data(str(sample_h5ad), attribute="uns")
    assert result["type"] == "dict"
    assert result["data"]["title"] == "Test Dataset"
    assert result["data"]["schema_version"] == "5.1.0"


def test_view_bad_attribute(sample_h5ad):
    result = view_data(str(sample_h5ad), attribute="nonexistent")
    assert "error" in result


def test_view_bad_key(sample_h5ad):
    result = view_data(str(sample_h5ad), attribute="obsm", key="nonexistent")
    assert "error" in result


def test_view_missing_file():
    result = view_data("/nonexistent/file.h5ad", attribute="obs")
    assert "error" in result
