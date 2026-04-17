"""Verify each read-only tool returns results from the latest edit snapshot when one exists beside the given path."""

from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp
from hca_anndata_tools.cap import get_cap_annotations
from hca_anndata_tools.marker_genes import validate_marker_genes
from hca_anndata_tools.plot import plot_embedding
from hca_anndata_tools.stats import get_descriptive_stats
from hca_anndata_tools.storage import get_storage_info
from hca_anndata_tools.summary import get_summary
from hca_anndata_tools.view import view_data


def _make_file(path: Path, *, n_obs: int, marker: str, edit_only: bool) -> None:
    obs_data = {"kind": pd.Categorical([marker] * n_obs)}
    if edit_only:
        # Added only to the snapshot so tools that observe these signals fail
        # assertions when they accidentally read the original file.
        obs_data["organism_ontology_term_id"] = pd.Categorical(["NCBITaxon:9606"] * n_obs)
    obs = pd.DataFrame(
        obs_data,
        index=[f"c{i}" for i in range(n_obs)],  # pyright: ignore[reportArgumentType]
    )
    var = pd.DataFrame(index=[f"g{i}" for i in range(3)])  # pyright: ignore[reportArgumentType]
    adata = ad.AnnData(
        X=sp.csr_matrix(np.zeros((n_obs, 3), dtype=np.float32)),
        obs=obs,
        var=var,
    )
    adata.uns["title"] = marker
    if edit_only:
        adata.uns["cellannotation_schema_version"] = "1.0.0"
        adata.obsm["X_umap"] = np.random.default_rng(0).normal(size=(n_obs, 2)).astype(np.float32)
    adata.write_h5ad(path)


@pytest.fixture
def original_path(tmp_path):
    """Write an original + a later timestamped edit; return the original path.

    The edit has different n_obs, obs marker, extra uns keys, and extra obs
    columns so every tool's output differs based on which file it reads.
    """
    original = tmp_path / "dataset.h5ad"
    _make_file(original, n_obs=3, marker="original", edit_only=False)
    edit = tmp_path / "dataset-edit-2026-04-17-06-00-00.h5ad"
    _make_file(edit, n_obs=7, marker="edit", edit_only=True)
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
    # cellannotation_schema_version is set only on the snapshot.
    result = get_cap_annotations(str(original_path))
    assert "cellannotation_schema_version" in result["uns_metadata"]["required_present"]


def test_plot_embedding_resolves_latest(original_path):
    # obsm['X_umap'] exists only on the snapshot — asking for it on the original
    # would error "embedding not found". A successful PNG result therefore
    # proves the snapshot was read.
    result = plot_embedding(str(original_path), color="kind", embedding="X_umap")
    assert "error" not in result
    assert result["mime_type"] == "image/png"


def test_validate_marker_genes_resolves_latest(original_path):
    # The snapshot adds organism_ontology_term_id = NCBITaxon:9606; the original
    # lacks it entirely. Reading the original returns the "missing column" error;
    # reading the snapshot passes the organism gate and falls through to the
    # no-marker-sets branch.
    result = validate_marker_genes(str(original_path))
    assert "error" not in result
    assert result["annotation_sets_with_markers"] == []
