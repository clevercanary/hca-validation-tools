"""Unit tests for the validate_schema MCP wrapper."""

import anndata as ad
from hca_anndata_mcp.tools.validate import validate_schema
from hca_anndata_tools.testing import create_sample_h5ad
from hca_schema_validator.testing import create_labelable_h5ad


def test_validate_schema_shape(sample_h5ad):
    result = validate_schema(str(sample_h5ad))
    assert set(result.keys()) == {
        "filename", "is_valid", "error_count", "warning_count", "errors", "warnings",
    }
    assert isinstance(result["is_valid"], bool)
    assert result["error_count"] == len(result["errors"])
    assert result["warning_count"] == len(result["warnings"])


def test_validate_schema_missing_file():
    result = validate_schema("/nonexistent/file.h5ad")
    assert "error" in result


def test_validate_schema_surfaces_cosmetic_check(tmp_path):
    """Confirm the new producer-cosmetic-column check (issue #377) surfaces
    through the MCP wrapper. The wrapper just returns the validator's
    warnings/errors, so this test exercises the integration boundary
    rather than re-testing the underlying logic.
    """
    path = create_labelable_h5ad(tmp_path / "cosmetic.h5ad")
    adata = ad.read_h5ad(path)
    adata.obs["tissue"] = "WRONG_TISSUE_LABEL"
    adata.write_h5ad(path)

    result = validate_schema(str(path))

    assert any(
        "obs['tissue']" in w and "should not be populated by producers" in w
        for w in result["warnings"]
    ), result["warnings"]
    assert any(
        "'WRONG_TISSUE_LABEL'" in e and "Either delete the cosmetic column" in e
        for e in result["errors"]
    ), result["errors"]
    assert result["is_valid"] is False


def test_validate_schema_resolves_latest(tmp_path):
    """Confirm the wrapper validates the snapshot's bytes, not just echoes its
    filename. Strip ``uns['title']`` from the snapshot so it produces a distinct
    error the original lacks, then verify the lineage call's output matches the
    snapshot's direct validation result."""
    original = tmp_path / "dataset.h5ad"
    create_sample_h5ad(original)

    # Capture the original's baseline before any snapshot exists in the
    # directory — otherwise resolve_latest would pick the snapshot when we
    # ask about the original path.
    direct_original = validate_schema(str(original))

    snapshot = tmp_path / "dataset-edit-2026-04-17-06-00-00.h5ad"
    create_sample_h5ad(snapshot)
    adata = ad.read_h5ad(snapshot)
    del adata.uns["title"]
    adata.write_h5ad(snapshot)

    direct_snapshot = validate_schema(str(snapshot))
    via_lineage = validate_schema(str(original))  # resolve_latest picks the snapshot

    assert direct_original["errors"] != direct_snapshot["errors"]  # discriminator works
    assert via_lineage == direct_snapshot
