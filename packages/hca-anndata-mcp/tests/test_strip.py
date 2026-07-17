"""Unit tests for the strip_forbidden_obs_columns MCP wrapper."""

import anndata as ad
import pandas as pd

from hca_anndata_mcp.tools.strip import strip_forbidden_obs_columns


def test_strip_missing_file():
    result = strip_forbidden_obs_columns("/nonexistent/file.h5ad")
    assert "error" in result
    assert "File not found" in result["error"]


def test_strip_no_op_on_clean_sample(tmp_path):
    """Sample h5ad has no SRE columns → wrapper surfaces the skipped
    sentinel from the underlying tool."""
    from hca_anndata_tools.testing import create_sample_h5ad

    path = tmp_path / "test.h5ad"
    create_sample_h5ad(path)
    # Drop schema_version so the file models HCA-layout (the fixture sets
    # it for legacy reasons; the strip tool would otherwise refuse).
    adata = ad.read_h5ad(path)
    adata.uns.pop("schema_version", None)
    adata.write_h5ad(path)

    result = strip_forbidden_obs_columns(str(path))
    assert result.get("skipped") is True
    assert "reason" in result


def test_strip_actually_strips(tmp_path):
    """Integration test: SRE column present → wrapper returns
    output_path + obs_columns_stripped, and reading the output confirms
    the column is gone."""
    from hca_anndata_tools.testing import create_sample_h5ad

    path = tmp_path / "test.h5ad"
    create_sample_h5ad(path)
    adata = ad.read_h5ad(path)
    adata.uns.pop("schema_version", None)
    adata.obs["self_reported_ethnicity_ontology_term_id"] = pd.Categorical(["unknown"] * adata.n_obs)
    adata.write_h5ad(path)

    result = strip_forbidden_obs_columns(str(path))
    assert "error" not in result
    assert result["obs_columns_stripped"] == ["self_reported_ethnicity_ontology_term_id"]

    written = ad.read_h5ad(result["output_path"])
    assert "self_reported_ethnicity_ontology_term_id" not in written.obs.columns


def test_strip_refuses_cellxgene_layout(tmp_path):
    """Wrapper surfaces the CellxGENE-layout refusal verbatim — important
    that the user sees the redirect to convert_cellxgene_to_hca."""
    from hca_anndata_tools.testing import create_cellxgene_h5ad

    path = tmp_path / "cxg.h5ad"
    create_cellxgene_h5ad(path)

    result = strip_forbidden_obs_columns(str(path))
    assert "error" in result
    assert "CellxGENE-layout" in result["error"]
    assert "convert_cellxgene_to_hca" in result["error"]
