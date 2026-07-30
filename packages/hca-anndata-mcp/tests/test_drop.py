"""Unit tests for the drop_obs_columns MCP wrapper."""

import anndata as ad
import pandas as pd

from hca_anndata_mcp.tools.drop import drop_obs_columns


def test_drop_missing_file():
    result = drop_obs_columns("/nonexistent/file.h5ad", ["race"])
    assert "error" in result
    assert "File not found" in result["error"]


def test_drop_removes_producer_column(tmp_path):
    """Happy path through the wrapper: a column the HCA schema does not name
    drops cleanly."""
    from hca_anndata_tools.testing import create_sample_h5ad

    path = tmp_path / "test.h5ad"
    create_sample_h5ad(path)
    adata = ad.read_h5ad(path)
    adata.obs["ethnicity_verbatim"] = pd.Categorical(["unknown"] * adata.n_obs)
    adata.write_h5ad(path)

    result = drop_obs_columns(str(path), ["ethnicity_verbatim"])

    assert "error" not in result
    assert result["obs_columns_dropped"] == ["ethnicity_verbatim"]
    assert "ethnicity_verbatim" not in ad.read_h5ad(result["output_path"]).obs.columns


def test_drop_refuses_schema_column_through_wrapper(tmp_path):
    """The guard must be in force via the wrapper too — it lives in the tools
    layer, not the MCP layer, so this pins that the wrapper does not bypass it."""
    from hca_anndata_tools.testing import create_sample_h5ad

    path = tmp_path / "test.h5ad"
    create_sample_h5ad(path)
    adata = ad.read_h5ad(path)
    adata.obs["donor_id"] = pd.Categorical(["D1"] * adata.n_obs)
    adata.write_h5ad(path)

    result = drop_obs_columns(str(path), ["donor_id"])

    assert "error" in result
    assert "donor_id" in ad.read_h5ad(path).obs.columns
