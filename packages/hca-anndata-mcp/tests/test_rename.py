"""Unit tests for the rename_cell_ids MCP wrapper."""

import anndata as ad

from hca_anndata_mcp.tools.rename import rename_cell_ids


def test_rename_missing_file():
    result = rename_cell_ids("/nonexistent/file.h5ad", column="a", value="b", prefix_from="x_", prefix_to="y_")
    assert "error" in result
    assert "File not found" in result["error"]


def test_rename_through_wrapper(tmp_path):
    """Happy path through the wrapper: selected rows renamed, counts reported."""
    from hca_anndata_tools.testing import HCA_TEST_ROWS, create_hca_h5ad

    path = create_hca_h5ad(tmp_path / "test.h5ad")

    result = rename_cell_ids(
        str(path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )

    assert "error" not in result
    assert result["n_renamed"] == sum(1 for _, sample in HCA_TEST_ROWS if sample == "B1_0023")
    expected = [
        "MH_mix_BR1_" + cell_id[len("MH_mix_") :] if sample == "B1_0023" else cell_id
        for cell_id, sample in HCA_TEST_ROWS
    ]
    assert list(ad.read_h5ad(result["output_path"]).obs_names) == expected


def test_rename_refuses_cellxgene_through_wrapper(sample_h5ad):
    """The HCA-layout gate lives in the tools layer; this pins that the
    wrapper does not bypass it. Read-only, so the session fixture is safe."""
    result = rename_cell_ids(str(sample_h5ad), column="tissue", value="brain", prefix_from="cell_", prefix_to="c_")

    assert "error" in result
    assert "CellxGENE" in result["error"]
