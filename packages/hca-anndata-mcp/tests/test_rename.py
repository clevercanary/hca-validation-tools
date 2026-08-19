"""Unit tests for the rename_cell_ids MCP wrapper."""

import anndata as ad
import numpy as np
import pandas as pd

from hca_anndata_mcp.tools.rename import rename_cell_ids


def _write_hca_file(path):
    ids = ["MH_mix_AAA", "MH_mix_TTT", "MH_mix_CCC"]
    obs = pd.DataFrame(
        {"sample_id": pd.Categorical(["B1_0023", "N_0123", "B1_0023"])},
        index=pd.Index(ids, name="cellID"),
    )
    adata = ad.AnnData(X=np.zeros((3, 2), dtype=np.float32), obs=obs)
    adata.write_h5ad(path)
    return path


def test_rename_missing_file():
    result = rename_cell_ids("/nonexistent/file.h5ad", where={"a": "b"}, prefix_from="x_", prefix_to="y_")
    assert "error" in result
    assert "File not found" in result["error"]


def test_rename_through_wrapper(tmp_path):
    """Happy path through the wrapper: selected rows renamed, counts reported."""
    path = _write_hca_file(tmp_path / "test.h5ad")

    result = rename_cell_ids(str(path), where={"sample_id": "B1_0023"}, prefix_from="MH_mix_", prefix_to="MH_mix_BR1_")

    assert "error" not in result
    assert result["n_renamed"] == 2
    assert list(ad.read_h5ad(result["output_path"]).obs_names) == [
        "MH_mix_BR1_AAA",
        "MH_mix_TTT",
        "MH_mix_BR1_CCC",
    ]


def test_rename_refuses_cellxgene_through_wrapper(tmp_path):
    """The HCA-layout gate lives in the tools layer; this pins that the
    wrapper does not bypass it."""
    from hca_anndata_tools.testing import create_sample_h5ad

    path = create_sample_h5ad(tmp_path / "cxg.h5ad")  # sets uns['schema_version']

    result = rename_cell_ids(str(path), where={"tissue": "brain"}, prefix_from="cell_", prefix_to="c_")

    assert "error" in result
    assert "CellxGENE" in result["error"]
