"""Verify each read-only tool returns results from the latest edit snapshot when one exists beside the given path."""

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
def original_path(tmp_path):
    """Write an original + a later timestamped edit; return the original path.

    The edit has different n_obs and obs marker so tools reading the wrong
    file will fail their assertions.
    """
    original = tmp_path / "dataset.h5ad"
    _make_file(original, n_obs=3, marker="original")
    edit = tmp_path / "dataset-edit-2026-04-17-06-00-00.h5ad"
    _make_file(edit, n_obs=7, marker="edit")
    return original


def test_get_summary_resolves_latest(original_path):
    assert get_summary(str(original_path))["n_obs"] == 7


def test_get_storage_info_resolves_latest(original_path):
    # CSR indptr length is n_obs + 1 — the shape field isn't surfaced directly.
    assert get_storage_info(str(original_path))["X"]["indptr"]["shape"] == [8]


def test_get_descriptive_stats_resolves_latest(original_path):
    result = get_descriptive_stats(str(original_path), columns=["kind"], value_counts=True)
    assert result["n_rows"] == 7
    assert result["columns"]["kind"]["value_counts"] == {"edit": 7}


def test_view_data_resolves_latest(original_path):
    values = view_data(str(original_path), attribute="obs", columns=["kind"], row_end=10)["data"]["kind"]
    assert len(values) == 7
    assert all(v == "edit" for v in values)


def test_get_cap_annotations_resolves_latest(original_path):
    result = get_cap_annotations(str(original_path))
    # title is in uns so the snapshot's uns was read.
    assert "title" in result["uns_metadata"]["required_present"]


def test_validate_marker_genes_resolves_latest(original_path):
    result = validate_marker_genes(str(original_path))
    # The snapshot has no organism_ontology_term_id, so the tool returns a
    # specific error from that file — confirming it read the snapshot rather
    # than blowing up earlier on path resolution.
    assert result.get("error") == "organism_ontology_term_id not found in obs columns"
