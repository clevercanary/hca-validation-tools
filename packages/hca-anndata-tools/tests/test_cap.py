"""Tests for the get_cap_annotations function and _make_serializable helper."""

from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp

from hca_anndata_tools.cap import get_cap_annotations, _make_serializable


# -- _make_serializable tests --------------------------------------------------

def test_serializable_int():
    assert _make_serializable(np.int64(42)) == 42
    assert isinstance(_make_serializable(np.int64(42)), int)


def test_serializable_float():
    assert _make_serializable(np.float32(3.14)) == pytest.approx(3.14, rel=1e-5)
    assert isinstance(_make_serializable(np.float32(3.14)), float)


def test_serializable_bool():
    assert _make_serializable(np.bool_(True)) is True
    assert isinstance(_make_serializable(np.bool_(False)), bool)


def test_serializable_str():
    assert _make_serializable(np.str_("hello")) == "hello"
    assert isinstance(_make_serializable(np.str_("hello")), str)


def test_serializable_bytes():
    assert isinstance(_make_serializable(np.bytes_(b"data")), str)


def test_serializable_ndarray():
    result = _make_serializable(np.array([1, 2, 3]))
    assert result == [1, 2, 3]
    assert isinstance(result, list)


def test_serializable_nested_dict():
    result = _make_serializable({"a": np.int64(1), "b": {"c": np.float32(2.0)}})
    assert result == {"a": 1, "b": {"c": pytest.approx(2.0)}}
    assert isinstance(result["a"], int)
    assert isinstance(result["b"]["c"], float)


def test_serializable_list():
    result = _make_serializable([np.int64(1), np.float32(2.0), "plain"])
    assert result == [1, pytest.approx(2.0), "plain"]


def test_serializable_passthrough():
    assert _make_serializable("hello") == "hello"
    assert _make_serializable(42) == 42
    assert _make_serializable(None) is None


# -- get_cap_annotations tests -------------------------------------------------

def test_cap_no_annotations(sample_h5ad):
    """Sample file has no CAP annotations."""
    result = get_cap_annotations(str(sample_h5ad))
    assert "error" not in result
    assert result["has_cap_annotations"] is False
    assert result["annotation_sets"] == []


def test_cap_uns_metadata_missing(sample_h5ad):
    """Sample file is missing all required CAP uns keys."""
    result = get_cap_annotations(str(sample_h5ad))
    missing = result["uns_metadata"]["required_missing"]
    assert "cellannotation_schema_version" in missing
    assert "cellannotation_metadata" in missing


def test_cap_missing_file():
    result = get_cap_annotations("/nonexistent/file.h5ad")
    assert "error" in result


def test_cap_nonexistent_annotation_set(sample_h5ad):
    """Requesting a nonexistent set on a non-CAP file returns an error."""
    result = get_cap_annotations(str(sample_h5ad), annotation_set="nonexistent")
    assert "error" in result
    assert "nonexistent" in result["error"]


# -- Tests with a CAP-annotated fixture ----------------------------------------

@pytest.fixture(scope="module")
def cap_h5ad(tmp_path_factory) -> Path:
    """Create an h5ad with CAP-style annotation columns."""
    n_obs = 20
    rng = np.random.default_rng(99)

    X = sp.random(n_obs, 5, density=0.3, format="csr", dtype=np.float32, random_state=rng)

    labels = rng.choice(["neuron", "astrocyte", "microglia"], n_obs)
    obs = pd.DataFrame(
        {
            "my_labels": pd.Categorical(labels),
            "my_labels--cell_fullname": [f"{l} cell" for l in labels],
            "my_labels--cell_ontology_exists": rng.choice([True, False], n_obs),
            "my_labels--cell_ontology_term_id": rng.choice(
                ["CL:0000540", "CL:0000127", "CL:0000129"], n_obs
            ),
            "my_labels--cell_ontology_term": rng.choice(
                ["neuron", "astrocyte", "microglial cell"], n_obs
            ),
            "my_labels--rationale": ["morphology"] * n_obs,
            "my_labels--marker_gene_evidence": rng.choice(
                ["RBFOX3", "GFAP", "AIF1"], n_obs
            ),
        },
        index=[f"cell_{i}" for i in range(n_obs)],
    )

    var = pd.DataFrame(index=[f"GENE{i}" for i in range(5)])

    adata = ad.AnnData(X=X, obs=obs, var=var)
    adata.uns["title"] = "CAP Test"
    adata.uns["cellannotation_schema_version"] = "0.2.0"
    adata.uns["cellannotation_metadata"] = {
        "author": "test",
        "count": np.int64(42),
    }

    path = tmp_path_factory.mktemp("cap") / "cap_test.h5ad"
    adata.write_h5ad(path)
    return path


def test_cap_detects_annotation_set(cap_h5ad):
    result = get_cap_annotations(str(cap_h5ad))
    assert result["has_cap_annotations"] is True
    assert "my_labels" in result["annotation_sets"]


def test_cap_reports_required_columns(cap_h5ad):
    result = get_cap_annotations(str(cap_h5ad), annotation_set="my_labels")
    detail = result["set_details"]["my_labels"]
    assert "my_labels" in detail["required_columns_present"]
    assert "my_labels--cell_ontology_term_id" in detail["required_columns_present"]


def test_cap_reports_cell_labels(cap_h5ad):
    result = get_cap_annotations(str(cap_h5ad), annotation_set="my_labels")
    detail = result["set_details"]["my_labels"]
    assert "cell_labels" in detail
    assert sum(detail["cell_labels"].values()) == 20


def test_cap_reports_ontology_terms(cap_h5ad):
    result = get_cap_annotations(str(cap_h5ad), annotation_set="my_labels")
    detail = result["set_details"]["my_labels"]
    assert "ontology_terms" in detail
    assert any("CL:" in t for t in detail["ontology_terms"])


def test_cap_reports_marker_genes(cap_h5ad):
    result = get_cap_annotations(str(cap_h5ad), annotation_set="my_labels")
    detail = result["set_details"]["my_labels"]
    assert "marker_genes" in detail


def test_cap_serializes_uns_metadata(cap_h5ad):
    result = get_cap_annotations(str(cap_h5ad))
    meta = result["cellannotation_metadata"]
    assert meta["author"] == "test"
    # np.int64 should have been serialized to int
    assert meta["count"] == 42
    assert isinstance(meta["count"], int)


def test_cap_uns_required_present(cap_h5ad):
    result = get_cap_annotations(str(cap_h5ad))
    present = result["uns_metadata"]["required_present"]
    assert "title" in present
    assert "cellannotation_metadata" in present


def test_cap_bad_annotation_set(cap_h5ad):
    result = get_cap_annotations(str(cap_h5ad), annotation_set="nonexistent")
    assert "error" in result
    assert "nonexistent" in result["error"]
