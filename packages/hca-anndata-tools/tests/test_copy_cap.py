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


def _make_cap_source(
    path: Path,
    cell_ids: list[str],
    var_ids: list[str] | None = None,
) -> Path:
    """Create an h5ad with CAP annotations."""
    n = len(cell_ids)
    rng = np.random.default_rng(42)
    if var_ids is None:
        var_ids = [f"GENE{i}" for i in range(5)]
    n_vars = len(var_ids)

    X = sp.random(n, n_vars, density=0.3, format="csr", dtype=np.float32, random_state=rng)

    labels = rng.choice(["typeA", "typeB"], n)
    # CAP serializes all annotation columns as categorical — mirror that here.
    obs = pd.DataFrame(
        {
            "author_cell_type": pd.Categorical(labels),
            "author_cell_type--cell_fullname": pd.Categorical(
                [f"{label} cell" for label in labels]
            ),
            "author_cell_type--cell_ontology_exists": pd.Categorical(["True"] * n),
            "author_cell_type--cell_ontology_term_id": pd.Categorical(
                rng.choice(["CL:0000540", "CL:0000127"], n)
            ),
            "author_cell_type--cell_ontology_term": pd.Categorical(
                rng.choice(["neuron", "astrocyte"], n)
            ),
            "author_cell_type--rationale": pd.Categorical(["morphology"] * n),
            "author_cell_type--marker_gene_evidence": pd.Categorical(
                rng.choice(["GFAP", "AIF1"], n)
            ),
            "author_cell_type--canonical_marker_genes": pd.Categorical(["unknown"] * n),
            "author_cell_type--synonyms": pd.Categorical(["unknown"] * n),
            "author_cell_type--category_fullname": pd.Categorical(["neural cell"] * n),
            "author_cell_type--category_cell_ontology_term_id": pd.Categorical(
                ["CL:0002319"] * n
            ),
            "author_cell_type--category_cell_ontology_term": pd.Categorical(
                ["neural cell"] * n
            ),
            # Demographic columns (should NOT be copied)
            "sex--cell_ontology_term_id": pd.Categorical(["PATO:0000384"] * n),
            "development_stage--cell_ontology_term_id": pd.Categorical(
                ["HsapDv:0000087"] * n
            ),
            "self_reported_ethnicity--cell_ontology_term_id": pd.Categorical(
                ["HANCESTRO:0005"] * n
            ),
            "cell_type--cell_ontology_term_id": pd.Categorical(["CL:0000540"] * n),
        },
        index=cell_ids,
    )

    var = pd.DataFrame(index=var_ids)
    adata = ad.AnnData(X=X, obs=obs, var=var)

    adata.uns["title"] = "CAP Test Dataset"
    # Canonical layout: the entire CAP block nests under uns['cap_metadata'].
    adata.uns["cap_metadata"] = {
        "cellannotation_schema_version": "1.0.2",
        "cellannotation_metadata": {
            "author_cell_type": {
                "algorithm_name": "NA",
                "algorithm_version": "NA",
                "algorithm_repo_url": "NA",
                "annotation_method": "manual",
                "description": "Test annotation set",
            }
        },
        "authors_list": "Test Author",
        "hierarchy": {"author_cell_type": 1},
        "description": "A test CAP dataset",
        "cap_dataset_url": "https://celltype.info/test",
        "publication_timestamp": "2026-01-01",
        "publication_version": "1.0",
    }

    adata.write_h5ad(path)
    return path


def _make_hca_target(
    path: Path,
    cell_ids: list[str],
    var_ids: list[str] | None = None,
) -> Path:
    """Create a minimal HCA-converted h5ad with same cells, no CAP columns."""
    n = len(cell_ids)
    rng = np.random.default_rng(7)
    if var_ids is None:
        var_ids = [f"GENE{i}" for i in range(5)]
    n_vars = len(var_ids)

    X = sp.random(n, n_vars, density=0.3, format="csr", dtype=np.float32, random_state=rng)

    obs = pd.DataFrame(
        {
            "author_cell_type": pd.Categorical(rng.choice(["typeA", "typeB"], n)),
            "cell_type": pd.Categorical(rng.choice(["neuron", "astrocyte"], n)),
            "organism_ontology_term_id": pd.Categorical(["NCBITaxon:9606"] * n),
        },
        index=cell_ids,
    )

    var = pd.DataFrame(index=var_ids)
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



def test_copy_uns_cap_metadata_nested(cap_source, hca_target):
    result = copy_cap_annotations(str(cap_source), str(hca_target))
    written = ad.read_h5ad(result["output_path"])
    cap = written.uns["cap_metadata"]
    assert "cellannotation_schema_version" in cap
    assert "cellannotation_metadata" in cap
    # Schema keys must NOT leak to the top level.
    assert "cellannotation_schema_version" not in written.uns
    assert "cellannotation_metadata" not in written.uns


def test_copy_cap_metadata_includes_provenance(cap_source, hca_target):
    result = copy_cap_annotations(str(cap_source), str(hca_target))
    written = ad.read_h5ad(result["output_path"])
    cap = written.uns["cap_metadata"]
    # Publication provenance travels inside the cap_metadata block.
    assert cap["cap_dataset_url"] == "https://celltype.info/test"
    assert cap["authors_list"] == "Test Author"
    assert cap["description"] == "A test CAP dataset"
    assert cap["publication_timestamp"] == "2026-01-01"
    assert cap["publication_version"] == "1.0"
    # The old provenance/cap split is gone.
    assert "provenance" not in written.uns or "cap" not in written.uns["provenance"]
    # NOT scattered at top level either.
    assert "cap_dataset_url" not in written.uns
    assert "authors_list" not in written.uns


def test_copy_refuses_legacy_toplevel_source(tmp_path, downgrade_cap_to_legacy):
    # An old-format source (CAP keys at top level) is refused, not normalized:
    # only the nested cap_metadata layout is accepted.
    src = downgrade_cap_to_legacy(_make_cap_source(tmp_path / "legacy.h5ad", CELL_IDS))
    target = _make_hca_target(tmp_path / "target_legacy.h5ad", CELL_IDS)

    result = copy_cap_annotations(str(src), str(target))
    assert "error" in result
    assert "cap_metadata" in result["error"]


def test_copy_refuses_malformed_cap_metadata_source(cap_source, hca_target):
    # cap_metadata present but not a dict -> explicit malformed error, not the
    # generic "no cellannotation_metadata" message.
    adata = ad.read_h5ad(cap_source)
    adata.uns["cap_metadata"] = "not-a-dict"
    adata.write_h5ad(cap_source)

    result = copy_cap_annotations(str(cap_source), str(hca_target))
    assert "error" in result
    assert "malformed" in result["error"].lower()


def test_copy_refuses_legacy_target(cap_source, tmp_path):
    # A target carrying deprecated top-level CAP (from older tooling) is refused
    # rather than overwritten into a mixed-layout file — even with overwrite=True.
    target = _make_hca_target(tmp_path / "legacy_target.h5ad", CELL_IDS)
    adata = ad.read_h5ad(target)
    adata.uns["cellannotation_schema_version"] = "1.0.2"
    adata.uns["cellannotation_metadata"] = {"author_cell_type": {"description": "x"}}
    adata.write_h5ad(target)

    result = copy_cap_annotations(str(cap_source), str(target), overwrite=True)
    assert "error" in result
    assert "Target" in result["error"]
    assert "cap_metadata" in result["error"]


# --- Skip demographic columns ---


def test_copy_skips_demographic_columns(cap_source, hca_target):
    result = copy_cap_annotations(str(cap_source), str(hca_target))
    written = ad.read_h5ad(result["output_path"])
    assert "sex--cell_ontology_term_id" not in written.obs.columns
    assert "development_stage--cell_ontology_term_id" not in written.obs.columns
    assert "self_reported_ethnicity--cell_ontology_term_id" not in written.obs.columns



# --- Edit log ---


def test_copy_edit_log(cap_source, hca_target):
    result = copy_cap_annotations(str(cap_source), str(hca_target))
    written = ad.read_h5ad(result["output_path"])
    assert EDIT_LOG_KEY in written.uns["provenance"]
    log = json.loads(written.uns["provenance"][EDIT_LOG_KEY])
    assert len(log) >= 1
    entry = log[-1]
    assert entry["operation"] == "import_cap_annotations"
    details = entry["details"]
    assert "author_cell_type" in details["annotation_sets"]
    cells = details["cells"]
    assert cells["n_cap"] == len(CELL_IDS)
    assert cells["n_hca"] == len(CELL_IDS)
    assert cells["n_matched"] == len(CELL_IDS)
    assert cells["missing_from_hca"] == {"n": 0, "pct": pytest.approx(0.0)}
    assert cells["missing_from_cap"] == {"n": 0, "pct": pytest.approx(0.0)}
    genes = details["genes"]
    assert genes["n_cap"] == 5
    assert genes["n_hca"] == 5
    assert genes["n_matched"] == 5
    assert genes["missing_from_hca"] == {"n": 0, "pct": pytest.approx(0.0)}
    assert genes["missing_from_cap"] == {"n": 0, "pct": pytest.approx(0.0)}


# --- Var-axis overlap ---


def test_var_overlap_cap_superset(tmp_path):
    # CAP has GENE0..GENE6 (7), HCA has GENE0..GENE4 (5). HCA ⊂ CAP.
    cap = _make_cap_source(
        tmp_path / "cap_var_super.h5ad",
        CELL_IDS,
        var_ids=[f"GENE{i}" for i in range(7)],
    )
    target = _make_hca_target(
        tmp_path / "target_var_sub.h5ad",
        CELL_IDS,
        var_ids=[f"GENE{i}" for i in range(5)],
    )
    result = copy_cap_annotations(str(cap), str(target))
    assert "error" not in result
    genes = result["genes"]
    assert genes["n_cap"] == 7
    assert genes["n_hca"] == 5
    assert genes["n_matched"] == 5
    assert genes["missing_from_hca"] == {"n": 2, "pct": pytest.approx(28.6)}
    assert genes["missing_from_cap"] == {"n": 0, "pct": pytest.approx(0.0)}


def test_var_overlap_hca_superset(tmp_path):
    # CAP has GENE0..GENE4 (5), HCA has GENE0..GENE6 (7). CAP ⊂ HCA.
    cap = _make_cap_source(
        tmp_path / "cap_var_sub.h5ad",
        CELL_IDS,
        var_ids=[f"GENE{i}" for i in range(5)],
    )
    target = _make_hca_target(
        tmp_path / "target_var_super.h5ad",
        CELL_IDS,
        var_ids=[f"GENE{i}" for i in range(7)],
    )
    result = copy_cap_annotations(str(cap), str(target))
    assert "error" not in result
    genes = result["genes"]
    assert genes["n_cap"] == 5
    assert genes["n_hca"] == 7
    assert genes["n_matched"] == 5
    assert genes["missing_from_hca"] == {"n": 0, "pct": pytest.approx(0.0)}
    assert genes["missing_from_cap"] == {"n": 2, "pct": pytest.approx(28.6)}


def test_var_overlap_disjoint(tmp_path):
    # No shared genes — copy should still succeed (no gene-overlap floor).
    cap = _make_cap_source(
        tmp_path / "cap_var_disjoint.h5ad",
        CELL_IDS,
        var_ids=[f"GENE{i}" for i in range(5)],
    )
    target = _make_hca_target(
        tmp_path / "target_var_disjoint.h5ad",
        CELL_IDS,
        var_ids=[f"OTHER{i}" for i in range(5)],
    )
    result = copy_cap_annotations(str(cap), str(target))
    assert "error" not in result
    genes = result["genes"]
    assert genes["n_cap"] == 5
    assert genes["n_hca"] == 5
    assert genes["n_matched"] == 0
    assert genes["missing_from_hca"] == {"n": 5, "pct": pytest.approx(100.0)}
    assert genes["missing_from_cap"] == {"n": 5, "pct": pytest.approx(100.0)}


@pytest.mark.filterwarnings("ignore:Variable names are not unique:UserWarning")
def test_var_overlap_rejects_duplicate_var_ids(cap_source, tmp_path):
    # Sets silently dedupe — guard against it by reading var as a list and
    # explicitly rejecting duplicates so n_vars stays accurate.
    target = _make_hca_target(
        tmp_path / "target_dup.h5ad",
        CELL_IDS,
        var_ids=["GENE0", "GENE1", "GENE1", "GENE2", "GENE3"],
    )
    result = copy_cap_annotations(str(cap_source), str(target))
    assert "error" in result
    assert "duplicate" in result["error"].lower()
    assert "HCA genes" in result["error"]


# --- Failure cases ---


def test_copy_cell_mismatch_fails(cap_source, tmp_path):
    different_cells = _make_hca_target(
        tmp_path / "different.h5ad", [f"other_{i}" for i in range(10)]
    )
    result = copy_cap_annotations(str(cap_source), str(different_cells))
    assert "error" in result
    assert "mismatch" in result["error"].lower()
    assert result["cells"]["n_matched"] == 0


def test_copy_cap_uncovered_fails(cap_source, tmp_path):
    # HCA is a strict subset of CAP (5 of CAP's 10 cells). HCA is fully covered,
    # but half of CAP is missing from HCA — exercises the asymmetric failure
    # where missing_from_hca exceeds the threshold while missing_from_cap is 0.
    subset = _make_hca_target(
        tmp_path / "subset.h5ad", [f"cell_{i}" for i in range(5)]
    )
    result = copy_cap_annotations(str(cap_source), str(subset))
    assert "error" in result
    assert "mismatch" in result["error"].lower()
    assert result["cells"]["missing_from_cap"] == {"n": 0, "pct": pytest.approx(0.0)}
    assert result["cells"]["missing_from_hca"] == {"n": 5, "pct": pytest.approx(50.0)}


def test_copy_partial_overlap_succeeds(tmp_path):
    # 19/20 HCA cells present in CAP → 5% missing from CAP;
    # 19/20 CAP cells present in HCA → 5% missing from HCA.
    # Threshold is inclusive, so this should succeed and the HCA-only row
    # should end up with NaN in the new CAP columns.
    target_ids = [f"cell_{i}" for i in range(19)] + ["target_only"]
    cap_20 = _make_cap_source(
        tmp_path / "cap_20.h5ad", [f"cell_{i}" for i in range(20)]
    )
    target = _make_hca_target(tmp_path / "target_20.h5ad", target_ids)

    result = copy_cap_annotations(str(cap_20), str(target))

    assert "error" not in result
    cells = result["cells"]
    assert cells["n_cap"] == 20
    assert cells["n_hca"] == 20
    assert cells["n_matched"] == 19
    assert cells["missing_from_hca"] == {"n": 1, "pct": pytest.approx(5.0)}
    assert cells["missing_from_cap"] == {"n": 1, "pct": pytest.approx(5.0)}

    written = ad.read_h5ad(result["output_path"])
    # HCA-only cell should have NaN in a copied categorical CAP column.
    col = "author_cell_type--cell_ontology_term_id"
    assert col in written.obs.columns
    assert pd.isna(written.obs.loc["target_only", col])


def test_copy_preserves_column_dtype(cap_source, hca_target):
    # Every copied CAP obs column must remain categorical (CAP's serialization
    # contract). The copy must not coerce dtypes.
    result = copy_cap_annotations(str(cap_source), str(hca_target))
    assert "error" not in result
    written = ad.read_h5ad(result["output_path"])
    for col in result["obs_columns_added"]:
        assert isinstance(written.obs[col].dtype, pd.CategoricalDtype), (
            f"{col} dtype changed to {written.obs[col].dtype}"
        )


@pytest.mark.filterwarnings("ignore::anndata._warnings.OldFormatWarning")
def test_copy_rejects_non_categorical_source_column(cap_source, hca_target):
    # Rewrite one CAP column in the source as a plain string dataset (via h5py,
    # bypassing anndata's auto-coercion to categorical) to simulate a source
    # that violates CAP's categorical-everywhere serialization contract.
    import h5py
    col = "author_cell_type--rationale"
    with h5py.File(cap_source, "a") as f:
        del f["obs"][col]
        f["obs"].create_dataset(col, data=np.array(["morphology"] * len(CELL_IDS), dtype="S"))

    result = copy_cap_annotations(str(cap_source), str(hca_target))

    assert "error" in result
    assert "not categorical" in result["error"].lower()
    assert col in result["error"]


def test_copy_below_threshold_fails(cap_source, tmp_path):
    # 9/10 HCA cells in CAP → 10% missing from CAP, above the 5% ceiling.
    target_ids = [f"cell_{i}" for i in range(9)] + ["target_only"]
    target = _make_hca_target(tmp_path / "target_below.h5ad", target_ids)

    result = copy_cap_annotations(str(cap_source), str(target))

    assert "error" in result
    assert "mismatch" in result["error"].lower()
    assert result["cells"]["n_matched"] == 9
    assert result["cells"]["missing_from_cap"] == {"n": 1, "pct": pytest.approx(10.0)}


def test_copy_no_cap_source_fails(hca_target, tmp_path):
    no_cap = _make_hca_target(tmp_path / "no_cap.h5ad", CELL_IDS)
    result = copy_cap_annotations(str(no_cap), str(hca_target))
    assert "error" in result
    assert "cellannotation_metadata" in result["error"]


def test_copy_target_has_cap_fails(cap_source, hca_target_with_cap):
    result = copy_cap_annotations(str(cap_source), str(hca_target_with_cap))
    assert "error" in result
    assert "overwrite" in result["error"].lower()


# --- Pipeline: convert then copy_cap preserves both provenance keys ---


def test_copy_cap_preserves_cellxgene_provenance(cap_source, tmp_path):
    """When target already has provenance/cellxgene, copy_cap writes the CAP block to uns['cap_metadata'] alongside it (preserving the cellxgene provenance)."""
    n = len(CELL_IDS)
    rng = np.random.default_rng(99)
    X = sp.random(n, 5, density=0.3, format="csr", dtype=np.float32, random_state=rng)
    obs = pd.DataFrame(
        {
            "author_cell_type": pd.Categorical(rng.choice(["typeA", "typeB"], n)),
            "organism_ontology_term_id": pd.Categorical(["NCBITaxon:9606"] * n),
        },
        index=CELL_IDS,
    )
    adata = ad.AnnData(X=X, obs=obs, var=pd.DataFrame(index=[f"G{i}" for i in range(5)]))
    adata.uns["provenance"] = {"cellxgene": {"schema_version": "7.0.0"}}
    adata.uns["title"] = "Test"
    target_path = tmp_path / "with_cxg_provenance.h5ad"
    adata.write_h5ad(target_path)

    result = copy_cap_annotations(str(cap_source), str(target_path))
    assert "error" not in result
    written = ad.read_h5ad(result["output_path"])
    # Existing cellxgene provenance is preserved alongside the new CAP block.
    assert "cellxgene" in written.uns["provenance"]
    assert written.uns["provenance"]["cellxgene"]["schema_version"] == "7.0.0"
    assert "cap_metadata" in written.uns


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
    """Source and target have same cells in different order — values align correctly."""
    reversed_ids = list(reversed(CELL_IDS))
    target = _make_hca_target(tmp_path / "reversed.h5ad", reversed_ids)
    result = copy_cap_annotations(str(cap_source), str(target))
    assert "error" not in result

    written = ad.read_h5ad(result["output_path"])
    assert list(written.obs.index) == reversed_ids

    # Verify annotation values align with cell IDs, not positional order
    source = ad.read_h5ad(str(cap_source))
    for cell_id in reversed_ids[:3]:
        src_val = source.obs.loc[cell_id, "author_cell_type--cell_ontology_term_id"]
        tgt_val = written.obs.loc[cell_id, "author_cell_type--cell_ontology_term_id"]
        assert str(src_val) == str(tgt_val), f"Mismatch at {cell_id}"


def test_missing_file():
    result = copy_cap_annotations("/nonexistent/source.h5ad", "/nonexistent/target.h5ad")
    assert "error" in result
