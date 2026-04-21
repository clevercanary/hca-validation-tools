"""Unit tests for the label_h5ad MCP wrapper."""

import json
import shutil

import anndata as ad
import pytest
from hca_anndata_mcp.tools.label import label_h5ad
from hca_anndata_tools.testing import create_sample_h5ad
from hca_schema_validator.testing import create_labelable_h5ad


@pytest.fixture
def labelable_path(tmp_path):
    return create_labelable_h5ad(tmp_path / "labelable.h5ad")


def test_label_h5ad_happy_path(labelable_path):
    result = label_h5ad(str(labelable_path))

    assert "error" not in result, result
    assert result["output_path"].endswith(".h5ad")
    assert result["n_vars"] == 7
    # All seven fixture Ensembl IDs are GENCODE-resolvable.
    assert result["feature_name_labeled"] == 7
    assert result["feature_name_nan"] == 0
    # Fixture ships with no bare-label columns pre-populated.
    assert result["obs_label_cols_overwritten"] == []
    assert result["var_feature_name_overwritten"] is False
    # cell_type is optional but present in the fixture, so all 8 labels written.
    assert set(result["obs_labels_written"]) == {
        "tissue", "cell_type", "assay", "disease",
        "sex", "organism", "development_stage", "self_reported_ethnicity",
    }

    labeled = ad.read_h5ad(result["output_path"])
    assert "feature_name" in labeled.var.columns
    assert "feature_name" in labeled.raw.to_adata().var.columns
    assert "observation_joinid" in labeled.obs.columns
    for col in ("tissue", "cell_type", "assay", "organism"):
        assert col in labeled.obs.columns


def test_label_h5ad_writes_edit_log_entry(labelable_path):
    result = label_h5ad(str(labelable_path))
    labeled = ad.read_h5ad(result["output_path"])

    log = json.loads(labeled.uns["provenance"]["edit_history"])
    entry = log[-1]
    assert entry["operation"] == "label_h5ad"
    assert entry["tool"] == "hca-anndata-tools"
    details = entry["details"]
    assert details["feature_name_labeled"] == 7
    assert details["feature_name_nan"] == 0
    assert details["raw_var_mirrored"] is True
    assert details["observation_joinid_written"] is True
    assert details["var_feature_name_overwritten"] is False
    assert details["obs_label_cols_overwritten"] == []
    assert set(details["obs_labels_written"]) == {
        "tissue", "cell_type", "assay", "disease",
        "sex", "organism", "development_stage", "self_reported_ethnicity",
    }


def test_label_h5ad_reports_overwrites(tmp_path):
    # Pre-populate obs["tissue"] and var["feature_name"] before labeling to
    # confirm the wrapper surfaces the overwrite in both the return value
    # and the edit-log entry.
    path = create_labelable_h5ad(tmp_path / "drifted.h5ad")
    adata = ad.read_h5ad(path)
    adata.obs["tissue"] = "STALE_LABEL"
    adata.var["feature_name"] = "STALE_SYMBOL"
    adata.write_h5ad(path)

    result = label_h5ad(str(path))

    assert "error" not in result, result
    assert result["var_feature_name_overwritten"] is True
    assert "tissue" in result["obs_label_cols_overwritten"]

    labeled = ad.read_h5ad(result["output_path"])
    assert "STALE_LABEL" not in labeled.obs["tissue"].astype(str).unique()
    assert "STALE_SYMBOL" not in labeled.var["feature_name"].astype(str).unique()


def test_label_h5ad_preflight_rejects_schema_version(tmp_path):
    path = create_labelable_h5ad(tmp_path / "cxg.h5ad")
    adata = ad.read_h5ad(path)
    adata.uns["schema_version"] = "5.0.0"
    adata.write_h5ad(path)

    result = label_h5ad(str(path))
    assert "error" in result
    assert "preflight" in result["error"]
    assert "schema_version" in result["error"]


def test_label_h5ad_preflight_rejects_non_human(tmp_path):
    path = create_labelable_h5ad(tmp_path / "mouse.h5ad")
    adata = ad.read_h5ad(path)
    adata.obs["organism_ontology_term_id"] = adata.obs["organism_ontology_term_id"].astype(str)
    adata.obs.loc[adata.obs.index[0], "organism_ontology_term_id"] = "NCBITaxon:10090"
    adata.write_h5ad(path)

    result = label_h5ad(str(path))
    assert "error" in result
    assert "NCBITaxon:10090" in result["error"]


def test_label_h5ad_preflight_rejects_missing_required_obs_col(tmp_path):
    # create_sample_h5ad omits organism_ontology_term_id and the other
    # required *_ontology_term_id columns — preflight should fail without
    # a surprise in the error surface.
    path = tmp_path / "sample.h5ad"
    create_sample_h5ad(path)

    result = label_h5ad(str(path))
    assert "error" in result
    assert "preflight" in result["error"]


def test_label_h5ad_missing_file():
    result = label_h5ad("/nonexistent/file.h5ad")
    assert "error" in result


def test_label_h5ad_resolves_latest(tmp_path):
    original = tmp_path / "dataset.h5ad"
    create_labelable_h5ad(original)

    # Seed a newer snapshot with a mutation that label_h5ad will preserve
    # (producer column untouched by the labeler — see PRD R3).
    snapshot = tmp_path / "dataset-edit-2026-04-17-06-00-00.h5ad"
    shutil.copy2(original, snapshot)
    adata = ad.read_h5ad(snapshot)
    adata.obs["author_cell_type"] = "marker_only_in_snapshot"
    adata.write_h5ad(snapshot)

    # Invoke via the original path — resolve_latest should pick the snapshot.
    result = label_h5ad(str(original))
    assert "error" not in result, result

    labeled = ad.read_h5ad(result["output_path"])
    assert "author_cell_type" in labeled.obs.columns
    assert (labeled.obs["author_cell_type"].astype(str) == "marker_only_in_snapshot").all()
