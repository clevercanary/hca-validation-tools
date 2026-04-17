"""Unit tests for the validate_schema MCP wrapper."""

from pathlib import Path

from hca_anndata_mcp.tools.validate import validate_schema
from hca_anndata_tools.testing import create_sample_h5ad


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


def test_validate_schema_resolves_latest(tmp_path):
    """When an edit snapshot exists, the wrapper must validate the snapshot."""
    original = tmp_path / "dataset.h5ad"
    create_sample_h5ad(original)

    # Write a later snapshot that differs from the original.
    snapshot = tmp_path / "dataset-edit-2026-04-17-06-00-00.h5ad"
    create_sample_h5ad(snapshot)

    original_result = validate_schema(str(original))
    assert "error" not in original_result
    assert Path(snapshot).name == original_result["filename"]
