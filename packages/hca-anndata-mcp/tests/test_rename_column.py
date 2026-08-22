"""Unit tests for the rename_obs_column MCP wrapper."""

import anndata as ad
import pandas as pd

from hca_anndata_mcp.tools.rename_column import rename_obs_column


def test_rename_missing_file():
    result = rename_obs_column("/nonexistent/file.h5ad", "a", "b")
    assert "error" in result
    assert "File not found" in result["error"]


def test_rename_producer_column(tmp_path):
    """Happy path through the wrapper: a producer column whose name misdescribes
    it takes the schema's name for what it actually holds."""
    from hca_anndata_tools.testing import create_sample_h5ad

    path = create_sample_h5ad(tmp_path / "test.h5ad")
    adata = ad.read_h5ad(path)
    adata.obs["cell_type_label"] = pd.Categorical(["T cell"] * adata.n_obs)
    adata.write_h5ad(path)

    result = rename_obs_column(str(path), "cell_type_label", "author_cell_type")

    assert "error" not in result
    out = ad.read_h5ad(result["output_path"])
    assert "author_cell_type" in out.obs.columns
    assert "cell_type_label" not in out.obs.columns
