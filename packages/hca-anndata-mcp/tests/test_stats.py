"""Tests for the get_descriptive_stats tool."""

from hca_anndata_mcp.tools.stats import get_descriptive_stats


def test_stats_obs_all_columns(sample_h5ad):
    result = get_descriptive_stats(str(sample_h5ad), attribute="obs")
    assert "error" not in result
    assert result["n_rows"] == 50
    assert "sex" in result["columns"]
    assert "n_counts" in result["columns"]


def test_stats_numeric_column(sample_h5ad):
    result = get_descriptive_stats(str(sample_h5ad), attribute="obs", columns=["n_counts"])
    col = result["columns"]["n_counts"]
    assert col["type"] == "numeric"
    assert col["count"] == 50
    assert col["mean"] is not None
    assert col["std"] is not None


def test_stats_categorical_column(sample_h5ad):
    result = get_descriptive_stats(str(sample_h5ad), attribute="obs", columns=["sex"])
    col = result["columns"]["sex"]
    assert col["type"] == "categorical"
    assert col["unique"] == 3
    assert col["top"] in ("male", "female", "unknown")


def test_stats_value_counts(sample_h5ad):
    result = get_descriptive_stats(
        str(sample_h5ad), attribute="obs", columns=["cell_type"], value_counts=True,
    )
    col = result["columns"]["cell_type"]
    assert "value_counts" in col
    assert isinstance(col["value_counts"], dict)
    assert sum(col["value_counts"].values()) == 50


def test_stats_with_filter(sample_h5ad):
    result = get_descriptive_stats(
        str(sample_h5ad),
        attribute="obs",
        columns=["cell_type"],
        filter_column="sex",
        filter_operator="==",
        filter_value="female",
    )
    assert "error" not in result
    assert result["n_rows"] < 50


def test_stats_filter_isin(sample_h5ad):
    result = get_descriptive_stats(
        str(sample_h5ad),
        attribute="obs",
        columns=["sex"],
        filter_column="tissue",
        filter_operator="isin",
        filter_value=["brain", "lung"],
        value_counts=True,
    )
    assert "error" not in result


def test_stats_var(sample_h5ad):
    result = get_descriptive_stats(str(sample_h5ad), attribute="var")
    assert "error" not in result
    assert "gene_name" in result["columns"]


def test_stats_bad_attribute(sample_h5ad):
    result = get_descriptive_stats(str(sample_h5ad), attribute="X")
    assert "error" in result


def test_stats_missing_column(sample_h5ad):
    result = get_descriptive_stats(str(sample_h5ad), attribute="obs", columns=["nonexistent"])
    assert "error" in result
