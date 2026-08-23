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


def test_drop_refusal_reaches_through_wrapper(tmp_path):
    """A coherence refusal must be in force via the wrapper too — it lives in
    the tools layer, not the MCP layer, so this pins that the wrapper does not
    bypass it. The obs index is the coherence guard every layout carries
    (schema-tier refusals were removed in #619)."""
    import h5py

    from hca_anndata_tools.testing import create_sample_h5ad

    path = tmp_path / "test.h5ad"
    create_sample_h5ad(path)
    with h5py.File(path, "r") as f:
        index_name = f["obs"].attrs.get("_index", "_index")
        index_name = index_name.decode() if isinstance(index_name, bytes) else index_name

    result = drop_obs_columns(str(path), [index_name])

    assert "error" in result
    assert "obs index" in result["error"]
