"""Tests for the plot_embedding function."""

import base64

from hca_anndata_tools.plot import plot_embedding


def test_plot_returns_png(sample_h5ad):
    result = plot_embedding(
        str(sample_h5ad),
        color="cell_type",
        embedding="X_umap",
    )
    assert "error" not in result
    assert result["mime_type"] == "image/png"
    # Verify data is valid base64
    raw = base64.standard_b64decode(result["data"])
    # PNG magic bytes
    assert raw[:4] == b"\x89PNG"


def test_plot_with_pca(sample_h5ad):
    result = plot_embedding(
        str(sample_h5ad),
        color="tissue",
        embedding="X_pca",
    )
    assert "error" not in result
    assert result["mime_type"] == "image/png"


def test_plot_custom_title(sample_h5ad):
    result = plot_embedding(
        str(sample_h5ad),
        color="sex",
        embedding="X_umap",
        title="Custom Title",
    )
    assert "error" not in result


def test_plot_missing_embedding(sample_h5ad):
    result = plot_embedding(
        str(sample_h5ad),
        color="cell_type",
        embedding="X_nonexistent",
    )
    assert "error" in result


def test_plot_missing_color(sample_h5ad):
    result = plot_embedding(
        str(sample_h5ad),
        color="nonexistent_column",
        embedding="X_umap",
    )
    assert "error" in result


def test_plot_missing_file():
    result = plot_embedding("/nonexistent/file.h5ad")
    assert "error" in result
