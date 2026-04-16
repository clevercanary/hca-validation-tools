"""Tests for the get_summary function."""

from hca_anndata_tools.summary import get_summary


def test_summary_basic(sample_h5ad):
    result = get_summary(str(sample_h5ad))
    assert "error" not in result
    assert result["n_obs"] == 50
    assert result["n_vars"] == 20


def test_summary_obs_columns(sample_h5ad):
    result = get_summary(str(sample_h5ad))
    col_names = [c["name"] for c in result["obs_columns"]]
    assert "sex" in col_names
    assert "tissue" in col_names
    assert "cell_type" in col_names
    assert "n_counts" in col_names


def test_summary_var_columns(sample_h5ad):
    result = get_summary(str(sample_h5ad))
    col_names = [c["name"] for c in result["var_columns"]]
    assert "gene_name" in col_names
    assert "highly_variable" in col_names


def test_summary_obsm(sample_h5ad):
    result = get_summary(str(sample_h5ad))
    obsm_keys = [k["key"] for k in result["obsm_keys"]]
    assert "X_umap" in obsm_keys
    assert "X_pca" in obsm_keys


def test_summary_layers(sample_h5ad):
    result = get_summary(str(sample_h5ad))
    layer_names = [layer["name"] for layer in result["layers"]]
    assert "raw_counts" in layer_names


def test_summary_uns(sample_h5ad):
    result = get_summary(str(sample_h5ad))
    assert "title" in result["uns_keys"]
    assert "schema_version" in result["uns_keys"]


def test_summary_missing_file():
    result = get_summary("/nonexistent/file.h5ad")
    assert "error" in result
