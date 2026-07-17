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
    # All 7 obs labels + 5 var feature_* + 5 raw.var feature_* mirrors
    # (the fixture's raw is a copy of an unlabeled adata, so raw.var
    # also starts empty and gets the same symmetric fill).
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
        "raw.var/feature_name",
        "raw.var/feature_reference",
        "raw.var/feature_biotype",
        "raw.var/feature_length",
        "raw.var/feature_type",
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
    """Populator never writes obs['observation_joinid'] — it's HCA-
    reserved-but-not-required, and writing reserved columns is out of
    scope for a per-column-fill tool (joinid semantics belong with
    label_h5ad's broader labeling pass). See the populator.py module
    docstring for the full rationale; this test pins the contract."""
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


def test_partial_fill_obs_when_some_rows_nan(tmp_path):
    """Producer labeled most rows correctly but left some NaN. Populator
    verifies every populated row matches canonical, then fills the NaN
    rows from canonical — no mismatch, partial fill. Reports the column
    in 'filled' (merged values), NOT in 'matched'."""
    adata = _load(create_labelable_h5ad(tmp_path / "partial_obs.h5ad"))
    # 4 rows in the fixture; pre-populate 2 with canonical, 2 with NaN.
    canonical_tissue = _FIXTURE_CANONICAL["tissue"]
    partial = pd.Categorical(
        [canonical_tissue, None, canonical_tissue, None],
        categories=[canonical_tissue],
    )
    adata.obs["tissue"] = partial

    result = populate_in_memory(adata)

    assert "error" not in result, result
    assert "tissue" in result["filled"], result
    assert "tissue" not in result["matched"]
    # All 4 rows should now equal canonical (2 preserved + 2 filled).
    assert (adata.obs["tissue"] == canonical_tissue).all()


def test_partial_fill_var_when_some_rows_nan(tmp_path):
    """Same partial-fill semantic for var feature_name: producer wrote
    correct gene symbols on some rows, NaN on others. Populator fills
    the NaN rows from GENCODE without rewriting the producer's correct
    values."""
    adata = _load(create_labelable_h5ad(tmp_path / "partial_var.h5ad"))
    # First, compute what GENCODE thinks the canonical feature_name is
    # for the fixture's Ensembl IDs by running populate once on a sibling
    # adata to capture the canonical values.
    sib = _load(create_labelable_h5ad(tmp_path / "sib.h5ad"))
    populate_in_memory(sib)
    canonical_names = list(sib.var["feature_name"])

    # On the target file: pre-populate every-other row with the canonical
    # value, leave the rest NaN.
    partial = [canonical_names[i] if i % 2 == 0 else None for i in range(adata.n_vars)]
    adata.var["feature_name"] = pd.Categorical(partial)

    result = populate_in_memory(adata)

    assert "error" not in result, result
    assert "var/feature_name" in result["filled"], result
    # All rows should now equal canonical (no producer values overwritten,
    # NaN rows filled).
    written = list(adata.var["feature_name"])
    for i, expected in enumerate(canonical_names):
        if expected is None or pd.isna(expected):
            continue
        assert written[i] == expected, f"row {i}: got {written[i]!r}, expected {expected!r}"


def test_raw_var_mismatch_refuses_not_silently_skips(tmp_path):
    """Pre-populate raw.var['feature_name'] with WRONG values while var
    is empty. Old behavior was 'fill var, skip raw.var because column
    exists' — silent — leaving stale wrong values on raw.var. New
    symmetric behavior: classify raw.var separately, refuse on mismatch
    with row-level evidence prefixed as raw.var['col'].
    """
    adata = _load(create_labelable_h5ad(tmp_path / "raw_mismatch.h5ad"))
    # adata.raw was set by the fixture as a copy of adata. Now overwrite
    # raw.var['feature_name'] with deliberately wrong values.
    raw_var = adata.raw.var
    raw_var["feature_name"] = pd.Categorical(["WRONG_RAW_SYMBOL"] * adata.n_vars)

    result = populate_in_memory(adata)

    assert "error" in result
    # The error must be attributed to raw.var (the rewrite at fill-time
    # changes the prefix in the message).
    assert any("raw.var['feature_name']" in e and "WRONG_RAW_SYMBOL" in e for e in result["details"]["errors"]), result[
        "details"
    ]["errors"]


def test_raw_var_fill_when_empty(tmp_path):
    """raw.var feature_name column missing → populator fills it via the
    same path as var. Reports the fill as 'raw.var/feature_name'."""
    adata = _load(create_labelable_h5ad(tmp_path / "raw_fill.h5ad"))
    # Fixture leaves raw.var without feature_* columns by default.
    # Confirm: feature_name should be absent or NaN on raw.var.
    if "feature_name" in adata.raw.var.columns:
        # Some fixture variants set it; drop to test the fill path
        # explicitly.
        del adata.raw.var["feature_name"]

    result = populate_in_memory(adata)

    assert "error" not in result, result
    assert "raw.var/feature_name" in result["filled"], result
    assert "feature_name" in adata.raw.var.columns


def test_partial_fill_refuses_when_filled_rows_mismatch(tmp_path):
    """Partial-NaN obs column where the populated rows DON'T match
    canonical → refuse entirely, no fill of the NaN rows. The whole
    point: only fill NaNs when every populated row passes verification."""
    adata = _load(create_labelable_h5ad(tmp_path / "partial_mismatch.h5ad"))
    # Producer wrote a WRONG value on 2 rows, left 2 NaN. No fill should
    # happen even though the NaN rows could be filled — the populated
    # rows fail verification.
    partial = pd.Categorical(
        ["wrong-tissue", None, "wrong-tissue", None],
        categories=["wrong-tissue"],
    )
    adata.obs["tissue"] = partial

    result = populate_in_memory(adata)

    assert "error" in result
    assert any("obs['tissue']" in e and "wrong-tissue" in e for e in result["details"]["errors"])
    # NaN rows should still be NaN — partial fill must not happen on a
    # column whose populated rows didn't pass verification.
    assert adata.obs["tissue"].iloc[1] is pd.NA or pd.isna(adata.obs["tissue"].iloc[1])


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
        "obs['tissue']" in e and "totally-wrong-tissue-label" in e and "UBERON:0002048" in e
        for e in result["details"]["errors"]
    )


def test_error_on_var_mismatch(tmp_path):
    """Pre-populate var feature_name with wrong values; populator refuses."""
    adata = _load(create_labelable_h5ad(tmp_path / "var_mismatch.h5ad"))
    adata.var["feature_name"] = pd.Categorical(["WRONG_SYMBOL"] * adata.n_vars)

    result = populate_in_memory(adata)

    assert "error" in result
    assert any("var['feature_name']" in e and "WRONG_SYMBOL" in e for e in result["details"]["errors"])


def test_error_message_distinguishes_unknown_ensembl(tmp_path):
    """When GENCODE doesn't know the Ensembl ID but the producer claimed
    a value, the error message must NOT format canonical as '<NA>' —
    that's opaque to curators. Should explain that GENCODE has no
    canonical value for the ID."""
    adata = _load(create_labelable_h5ad(tmp_path / "unknown_ensembl.h5ad"))
    # Replace var.index with a fake Ensembl ID GENCODE won't know, then
    # claim a feature_name for that row. Triggers the NaN-canonical
    # mismatch path.
    fake_ids = ["ENSG99999999999"] + list(adata.var.index[1:])
    adata.var.index = pd.Index(fake_ids)
    adata.var["feature_name"] = pd.Categorical(["FAKE_SYMBOL"] * adata.n_vars)

    result = populate_in_memory(adata)

    assert "error" in result
    msgs = result["details"]["errors"]
    # New message format for the NaN-canonical branch — should not
    # render '<NA>'.
    nan_branch_msgs = [m for m in msgs if "GENCODE has no canonical value" in m]
    assert nan_branch_msgs, f"expected NaN-canonical branch message, got: {msgs}"
    assert not any("'<NA>'" in m for m in nan_branch_msgs), (
        f"NaN-canonical messages must not format canonical as '<NA>': {nan_branch_msgs}"
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
    adata.obs["self_reported_ethnicity_ontology_term_id"] = pd.Categorical(["unknown"] * adata.n_obs)

    result = populate_in_memory(adata)
    assert "error" in result
    assert "strip_forbidden_obs_columns" in result["error"]


def test_refuse_cellxgene_layout(tmp_path):
    adata = _load(create_labelable_h5ad(tmp_path / "cxg_layout.h5ad"))
    adata.uns["schema_version"] = "7.0.0"

    result = populate_in_memory(adata)
    assert "error" in result
    assert "convert_cellxgene_to_hca" in result["error"]


def test_refuse_provenance_cellxgene(tmp_path):
    """File has uns['provenance']['cellxgene'] — set by our own
    convert_cellxgene_to_hca tool. Even without a top-level
    schema_version (which the convert tool moves out) the populator
    must recognize this as a CellxGENE-derived file and refuse."""
    adata = _load(create_labelable_h5ad(tmp_path / "from_convert.h5ad"))
    adata.uns.setdefault("provenance", {})["cellxgene"] = {
        "schema_version": "7.0.0",
        "schema_reference": "https://example.com",
        "citation": "Some citation",
    }

    result = populate_in_memory(adata)
    assert "error" in result
    assert "CellxGENE-derived" in result["error"]
    assert "provenance" in result["error"]
    assert "label_h5ad" in result["error"]


def test_refuse_observation_joinid_present(tmp_path):
    """Most durable signal of CellxGENE-derived: obs['observation_joinid']
    is written by cellxgene-schema add-labels and persists. If it's
    present, the file has been through CellxGENE labeling somewhere
    upstream — populator must refuse even if none of the other markers
    (schema_version, provenance/cellxgene, edit log) are present."""
    import pandas as pd

    adata = _load(create_labelable_h5ad(tmp_path / "with_joinid.h5ad"))
    # No schema_version, no provenance/cellxgene — only the joinid.
    adata.obs["observation_joinid"] = pd.Categorical([f"joinid_{i}" for i in range(adata.n_obs)])

    result = populate_in_memory(adata)
    assert "error" in result
    assert "CellxGENE-derived" in result["error"]
    assert "observation_joinid" in result["error"]


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
    seed = json.dumps(
        [
            {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "tool": "hca-anndata-tools",
                "tool_version": "0.0.0",
                "operation": "import_cellxgene",
                "description": "Imported from CellxGENE Discover",
                "details": {},
                "source_file": "x.h5ad",
                "source_sha256": "0" * 64,
            }
        ]
    )
    adata.uns.setdefault("provenance", {})["edit_history"] = seed

    # Should NOT refuse — origin check is the wrapper's concern.
    result = populate_in_memory(adata)
    assert "error" not in result, f"populator must not check edit log; that's the wrapper's job. Got: {result}"
