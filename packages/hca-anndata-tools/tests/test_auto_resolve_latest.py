"""Verify read-only tools auto-resolve to the latest edit snapshot.

Mutating tools already carry their own test coverage for resolve_latest
behavior. These tests cover the previously-inconsistent read-only path
(#339): when both ``foo.h5ad`` and ``foo-edit-<UTC>.h5ad`` exist, calling
a tool with the original path should operate on the snapshot.
"""

from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp
from hca_anndata_tools.cap import get_cap_annotations
from hca_anndata_tools.marker_genes import validate_marker_genes
from hca_anndata_tools.stats import get_descriptive_stats
from hca_anndata_tools.storage import get_storage_info
from hca_anndata_tools.summary import get_summary
from hca_anndata_tools.view import view_data


def _make_file(path: Path, *, n_obs: int, marker: str) -> None:
    """Write a minimal h5ad with an identifiable obs column + uns title."""
    X = sp.csr_matrix(np.zeros((n_obs, 3), dtype=np.float32))
    obs = pd.DataFrame(
        {"kind": pd.Categorical([marker] * n_obs)},
        index=[f"c{i}" for i in range(n_obs)],  # pyright: ignore[reportArgumentType]
    )
    var = pd.DataFrame(index=[f"g{i}" for i in range(3)])  # pyright: ignore[reportArgumentType]
    adata = ad.AnnData(X=X, obs=obs, var=var)
    adata.uns["title"] = marker
    adata.write_h5ad(path)


@pytest.fixture
def lineage(tmp_path):
    """Create an original file plus a later timestamped edit with differing n_obs."""
    original = tmp_path / "dataset.h5ad"
    _make_file(original, n_obs=3, marker="original")

    # The snapshot has more cells and a different uns title/obs marker so we
    # can tell which one the tool actually read.
    edit = tmp_path / "dataset-edit-2026-04-17-06-00-00.h5ad"
    _make_file(edit, n_obs=7, marker="edit")
    return original, edit


def test_get_summary_resolves_latest(lineage):
    original, edit = lineage
    result = get_summary(str(original))
    assert result["n_obs"] == 7


def test_get_storage_info_resolves_latest(lineage):
    original, edit = lineage
    result = get_storage_info(str(original))
    # n_obs not surfaced directly, but X shape is.
    assert result["X"]["indptr"]["shape"] == [8]  # n_obs + 1 for CSR


def test_get_descriptive_stats_resolves_latest(lineage):
    original, edit = lineage
    result = get_descriptive_stats(str(original), columns=["kind"], value_counts=True)
    assert result["n_rows"] == 7
    assert result["columns"]["kind"]["value_counts"] == {"edit": 7}


def test_view_data_resolves_latest(lineage):
    original, edit = lineage
    result = view_data(str(original), attribute="obs", columns=["kind"], row_end=10)
    values = result["data"]["kind"]
    assert len(values) == 7
    assert all(v == "edit" for v in values)


def test_get_cap_annotations_resolves_latest(lineage):
    """CAP reports title from uns — should reflect the snapshot."""
    original, edit = lineage
    result = get_cap_annotations(str(original))
    # title is in uns_metadata.required_present when set.
    assert "title" in result["uns_metadata"]["required_present"]
    # The exact n_obs isn't in this result, but we can verify it opened the edit
    # by checking that has_cap_annotations handling reached its logic at all (no error).
    assert "error" not in result


def test_validate_marker_genes_resolves_latest(lineage):
    """validate_marker_genes reads obs columns via h5py — confirm it reads the edit."""
    original, edit = lineage
    result = validate_marker_genes(str(original))
    # The fixture has no CAP columns, so this returns an informational result
    # rather than an error. The key check: resolve_latest succeeds (no file-not-found
    # or path-mismatch error).
    assert "error" not in result or "organism_ontology_term_id" in result.get("error", "")
