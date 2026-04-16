"""Tests for CAP marker gene validation."""

from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp
from hca_anndata_tools._gencode import load_gencode_reference
from hca_anndata_tools._io import read_var_gene_names
from hca_anndata_tools.marker_genes import (
    _extract_marker_genes_from_categories,
    validate_marker_genes,
)

# -- GENCODE reference loader tests --------------------------------------------


def test_load_gencode_reference():
    id_to_name, name_to_ids = load_gencode_reference()
    assert len(id_to_name) > 70000
    assert "ENSG00000173947" in id_to_name
    assert id_to_name["ENSG00000173947"] == "CIMAP3"
    assert "CIMAP3" in name_to_ids


def test_gencode_reference_cached():
    result1 = load_gencode_reference()
    result2 = load_gencode_reference()
    assert result1 is result2


def test_gencode_duplicate_names():
    """Some gene names map to multiple Ensembl IDs."""
    _, name_to_ids = load_gencode_reference()
    assert len(name_to_ids["WASH7P"]) >= 2


# -- Marker gene extraction tests ---------------------------------------------


def test_extract_markers_simple():
    categories = {"GFAP", "AIF1", "RBFOX3"}
    assert _extract_marker_genes_from_categories(categories) == {"GFAP", "AIF1", "RBFOX3"}


def test_extract_markers_comma_separated():
    categories = {"GFAP, AIF1", "RBFOX3"}
    assert _extract_marker_genes_from_categories(categories) == {"GFAP", "AIF1", "RBFOX3"}


def test_extract_markers_skips_unknown():
    categories = {"GFAP", "unknown", "", "NA", "RBFOX3"}
    assert _extract_marker_genes_from_categories(categories) == {"GFAP", "RBFOX3"}


def test_extract_markers_strips_whitespace():
    categories = {"  GFAP  ", "AIF1 , RBFOX3 "}
    assert _extract_marker_genes_from_categories(categories) == {"GFAP", "AIF1", "RBFOX3"}


def test_extract_markers_empty():
    assert _extract_marker_genes_from_categories(set()) == set()


# -- Var gene name detection tests ---------------------------------------------


def test_read_var_gene_names_feature_name(tmp_path):
    var = pd.DataFrame(
        {"feature_name": ["GFAP", "AIF1"]},
        index=["ENSG00000131095", "ENSG00000204472"],
    )
    X = sp.random(2, 2, density=0.5, format="csr", dtype=np.float32)
    adata = ad.AnnData(X=X, var=var, obs=pd.DataFrame(index=["c0", "c1"]))
    path = tmp_path / "feat.h5ad"
    adata.write_h5ad(path)
    names, eid_map = read_var_gene_names(str(path))
    assert names == {"GFAP", "AIF1"}
    assert eid_map["ENSG00000131095"] == "GFAP"


def test_read_var_gene_names_gene_name_col(tmp_path):
    var = pd.DataFrame(
        {"gene_name": ["GFAP", "AIF1"]},
        index=["ENSG00000131095", "ENSG00000204472"],
    )
    X = sp.random(2, 2, density=0.5, format="csr", dtype=np.float32)
    adata = ad.AnnData(X=X, var=var, obs=pd.DataFrame(index=["c0", "c1"]))
    path = tmp_path / "gene.h5ad"
    adata.write_h5ad(path)
    names, eid_map = read_var_gene_names(str(path))
    assert names == {"GFAP", "AIF1"}


def test_read_var_gene_names_fallback(tmp_path):
    var = pd.DataFrame(index=["GFAP", "AIF1"])
    X = sp.random(2, 2, density=0.5, format="csr", dtype=np.float32)
    adata = ad.AnnData(X=X, var=var, obs=pd.DataFrame(index=["c0", "c1"]))
    path = tmp_path / "fallback.h5ad"
    adata.write_h5ad(path)
    names, eid_map = read_var_gene_names(str(path))
    assert names == {"GFAP", "AIF1"}
    assert eid_map == {}


# -- Full validation tests with fixtures ---------------------------------------


@pytest.fixture(scope="module")
def marker_h5ad(tmp_path_factory) -> Path:
    """h5ad with CAP markers: some found, one rename, one typo."""
    n_obs = 12
    rng = np.random.default_rng(42)

    # Use real Ensembl IDs so rename detection works
    var_index = ["ENSG00000131095", "ENSG00000204472", "ENSG00000167281", "ENSG00000173947"]
    var_names = ["GFAP", "AIF1", "RBFOX3", "PIFO"]  # PIFO is old name for CIMAP3

    X = sp.random(n_obs, len(var_index), density=0.3, format="csr", dtype=np.float32, random_state=rng)

    obs = pd.DataFrame(
        {
            "organism_ontology_term_id": pd.Categorical(["NCBITaxon:9606"] * n_obs),
            "test_labels": pd.Categorical(rng.choice(["typeA", "typeB", "typeC"], n_obs)),
            "test_labels--marker_gene_evidence": pd.Categorical(
                rng.choice(["GFAP,AIF1", "RBFOX3", "CIMAP3", "SCL25A5"], n_obs)
            ),
            "test_labels--cell_ontology_term_id": pd.Categorical(
                rng.choice(["CL:0000540", "CL:0000127"], n_obs)
            ),
        },
        index=[f"cell_{i}" for i in range(n_obs)],
    )

    var = pd.DataFrame(
        {"feature_name": pd.Categorical(var_names)},
        index=var_index,
    )

    adata = ad.AnnData(X=X, obs=obs, var=var)
    path = tmp_path_factory.mktemp("marker") / "marker_test.h5ad"
    adata.write_h5ad(path)
    return path


@pytest.fixture(scope="module")
def clean_h5ad(tmp_path_factory) -> Path:
    """h5ad with CAP markers where all genes are found in var."""
    n_obs = 6
    rng = np.random.default_rng(7)

    var_index = ["ENSG00000131095", "ENSG00000204472", "ENSG00000167281"]
    var_names = ["GFAP", "AIF1", "RBFOX3"]

    X = sp.random(n_obs, len(var_index), density=0.3, format="csr", dtype=np.float32, random_state=rng)

    obs = pd.DataFrame(
        {
            "organism_ontology_term_id": pd.Categorical(["NCBITaxon:9606"] * n_obs),
            "ann": pd.Categorical(rng.choice(["a", "b"], n_obs)),
            "ann--marker_gene_evidence": pd.Categorical(
                rng.choice(["GFAP", "AIF1,RBFOX3"], n_obs)
            ),
        },
        index=[f"cell_{i}" for i in range(n_obs)],
    )

    var = pd.DataFrame(
        {"feature_name": pd.Categorical(var_names)},
        index=var_index,
    )

    adata = ad.AnnData(X=X, obs=obs, var=var)
    path = tmp_path_factory.mktemp("clean") / "clean_test.h5ad"
    adata.write_h5ad(path)
    return path


def test_rename_detected(marker_h5ad):
    result = validate_marker_genes(str(marker_h5ad))
    assert result["missing"] >= 1
    renames = result["known_renames"]
    assert any(r["marker_gene"] == "CIMAP3" and r["var_name"] == "PIFO" for r in renames)


def test_typo_detected(marker_h5ad):
    result = validate_marker_genes(str(marker_h5ad))
    typos = result["not_in_gencode"]
    assert any(t["marker_gene"] == "SCL25A5" for t in typos)


def test_missing_from_var_key_present(marker_h5ad):
    result = validate_marker_genes(str(marker_h5ad))
    assert "missing_from_var" in result


def test_all_markers_found(clean_h5ad):
    result = validate_marker_genes(str(clean_h5ad))
    assert result["missing"] == 0
    assert result["found_in_var"] == result["total_unique_markers"]


def test_no_cap_annotations(tmp_path):
    """File with organism but no CAP annotation columns."""
    n_obs = 4
    X = sp.random(n_obs, 2, density=0.5, format="csr", dtype=np.float32)
    obs = pd.DataFrame(
        {"organism_ontology_term_id": pd.Categorical(["NCBITaxon:9606"] * n_obs)},
        index=[f"c{i}" for i in range(n_obs)],
    )
    var = pd.DataFrame({"feature_name": ["A", "B"]}, index=["ENSG1", "ENSG2"])
    adata = ad.AnnData(X=X, obs=obs, var=var)
    path = tmp_path / "no_cap.h5ad"
    adata.write_h5ad(path)
    result = validate_marker_genes(str(path))
    assert result["annotation_sets_with_markers"] == []
    assert result["total_unique_markers"] == 0


def test_missing_organism(sample_h5ad):
    """File without organism_ontology_term_id in obs is rejected."""
    result = validate_marker_genes(str(sample_h5ad))
    assert "error" in result
    assert "organism_ontology_term_id" in result["error"]


def test_specific_annotation_set(marker_h5ad):
    result = validate_marker_genes(str(marker_h5ad), annotation_set="test_labels")
    assert "test_labels" in result["annotation_sets_with_markers"]


def test_invalid_annotation_set(marker_h5ad):
    result = validate_marker_genes(str(marker_h5ad), annotation_set="nonexistent")
    assert "error" in result


def test_missing_file():
    result = validate_marker_genes("/nonexistent/file.h5ad")
    assert "error" in result


@pytest.fixture(scope="module")
def versioned_h5ad(tmp_path_factory) -> Path:
    """h5ad with versioned Ensembl IDs in var.index (e.g., ENSG*.7)."""
    n_obs = 6
    rng = np.random.default_rng(11)

    var_index = ["ENSG00000131095.12", "ENSG00000204472.3", "ENSG00000173947.7"]
    var_names = ["GFAP", "AIF1", "PIFO"]

    X = sp.random(n_obs, len(var_index), density=0.3, format="csr", dtype=np.float32, random_state=rng)

    obs = pd.DataFrame(
        {
            "organism_ontology_term_id": pd.Categorical(["NCBITaxon:9606"] * n_obs),
            "ann": pd.Categorical(rng.choice(["a", "b"], n_obs)),
            "ann--marker_gene_evidence": pd.Categorical(
                rng.choice(["GFAP", "CIMAP3"], n_obs)
            ),
        },
        index=[f"cell_{i}" for i in range(n_obs)],
    )

    var = pd.DataFrame(
        {"feature_name": pd.Categorical(var_names)},
        index=var_index,
    )

    adata = ad.AnnData(X=X, obs=obs, var=var)
    path = tmp_path_factory.mktemp("versioned") / "versioned_test.h5ad"
    adata.write_h5ad(path)
    return path


def test_rename_detected_with_versioned_ids(versioned_h5ad):
    """Rename detection works when var.index has versioned Ensembl IDs."""
    result = validate_marker_genes(str(versioned_h5ad))
    renames = result["known_renames"]
    assert any(r["marker_gene"] == "CIMAP3" and r["var_name"] == "PIFO" for r in renames)


def test_details_per_set(marker_h5ad):
    result = validate_marker_genes(str(marker_h5ad))
    assert "test_labels" in result["details"]
    detail = result["details"]["test_labels"]
    assert "unique_markers" in detail
    assert "found" in detail
    assert "known_renames" in detail
    assert "not_in_gencode" in detail
