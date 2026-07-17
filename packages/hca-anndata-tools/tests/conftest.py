"""Shared fixtures for hca-anndata-tools tests."""

from pathlib import Path

import anndata as ad
import pytest

from hca_anndata_tools.testing import create_cellxgene_h5ad, create_sample_h5ad


@pytest.fixture
def downgrade_cap_to_legacy():
    """Return a helper that rewrites a nested-CAP h5ad into the deprecated
    top-level layout in place: lifts every key out of ``uns['cap_metadata']``
    to the top level of ``uns`` and drops the wrapper. Used to build a
    legacy-layout file for the detection / refusal tests (the legacy layout is
    refused, not normalized).
    """

    def _downgrade(path: Path) -> Path:
        adata = ad.read_h5ad(path)
        cap = dict(adata.uns.pop("cap_metadata"))
        for key, value in cap.items():
            adata.uns[key] = value
        adata.write_h5ad(path)
        return path

    return _downgrade


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


@pytest.fixture
def cellxgene_h5ad(tmp_path) -> Path:
    """Create a CellxGENE-style h5ad file in a writable tmp dir."""
    path = tmp_path / "d394204c-dc6f-4c82-ae66-c6d00addbf43.h5ad"
    return create_cellxgene_h5ad(path)
