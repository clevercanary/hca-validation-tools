"""Tests for CAP marker gene validation."""

from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp

from hca_anndata_tools._gencode import load_gencode_reference
from hca_anndata_tools.marker_genes import (
    _extract_marker_genes,
    _get_gene_names_from_var,
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
    series = pd.Series(["GFAP", "AIF1", "GFAP", "RBFOX3"])
    assert _extract_marker_genes(series) == {"GFAP", "AIF1", "RBFOX3"}


def test_extract_markers_comma_separated():
    series = pd.Series(["GFAP, AIF1", "RBFOX3"])
    assert _extract_marker_genes(series) == {"GFAP", "AIF1", "RBFOX3"}


def test_extract_markers_skips_unknown():
    series = pd.Series(["GFAP", "unknown", "", None, "NA", "RBFOX3"])
    assert _extract_marker_genes(series) == {"GFAP", "RBFOX3"}


def test_extract_markers_strips_whitespace():
    series = pd.Series(["  GFAP  ", "AIF1 , RBFOX3 "])
    assert _extract_marker_genes(series) == {"GFAP", "AIF1", "RBFOX3"}


def test_extract_markers_empty_series():
    series = pd.Series([], dtype=object)
    assert _extract_marker_genes(series) == set()


# -- Var gene name detection tests ---------------------------------------------


def test_get_gene_names_feature_name():
    var = pd.DataFrame(
        {"feature_name": ["GFAP", "AIF1"]},
        index=["ENSG00000131095", "ENSG00000204472"],
    )
    names, eid_map = _get_gene_names_from_var(var)
    assert names == {"GFAP", "AIF1"}
    assert eid_map["ENSG00000131095"] == "GFAP"


def test_get_gene_names_gene_name_col():
    var = pd.DataFrame(
        {"gene_name": ["GFAP", "AIF1"]},
        index=["ENSG00000131095", "ENSG00000204472"],
    )
    names, eid_map = _get_gene_names_from_var(var)
    assert names == {"GFAP", "AIF1"}


def test_get_gene_names_fallback():
    var = pd.DataFrame(index=["GFAP", "AIF1"])
    names, eid_map = _get_gene_names_from_var(var)
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
    typos = result["probable_typos"]
    assert any(t["marker_gene"] == "SCL25A5" for t in typos)


def test_all_markers_found(clean_h5ad):
    result = validate_marker_genes(str(clean_h5ad))
    assert result["missing"] == 0
    assert result["found_in_var"] == result["total_unique_markers"]


def test_no_cap_annotations(sample_h5ad):
    result = validate_marker_genes(str(sample_h5ad))
    assert result["annotation_sets_with_markers"] == []
    assert result["total_unique_markers"] == 0


def test_specific_annotation_set(marker_h5ad):
    result = validate_marker_genes(str(marker_h5ad), annotation_set="test_labels")
    assert "test_labels" in result["annotation_sets_with_markers"]


def test_invalid_annotation_set(marker_h5ad):
    result = validate_marker_genes(str(marker_h5ad), annotation_set="nonexistent")
    assert "error" in result


def test_missing_file():
    result = validate_marker_genes("/nonexistent/file.h5ad")
    assert "error" in result


def test_details_per_set(marker_h5ad):
    result = validate_marker_genes(str(marker_h5ad))
    assert "test_labels" in result["details"]
    detail = result["details"]["test_labels"]
    assert "unique_markers" in detail
    assert "found" in detail
    assert "known_renames" in detail
    assert "probable_typos" in detail
