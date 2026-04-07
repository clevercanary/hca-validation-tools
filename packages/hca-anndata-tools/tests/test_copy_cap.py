"""Tests for copy_cap_annotations."""

import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp

from hca_anndata_tools.copy_cap import copy_cap_annotations
from hca_anndata_tools.write import EDIT_LOG_KEY


# --- Fixtures ---


def _make_cap_source(path: Path, cell_ids: list[str]) -> Path:
    """Create an h5ad with CAP annotations."""
    n = len(cell_ids)
    rng = np.random.default_rng(42)

    X = sp.random(n, 5, density=0.3, format="csr", dtype=np.float32, random_state=rng)

    labels = rng.choice(["typeA", "typeB"], n)
    obs = pd.DataFrame(
        {
            "author_cell_type": pd.Categorical(labels),
            "author_cell_type--cell_fullname": [f"{l} cell" for l in labels],
            "author_cell_type--cell_ontology_exists": [True] * n,
            "author_cell_type--cell_ontology_term_id": pd.Categorical(
                rng.choice(["CL:0000540", "CL:0000127"], n)
            ),
            "author_cell_type--cell_ontology_term": pd.Categorical(
                rng.choice(["neuron", "astrocyte"], n)
            ),
            "author_cell_type--rationale": ["morphology"] * n,
            "author_cell_type--marker_gene_evidence": pd.Categorical(
                rng.choice(["GFAP", "AIF1"], n)
            ),
            "author_cell_type--canonical_marker_genes": ["unknown"] * n,
            "author_cell_type--synonyms": ["unknown"] * n,
            "author_cell_type--category_fullname": ["neural cell"] * n,
            "author_cell_type--category_cell_ontology_term_id": ["CL:0002319"] * n,
            "author_cell_type--category_cell_ontology_term": ["neural cell"] * n,
            # cell_type enrichment columns
            "cell_type--cell_fullname": ["neuron"] * n,
            "cell_type--cell_ontology_exists": [True] * n,
            "cell_type--cell_ontology_term": ["neuron"] * n,
            # Demographic columns (should NOT be copied)
            "sex--cell_ontology_term_id": ["PATO:0000384"] * n,
            "development_stage--cell_ontology_term_id": ["HsapDv:0000087"] * n,
            "self_reported_ethnicity--cell_ontology_term_id": ["HANCESTRO:0005"] * n,
            "cell_type--cell_ontology_term_id": ["CL:0000540"] * n,
        },
        index=cell_ids,
    )

    var = pd.DataFrame(index=[f"GENE{i}" for i in range(5)])
    adata = ad.AnnData(X=X, obs=obs, var=var)

    adata.uns["title"] = "CAP Test Dataset"
    adata.uns["cellannotation_schema_version"] = "1.0.2"
    adata.uns["cellannotation_metadata"] = {
        "author_cell_type": {
            "algorithm_name": "NA",
            "algorithm_version": "NA",
            "algorithm_repo_url": "NA",
            "annotation_method": "manual",
            "description": "Test annotation set",
        }
    }
    adata.uns["authors_list"] = "Test Author"
    adata.uns["hierarchy"] = {"author_cell_type": 1}
    adata.uns["description"] = "A test CAP dataset"
    adata.uns["cap_dataset_url"] = "https://celltype.info/test"
    adata.uns["publication_timestamp"] = "2026-01-01"
    adata.uns["publication_version"] = "1.0"

    adata.write_h5ad(path)
    return path


def _make_hca_target(path: Path, cell_ids: list[str]) -> Path:
    """Create a minimal HCA-converted h5ad with same cells, no CAP columns."""
    n = len(cell_ids)
    rng = np.random.default_rng(7)

    X = sp.random(n, 5, density=0.3, format="csr", dtype=np.float32, random_state=rng)

    obs = pd.DataFrame(
        {
            "author_cell_type": pd.Categorical(rng.choice(["typeA", "typeB"], n)),
            "cell_type": pd.Categorical(rng.choice(["neuron", "astrocyte"], n)),
            "organism_ontology_term_id": pd.Categorical(["NCBITaxon:9606"] * n),
        },
        index=cell_ids,
    )

    var = pd.DataFrame(index=[f"GENE{i}" for i in range(5)])
    adata = ad.AnnData(X=X, obs=obs, var=var)
    adata.uns["title"] = "HCA Test Dataset"

    adata.write_h5ad(path)
    return path


CELL_IDS = [f"cell_{i}" for i in range(10)]


@pytest.fixture
def cap_source(tmp_path) -> Path:
    return _make_cap_source(tmp_path / "cap_source.h5ad", CELL_IDS)


@pytest.fixture
def hca_target(tmp_path) -> Path:
    return _make_hca_target(tmp_path / "hca-target.h5ad", CELL_IDS)


@pytest.fixture
def hca_target_with_cap(tmp_path) -> Path:
    """Target that already has CAP columns."""
    target = _make_hca_target(tmp_path / "hca-target-cap.h5ad", CELL_IDS)
    adata = ad.read_h5ad(target)
    adata.obs["existing--cell_ontology_term_id"] = "CL:0000000"
    adata.write_h5ad(target)
    return target


# --- Basic copy tests ---


def test_copy_basic(cap_source, hca_target):
    result = copy_cap_annotations(str(cap_source), str(hca_target))
    assert "error" not in result
    assert "output_path" in result
    assert "author_cell_type" in result["annotation_sets"]


def test_copy_obs_columns_present(cap_source, hca_target):
    result = copy_cap_annotations(str(cap_source), str(hca_target))
    written = ad.read_h5ad(result["output_path"])
    assert "author_cell_type--cell_ontology_term_id" in written.obs.columns
    assert "author_cell_type--marker_gene_evidence" in written.obs.columns
    assert "author_cell_type--rationale" in written.obs.columns
    assert "author_cell_type--category_fullname" in written.obs.columns


def test_copy_marker_gene_validation(cap_source, hca_target):
    result = copy_cap_annotations(str(cap_source), str(hca_target))
    assert "marker_gene_validation" in result
    mv = result["marker_gene_validation"]
    assert "total_unique_markers" in mv
    assert "found_in_var" in mv


def test_copy_cell_type_enrichment(cap_source, hca_target):
    result = copy_cap_annotations(str(cap_source), str(hca_target))
    written = ad.read_h5ad(result["output_path"])
    assert "cell_type--cell_fullname" in written.obs.columns
    assert "cell_type--cell_ontology_exists" in written.obs.columns
    assert "cell_type--cell_ontology_term" in written.obs.columns


def test_copy_uns_direct(cap_source, hca_target):
    result = copy_cap_annotations(str(cap_source), str(hca_target))
    written = ad.read_h5ad(result["output_path"])
    assert "cellannotation_schema_version" in written.uns
    assert "cellannotation_metadata" in written.uns
    assert "cap_dataset_url" in written.uns


def test_copy_uns_cap_keys(cap_source, hca_target):
    result = copy_cap_annotations(str(cap_source), str(hca_target))
    written = ad.read_h5ad(result["output_path"])
    assert "authors_list" in written.uns
    assert "hierarchy" in written.uns
    assert "description" in written.uns
    assert "publication_timestamp" in written.uns
    assert "publication_version" in written.uns


# --- Skip demographic columns ---


def test_copy_skips_demographic_columns(cap_source, hca_target):
    result = copy_cap_annotations(str(cap_source), str(hca_target))
    written = ad.read_h5ad(result["output_path"])
    assert "sex--cell_ontology_term_id" not in written.obs.columns
    assert "development_stage--cell_ontology_term_id" not in written.obs.columns
    assert "self_reported_ethnicity--cell_ontology_term_id" not in written.obs.columns


def test_copy_skips_cell_type_ontology_id(cap_source, hca_target):
    result = copy_cap_annotations(str(cap_source), str(hca_target))
    written = ad.read_h5ad(result["output_path"])
    assert "cell_type--cell_ontology_term_id" not in written.obs.columns


# --- Edit log ---


def test_copy_edit_log(cap_source, hca_target):
    result = copy_cap_annotations(str(cap_source), str(hca_target))
    written = ad.read_h5ad(result["output_path"])
    assert EDIT_LOG_KEY in written.uns
    log = json.loads(written.uns[EDIT_LOG_KEY])
    assert len(log) >= 1
    entry = log[-1]
    assert entry["operation"] == "import_cap_annotations"
    assert "author_cell_type" in entry["details"]["annotation_sets"]


# --- Failure cases ---


def test_copy_cell_mismatch_fails(cap_source, tmp_path):
    different_cells = _make_hca_target(
        tmp_path / "different.h5ad", [f"other_{i}" for i in range(10)]
    )
    result = copy_cap_annotations(str(cap_source), str(different_cells))
    assert "error" in result
    assert "mismatch" in result["error"].lower()


def test_copy_cell_count_mismatch_fails(cap_source, tmp_path):
    fewer_cells = _make_hca_target(
        tmp_path / "fewer.h5ad", [f"cell_{i}" for i in range(5)]
    )
    result = copy_cap_annotations(str(cap_source), str(fewer_cells))
    assert "error" in result
    assert "mismatch" in result["error"].lower()


def test_copy_no_cap_source_fails(hca_target, tmp_path):
    no_cap = _make_hca_target(tmp_path / "no_cap.h5ad", CELL_IDS)
    result = copy_cap_annotations(str(no_cap), str(hca_target))
    assert "error" in result
    assert "cellannotation_metadata" in result["error"]


def test_copy_target_has_cap_fails(cap_source, hca_target_with_cap):
    result = copy_cap_annotations(str(cap_source), str(hca_target_with_cap))
    assert "error" in result
    assert "overwrite" in result["error"].lower()


# --- Overwrite ---


def test_copy_overwrite(cap_source, hca_target_with_cap):
    result = copy_cap_annotations(
        str(cap_source), str(hca_target_with_cap), overwrite=True
    )
    assert "error" not in result
    written = ad.read_h5ad(result["output_path"])
    # Old CAP column removed
    assert "existing--cell_ontology_term_id" not in written.obs.columns
    # New CAP columns present
    assert "author_cell_type--cell_ontology_term_id" in written.obs.columns


# --- Index ordering ---


def test_copy_obs_index_reordered(cap_source, tmp_path):
    """Source and target have same cells in different order."""
    reversed_ids = list(reversed(CELL_IDS))
    target = _make_hca_target(tmp_path / "reversed.h5ad", reversed_ids)
    result = copy_cap_annotations(str(cap_source), str(target))
    assert "error" not in result

    written = ad.read_h5ad(result["output_path"])
    # Verify obs index is still in the target's order
    assert list(written.obs.index) == reversed_ids


def test_missing_file():
    result = copy_cap_annotations("/nonexistent/source.h5ad", "/nonexistent/target.h5ad")
    assert "error" in result
