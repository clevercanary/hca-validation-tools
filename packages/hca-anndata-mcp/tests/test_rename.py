"""Unit tests for the rename_cell_ids MCP wrapper."""

import anndata as ad

from hca_anndata_mcp.tools.rename import rename_cell_ids


def test_rename_missing_file():
    result = rename_cell_ids("/nonexistent/file.h5ad", column="a", value="b", prefix_from="x_", prefix_to="y_")
    assert "error" in result
    assert "File not found" in result["error"]


def test_rename_through_wrapper(tmp_path):
    """Happy path through the wrapper: pins the wiring only — result keys and
    one cheap observable. Rename semantics are the tools layer's tests."""
    from hca_anndata_tools.testing import create_hca_h5ad

    path = create_hca_h5ad(tmp_path / "test.h5ad")

    result = rename_cell_ids(
        str(path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )

    assert "error" not in result
    assert result["n_renamed"] == result["n_selected"] > 0
    assert result["examples"][0] == ["MH_mix_AAA", "MH_mix_BR1_AAA"]
    assert "MH_mix_BR1_AAA" in ad.read_h5ad(result["output_path"]).obs_names


def test_rename_refuses_cellxgene_through_wrapper(sample_h5ad):
    """The HCA-layout gate lives in the tools layer; this pins that the
    wrapper does not bypass it. Read-only, so the session fixture is safe."""
    result = rename_cell_ids(str(sample_h5ad), column="tissue", value="brain", prefix_from="cell_", prefix_to="c_")

    assert "error" in result
    assert "CellxGENE" in result["error"]
