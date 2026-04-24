"""Tests for HCALabeler."""

import copy

import anndata
import pandas as pd
import pytest

from hca_schema_validator import HCALabeler

from .fixtures.hca_fixtures import adata as valid_adata


@pytest.fixture
def base_adata():
    # Deepcopy the module-level fixture so tests don't mutate each other's state.
    return copy.deepcopy(valid_adata)


@pytest.fixture
def labeled(base_adata, tmp_path):
    out_path = tmp_path / "labeled.h5ad"
    HCALabeler(base_adata).write_labels(str(out_path))
    return anndata.read_h5ad(str(out_path))


def _label(adata, tmp_path):
    out_path = tmp_path / "labeled.h5ad"
    HCALabeler(adata).write_labels(str(out_path))
    return anndata.read_h5ad(str(out_path))


def _replace_first_feature_id(adata, new_id):
    """Swap the first var/raw.var index entry for `new_id` and return it.

    Both indexes are updated together so they stay aligned (otherwise the
    labeler's raw.var mirror would target a different gene).
    """
    new_ids = [new_id] + list(adata.var.index[1:])
    adata.var.index = pd.Index(new_ids)
    raw = adata.raw.to_adata()
    raw.var.index = pd.Index(new_ids)
    adata.raw = raw
    return new_id


def test_feature_name_populated_from_ensembl(labeled):
    expected = {
        "ENSG00000127603": "MACF1",
        "ENSG00000141510": "TP53",
        "ENSG00000012048": "BRCA1",
        "ENSG00000139618": "BRCA2",
        "ENSG00000002330": "BAD",
        "ENSG00000000005": "TNMD",
        "ENSG00000000419": "DPM1",
    }
    for ens_id, symbol in expected.items():
        assert labeled.var.loc[ens_id, "feature_name"] == symbol


def test_unknown_ensembl_yields_nan(base_adata, tmp_path):
    fake_id = _replace_first_feature_id(base_adata, "ENSG99999999999")

    labeled = _label(base_adata, tmp_path)
    raw_var = labeled.raw.to_adata().var

    for col in ("feature_name", "feature_reference", "feature_biotype", "feature_length", "feature_type"):
        assert pd.isna(labeled.var.loc[fake_id, col]), f"var.{col} should be NaN for unknown ID"
        assert pd.isna(raw_var.loc[fake_id, col]), f"raw.var.{col} should be NaN for unknown ID"
    assert labeled.var.loc["ENSG00000141510", "feature_name"] == "TP53"
    assert raw_var.loc["ENSG00000141510", "feature_name"] == "TP53"


def test_obs_labels_populated_from_term_id(labeled):
    for col in (
        "tissue",
        "cell_type",
        "assay",
        "disease",
        "sex",
        "organism",
        "development_stage",
        "self_reported_ethnicity",
    ):
        assert col in labeled.obs.columns, f"{col} should be added by labeler"
        assert labeled.obs[col].notna().all(), f"{col} should be fully populated"


def test_preflight_fails_on_pre_populated_obs_label(base_adata, tmp_path):
    # Reserved-column policy: the labeler refuses to overwrite a pre-existing
    # controlled label column. Curators must drop the column upstream so we
    # never silently lose their text — see issue #374.
    base_adata.obs["tissue"] = "STALE_VALUE"
    with pytest.raises(ValueError) as excinfo:
        _label(base_adata, tmp_path)
    assert (
        "Add labels error: Column 'tissue' is a reserved column name "
        "of 'obs'. Remove it from h5ad and try again."
    ) in str(excinfo.value)


def test_preflight_fails_on_pre_populated_label_without_source(base_adata, tmp_path):
    # Reserved check is source-agnostic: even if the source ontology_term_id
    # column is absent (so the labeler wouldn't actually write the column),
    # a pre-existing reserved name still fails preflight. Single rule for the
    # curator: "delete the column."
    del base_adata.obs["cell_type_ontology_term_id"]
    base_adata.obs["cell_type"] = "STALE_VALUE"
    with pytest.raises(ValueError, match="reserved column name"):
        _label(base_adata, tmp_path)


def test_preflight_fails_on_pre_populated_feature_name(base_adata, tmp_path):
    base_adata.var["feature_name"] = "STALE_SYMBOL"
    with pytest.raises(ValueError) as excinfo:
        _label(base_adata, tmp_path)
    assert "feature_name" in str(excinfo.value)
    assert "reserved column name" in str(excinfo.value)


def test_preflight_fails_on_pre_populated_observation_joinid(base_adata, tmp_path):
    # `observation_joinid` is a component-level reserved column (not driven by
    # an add_labels directive) that label() writes from a hash digest. Without
    # this check the labeler would silently overwrite a producer-supplied
    # value. Wording omits the "Add labels error:" prefix to match cellxgene-
    # schema's reserved_columns wording.
    base_adata.obs["observation_joinid"] = "STALE_HASH"
    with pytest.raises(ValueError) as excinfo:
        _label(base_adata, tmp_path)
    msg = str(excinfo.value)
    assert (
        "Column 'observation_joinid' is a reserved column name "
        "of 'obs'. Remove it from h5ad and try again."
    ) in msg
    assert "Add labels error:" not in msg.split("observation_joinid")[0].rsplit("\n", 1)[-1]


def test_preflight_fails_on_pre_populated_feature_star_in_raw_var(base_adata, tmp_path):
    # Reserved-column policy covers all five `feature_*` targets in both var
    # and raw.var, not just `feature_name`. Spot-check raw.var with one of
    # the other four columns so the broader policy doesn't drift.
    raw = base_adata.raw.to_adata()
    raw.var["feature_reference"] = "STALE_REF"
    base_adata.raw = raw
    with pytest.raises(ValueError) as excinfo:
        _label(base_adata, tmp_path)
    msg = str(excinfo.value)
    assert "feature_reference" in msg
    assert "raw.var" in msg


def test_preflight_reports_all_collisions_in_one_error(base_adata, tmp_path):
    # All-or-nothing: every collision must surface in a single ValueError so
    # the curator can fix them in one pass instead of trial-and-error.
    base_adata.obs["tissue"] = "X"
    base_adata.obs["assay"] = "Y"
    base_adata.var["feature_name"] = "Z"
    with pytest.raises(ValueError) as excinfo:
        _label(base_adata, tmp_path)
    msg = str(excinfo.value)
    assert "'tissue'" in msg
    assert "'assay'" in msg
    assert "'feature_name'" in msg


def test_add_labels_direct_call_runs_preflight(base_adata):
    # Bypass guard: callers reaching the inherited mutation point directly
    # (e.g. via super() or a private-API call) must still hit preflight.
    base_adata.obs["tissue"] = "STALE_VALUE"
    labeler = HCALabeler(base_adata)
    with pytest.raises(ValueError, match="reserved column name"):
        labeler._add_labels()


def test_super_write_labels_runs_preflight(base_adata, tmp_path):
    # Bypass guard: skipping HCALabeler.write_labels and going through the
    # base class write_labels must still trip preflight via _add_labels.
    from hca_schema_validator._vendored.cellxgene_schema.write_labels import AnnDataLabelAppender

    base_adata.obs["tissue"] = "STALE_VALUE"
    labeler = HCALabeler(base_adata)
    out_path = tmp_path / "labeled.h5ad"
    with pytest.raises(ValueError, match="reserved column name"):
        AnnDataLabelAppender.write_labels(labeler, str(out_path))


def test_preflight_fails_on_non_human_organism(base_adata, tmp_path):
    base_adata.obs["organism_ontology_term_id"] = base_adata.obs["organism_ontology_term_id"].astype(str)
    first_label = base_adata.obs.index[0]
    base_adata.obs.loc[first_label, "organism_ontology_term_id"] = "NCBITaxon:10090"

    with pytest.raises(ValueError, match="NCBITaxon:10090"):
        _label(base_adata, tmp_path)


def test_cellxgene_only_uns_keys_absent(labeled):
    assert "schema_version" not in labeled.uns
    assert "schema_reference" not in labeled.uns
    assert "organism" not in labeled.uns


def test_observation_joinid_written(labeled, base_adata):
    assert "observation_joinid" in labeled.obs.columns
    assert len(labeled.obs["observation_joinid"]) == base_adata.n_obs
    assert labeled.obs["observation_joinid"].notna().all()


def test_preflight_fails_on_missing_required_ontology_term_id_column(base_adata, tmp_path):
    del base_adata.obs["organism_ontology_term_id"]
    with pytest.raises(ValueError, match="organism_ontology_term_id"):
        _label(base_adata, tmp_path)


def test_optional_cell_type_column_missing_is_skipped(base_adata, tmp_path):
    # cell_type_ontology_term_id is marked requirement_level: optional in the
    # HCA schema; labeler should succeed without writing obs['cell_type'].
    del base_adata.obs["cell_type_ontology_term_id"]
    labeled = _label(base_adata, tmp_path)
    assert "cell_type" not in labeled.obs.columns
    assert "tissue" in labeled.obs.columns  # other labels still written


def test_preflight_fails_when_cellxgene_schema_keys_present(base_adata, tmp_path):
    base_adata.uns["schema_version"] = "5.0.0"
    with pytest.raises(ValueError, match="schema_version"):
        _label(base_adata, tmp_path)


def test_ercc_spike_in_labeled(base_adata, tmp_path):
    ercc_id = _replace_first_feature_id(base_adata, "ERCC-00002")

    labeled = _label(base_adata, tmp_path)

    row = labeled.var.loc[ercc_id]
    assert row["feature_biotype"] == "spike-in"
    assert row["feature_reference"] == "NCBITaxon:32630"
    assert row["feature_type"] == "synthetic"
    assert "spike-in control" in str(row["feature_name"])


def test_producer_columns_preserved(base_adata, tmp_path):
    base_adata.obs["author_cell_type"] = "custom_label"
    base_adata.var["gene_symbol"] = "CUSTOM_SYMBOL"
    labeled = _label(base_adata, tmp_path)
    assert (labeled.obs["author_cell_type"].astype(str) == "custom_label").all()
    assert (labeled.var["gene_symbol"].astype(str) == "CUSTOM_SYMBOL").all()


def test_label_returns_mutated_adata_without_file_write(base_adata):
    result = HCALabeler(base_adata).label()
    # Same object back, mutated in place — enables the MCP wrapper to hand
    # the result to hca_anndata_tools.write.write_h5ad instead of having the
    # labeler own the write.
    assert result is base_adata
    assert "feature_name" in base_adata.var.columns
    assert "observation_joinid" in base_adata.obs.columns
    assert "tissue" in base_adata.obs.columns


def test_hca_derived_obs_labels_matches_schema(base_adata):
    """Guard against drift between the hand-maintained tuple and the schema YAML.

    HCA_DERIVED_OBS_LABELS is exported for downstream callers (e.g. the MCP
    label_h5ad wrapper) that need to reason about which columns the labeler
    writes without reloading the YAML. It must stay in sync with the obs
    add_labels directives in hca_schema_definition.yaml.
    """
    from hca_schema_validator import HCA_DERIVED_OBS_LABELS

    obs_def = HCALabeler(base_adata).schema_def["components"]["obs"]["columns"]
    schema_derived = {
        label["to_column"]
        for col_def in obs_def.values()
        for label in col_def.get("add_labels", [])
        if label.get("type") == "curie"
    }
    assert set(HCA_DERIVED_OBS_LABELS) == schema_derived
