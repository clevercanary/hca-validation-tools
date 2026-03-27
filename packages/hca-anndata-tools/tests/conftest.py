"""Shared fixtures for hca-anndata-tools tests."""

from pathlib import Path

import pytest

from hca_anndata_tools.testing import create_sample_h5ad


@pytest.fixture(scope="session")
def sample_h5ad(tmp_path_factory) -> Path:
    """Create a small but realistic h5ad file for testing."""
    path = tmp_path_factory.mktemp("data") / "test.h5ad"
    return create_sample_h5ad(path)


@pytest.fixture(scope="session")
def sample_dir(sample_h5ad) -> Path:
    """Return the directory containing the sample h5ad file."""
    return sample_h5ad.parent


@pytest.fixture
def sample_h5ad_for_write(tmp_path) -> Path:
    """Create a sample h5ad file in a writable tmp dir (function-scoped)."""
    path = tmp_path / "test-dataset.h5ad"
    return create_sample_h5ad(path)
