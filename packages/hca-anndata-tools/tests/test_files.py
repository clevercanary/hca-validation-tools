"""Tests for the locate_files function."""

from hca_anndata_tools.files import locate_files


def test_locate_finds_h5ad(sample_dir):
    result = locate_files(str(sample_dir))
    assert result["total"] == 1
    assert len(result["h5ad"]) == 1
    assert result["h5ad"][0].endswith(".h5ad")


def test_locate_bad_directory():
    result = locate_files("/nonexistent/path")
    assert "error" in result


def test_locate_empty_directory(tmp_path):
    result = locate_files(str(tmp_path))
    assert result["total"] == 0
    assert result["h5ad"] == []
