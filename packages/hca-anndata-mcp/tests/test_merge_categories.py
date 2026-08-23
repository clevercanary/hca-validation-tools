"""Unit tests for the merge_obs_categories MCP wrapper."""

import anndata as ad
import pandas as pd

from hca_anndata_mcp.tools.merge_categories import merge_obs_categories


def _make(tmp_path):
    from hca_anndata_tools.testing import create_sample_h5ad

    path = tmp_path / "test.h5ad"
    create_sample_h5ad(path)
    adata = ad.read_h5ad(path)
    adata.obs["procedure"] = pd.Categorical(["Prophylactic"] * (adata.n_obs - 2) + ["Prophylatctic"] * 2)
    adata.write_h5ad(path)
    return path


def test_merge_through_wrapper(tmp_path):
    path = _make(tmp_path)

    result = merge_obs_categories(str(path), "procedure", "Prophylatctic", "Prophylactic")

    assert "error" not in result
    assert result["cells_recoded"] == 2
    out = ad.read_h5ad(result["output_path"])
    assert list(out.obs["procedure"].cat.categories) == ["Prophylactic"]


def test_refusal_reaches_through_wrapper(tmp_path):
    """The guards live in the tools layer, not the MCP layer — this pins that
    the wrapper does not bypass them."""
    path = _make(tmp_path)

    result = merge_obs_categories(str(path), "procedure", "Absent", "Prophylactic")

    assert "error" in result
    assert "Absent" in result["error"]


def test_merge_missing_file():
    result = merge_obs_categories("/nonexistent/file.h5ad", "col", "a", "b")
    assert "error" in result
    assert "File not found" in result["error"]
