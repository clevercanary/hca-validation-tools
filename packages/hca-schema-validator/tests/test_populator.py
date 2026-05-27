"""Tests for hca_schema_validator.populator.populate_in_memory."""

import anndata as ad
import pandas as pd
from hca_schema_validator import populate_in_memory
from hca_schema_validator.testing import create_labelable_h5ad
from hca_schema_validator.validator import _lookup_canonical_label


# Canonical labels resolved from the fixture's term_ids. Computed once at
# import so tests don't all pay the ontology-lookup cost.
_FIXTURE_CANONICAL = {
    "cell_type": _lookup_canonical_label("CL:0000066", set()),
    "assay": _lookup_canonical_label("EFO:0009899", set()),
    "disease": _lookup_canonical_label("MONDO:0100096", set()),
    "sex": _lookup_canonical_label("PATO:0000383", set()),
    "tissue": _lookup_canonical_label("UBERON:0002048", set()),
    "development_stage": _lookup_canonical_label("HsapDv:0000003", set()),
    "organism": _lookup_canonical_label("NCBITaxon:9606", set()),
}


def _load(path):
    """Read the fixture-built h5ad into memory."""
    return ad.read_h5ad(path)


# --- Happy path: fill empty columns ---


def test_fill_all_empty(tmp_path):
    """Fixture has term_ids but no cosmetic obs labels and no feature_*;
    populator fills all 7 obs labels + 5 var feature_* + raw.var mirror."""
    adata = _load(create_labelable_h5ad(tmp_path / "empty.h5ad"))

    result = populate_in_memory(adata)

    assert "error" not in result, result
    assert set(result["filled"]) == {
        "tissue",
        "cell_type",
        "assay",
        "disease",
        "sex",
        "organism",
        "development_stage",
        "var/feature_name",
        "var/feature_reference",
        "var/feature_biotype",
        "var/feature_length",
        "var/feature_type",
    }
    assert result["matched"] == []

    # Obs side: canonical values written.
    for col, expected in _FIXTURE_CANONICAL.items():
        if expected is None:
            continue  # ontology miss; column still written, value can be NaN
        assert (adata.obs[col] == expected).all(), f"{col} mismatch"
    # Var side: feature_name populated from GENCODE.
    assert "feature_name" in adata.var.columns
    assert adata.var["feature_name"].notna().any()


def test_no_observation_joinid_written(tmp_path):
    """The whole point vs HCALabeler: never write the non-reproducible
    random observation_joinid column."""
    adata = _load(create_labelable_h5ad(tmp_path / "no_oj.h5ad"))
    result = populate_in_memory(adata)
    assert "error" not in result
    assert "observation_joinid" not in adata.obs.columns


# --- Matched (skip) ---


def test_skip_matched_obs_columns(tmp_path):
    """Pre-populate obs cosmetic columns with the canonical value;
    populator recognizes the match and skips them (no error, no fill)."""
    adata = _load(create_labelable_h5ad(tmp_path / "matched.h5ad"))
    adata.obs["tissue"] = pd.Categorical([_FIXTURE_CANONICAL["tissue"]] * adata.n_obs)
    adata.obs["assay"] = pd.Categorical([_FIXTURE_CANONICAL["assay"]] * adata.n_obs)

    result = populate_in_memory(adata)

    assert "error" not in result, result
    assert "tissue" in result["matched"]
    assert "assay" in result["matched"]
    # Empty ones still get filled.
    assert "cell_type" in result["filled"]
    assert "tissue" not in result["filled"]


def test_skipped_when_everything_matched(tmp_path):
    """All obs labels + all var feature_* pre-populated with canonical →
    skipped sentinel, adata not mutated."""
    # First run fills everything.
    adata_seed = _load(create_labelable_h5ad(tmp_path / "all_matched.h5ad"))
    populate_in_memory(adata_seed)

    # Re-run on the now-populated adata — should report skipped.
    result = populate_in_memory(adata_seed)
    assert result.get("skipped") is True, result
    assert "matched" in result


# --- Mismatch errors ---


def test_error_on_obs_mismatch(tmp_path):
    """Pre-populate an obs cosmetic column with a wrong value vs term_id;
    populator refuses with a row-level error message."""
    adata = _load(create_labelable_h5ad(tmp_path / "obs_mismatch.h5ad"))
    adata.obs["tissue"] = pd.Categorical(["totally-wrong-tissue-label"] * adata.n_obs)

    result = populate_in_memory(adata)

    assert "error" in result
    assert "details" in result
    assert any(
        "obs['tissue']" in e
        and "totally-wrong-tissue-label" in e
        and "UBERON:0002048" in e
        for e in result["details"]["errors"]
    )


def test_error_on_var_mismatch(tmp_path):
    """Pre-populate var feature_name with wrong values; populator refuses."""
    adata = _load(create_labelable_h5ad(tmp_path / "var_mismatch.h5ad"))
    adata.var["feature_name"] = pd.Categorical(["WRONG_SYMBOL"] * adata.n_vars)

    result = populate_in_memory(adata)

    assert "error" in result
    assert any(
        "var['feature_name']" in e and "WRONG_SYMBOL" in e
        for e in result["details"]["errors"]
    )


def test_partial_mix_mismatch_blocks_all(tmp_path):
    """Mix: some columns match, some empty, some mismatch → populator
    refuses (no partial mutation). matched / would_fill still surfaced in
    details so the curator sees the full picture."""
    adata = _load(create_labelable_h5ad(tmp_path / "mix.h5ad"))
    adata.obs["tissue"] = pd.Categorical([_FIXTURE_CANONICAL["tissue"]] * adata.n_obs)  # matched
    adata.obs["cell_type"] = pd.Categorical(["wrong-cell-type-label"] * adata.n_obs)  # mismatch

    result = populate_in_memory(adata)

    assert "error" in result
    assert "tissue" in result["details"]["matched"]
    assert any("cell_type" in e for e in result["details"]["errors"])
    assert "sex" in result["details"]["would_fill"]


# --- Data-level refusals ---


def test_refuse_sre_present(tmp_path):
    adata = _load(create_labelable_h5ad(tmp_path / "sre.h5ad"))
    adata.obs["self_reported_ethnicity_ontology_term_id"] = pd.Categorical(
        ["unknown"] * adata.n_obs
    )

    result = populate_in_memory(adata)
    assert "error" in result
    assert "strip_forbidden_obs_columns" in result["error"]


def test_refuse_cellxgene_layout(tmp_path):
    adata = _load(create_labelable_h5ad(tmp_path / "cxg_layout.h5ad"))
    adata.uns["schema_version"] = "7.0.0"

    result = populate_in_memory(adata)
    assert "error" in result
    assert "convert_cellxgene_to_hca" in result["error"]


def test_refuse_non_human(tmp_path):
    adata = _load(create_labelable_h5ad(tmp_path / "mouse.h5ad"))
    adata.obs["organism_ontology_term_id"] = pd.Categorical(["NCBITaxon:10090"] * adata.n_obs)

    result = populate_in_memory(adata)
    assert "error" in result
    assert "non-human" in result["error"]


def test_does_NOT_check_edit_log(tmp_path):
    """Origin-level refusal (import_cellxgene in edit log) is the MCP
    wrapper's job — populator must not check it. Asserts that an adata
    with an import_cellxgene edit-log entry runs normally here.

    Seeds the log inline rather than importing the edit-log helper from
    hca-anndata-tools — keeping hca-schema-validator's test surface free
    of a cross-package dep that isn't declared in its pyproject.
    """
    import json

    adata = _load(create_labelable_h5ad(tmp_path / "with_import.h5ad"))
    seed = json.dumps([{
        "timestamp": "2026-01-01T00:00:00+00:00",
        "tool": "hca-anndata-tools",
        "tool_version": "0.0.0",
        "operation": "import_cellxgene",
        "description": "Imported from CellxGENE Discover",
        "details": {},
        "source_file": "x.h5ad",
        "source_sha256": "0" * 64,
    }])
    adata.uns.setdefault("provenance", {})["edit_history"] = seed

    # Should NOT refuse — origin check is the wrapper's concern.
    result = populate_in_memory(adata)
    assert "error" not in result, (
        "populator must not check edit log; that's the wrapper's job. "
        f"Got: {result}"
    )
