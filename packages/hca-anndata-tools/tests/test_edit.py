"""Tests for set_uns and list_uns_fields."""

import json

import anndata as ad

from hca_anndata_tools.edit import list_uns_fields, set_uns
from hca_anndata_tools.write import EDIT_LOG_KEY


# --- list_uns_fields ---


def test_list_uns_fields_basic(sample_h5ad_for_write):
    result = list_uns_fields(str(sample_h5ad_for_write))
    assert "error" not in result
    assert "fields" in result
    assert isinstance(result["fields"], list)
    assert len(result["fields"]) > 0


def test_list_uns_fields_shows_current_value(sample_h5ad_for_write):
    result = list_uns_fields(str(sample_h5ad_for_write))
    title_field = next(f for f in result["fields"] if f["name"] == "title")
    assert title_field["is_set"] is True
    assert title_field["current_value"] == "Test Dataset"


def test_list_uns_fields_shows_batch_condition(sample_h5ad_for_write):
    result = list_uns_fields(str(sample_h5ad_for_write))
    bc = next(f for f in result["fields"] if f["name"] == "batch_condition")
    assert bc["is_set"] is True
    # Stored as numpy array in fixture, should be serialized to list
    assert bc["current_value"] == ["batch1", "batch2"]


def test_list_uns_fields_shows_missing_required(sample_h5ad_for_write):
    result = list_uns_fields(str(sample_h5ad_for_write))
    # description and study_pi are required but not in the test fixture
    assert "description" in result["missing_required"]
    assert "study_pi" in result["missing_required"]
    # bionetwork-only fields are in a separate list
    assert "ambient_count_correction" not in result["missing_required"]
    assert "ambient_count_correction" in result["missing_required_bionetwork"]


def test_list_uns_fields_shows_bionetwork_fields(sample_h5ad_for_write):
    result = list_uns_fields(str(sample_h5ad_for_write))
    field_names = [f["name"] for f in result["fields"]]
    assert "ambient_count_correction" in field_names
    assert "doublet_detection" in field_names
    acc = next(f for f in result["fields"] if f["name"] == "ambient_count_correction")
    assert acc["bionetwork_only"] is True


def test_list_uns_fields_extra_keys(sample_h5ad_for_write):
    result = list_uns_fields(str(sample_h5ad_for_write))
    # schema_version is in the fixture uns but not an HCA schema field
    assert "schema_version" in result["extra_uns_keys"]


def test_list_uns_fields_includes_obs_and_obsm(sample_h5ad_for_write):
    result = list_uns_fields(str(sample_h5ad_for_write))
    assert "obs_columns" in result
    assert "obsm_keys" in result
    assert "sex" in result["obs_columns"]
    assert "X_umap" in result["obsm_keys"]


def test_list_uns_fields_bad_path():
    result = list_uns_fields("/nonexistent/file.h5ad")
    assert "error" in result


# --- set_uns ---


def test_set_uns_string_field(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "description", "A test dataset")
    assert "error" not in result
    assert "output_path" in result

    written = ad.read_h5ad(result["output_path"])
    assert written.uns["description"] == "A test dataset"


def test_set_uns_list_field(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "study_pi", ["Smith,John,A."])
    assert "error" not in result

    written = ad.read_h5ad(result["output_path"])
    assert written.uns["study_pi"] == ["Smith,John,A."]


def test_set_uns_overwrite(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "title", "New Title")
    assert "error" not in result
    assert result["old_value"] == "Test Dataset"
    assert result["new_value"] == "New Title"

    written = ad.read_h5ad(result["output_path"])
    assert written.uns["title"] == "New Title"


def test_set_uns_invalid_field(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "not_a_real_field", "value")
    assert "error" in result
    assert "not a recognized HCA uns field" in result["error"]


def test_set_uns_batch_condition_valid(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "batch_condition", ["sex", "tissue"])
    assert "error" not in result

    written = ad.read_h5ad(result["output_path"])
    assert list(written.uns["batch_condition"]) == ["sex", "tissue"]


def test_set_uns_batch_condition_invalid_column(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "batch_condition", ["sex", "nonexistent"])
    assert "error" in result
    assert "nonexistent" in result["error"]


def test_set_uns_default_embedding_valid(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "default_embedding", "X_umap")
    assert "error" not in result

    written = ad.read_h5ad(result["output_path"])
    assert written.uns["default_embedding"] == "X_umap"


def test_set_uns_default_embedding_invalid(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "default_embedding", "X_tsne")
    assert "error" in result
    assert "X_tsne" in result["error"]


def test_set_uns_edit_log(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "description", "Logged edit")
    assert "error" not in result

    written = ad.read_h5ad(result["output_path"])
    log = json.loads(written.uns[EDIT_LOG_KEY])
    assert len(log) == 1
    assert log[0]["operation"] == "set_uns"
    assert log[0]["details"]["field"] == "description"
    assert log[0]["details"]["new_value"] == "Logged edit"


def test_set_uns_previous_value_in_details(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "title", "Updated")
    assert "error" not in result

    written = ad.read_h5ad(result["output_path"])
    log = json.loads(written.uns[EDIT_LOG_KEY])
    assert log[0]["details"]["old_value"] == "Test Dataset"


def test_set_uns_output_in_same_dir(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "description", "test")
    assert "error" not in result
    assert result["output_path"].startswith(str(sample_h5ad_for_write.parent))


def test_set_uns_bad_path():
    result = set_uns("/nonexistent/file.h5ad", "title", "test")
    assert "error" in result


# --- empty value rejection ---


def test_set_uns_empty_string_rejected(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "description", "")
    assert "error" in result
    assert "non-empty" in result["error"]


def test_set_uns_whitespace_string_rejected(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "description", "   ")
    assert "error" in result
    assert "non-empty" in result["error"]


def test_set_uns_empty_list_rejected(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "study_pi", [])
    assert "error" in result
    assert "non-empty" in result["error"]


def test_set_uns_list_with_empty_element_rejected(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "study_pi", ["Smith,John", ""])
    assert "error" in result
    assert "non-empty" in result["error"]


# --- type mismatch ---


def test_set_uns_list_to_string_field_rejected(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "description", ["not", "a", "string"])
    assert "error" in result


def test_set_uns_string_to_list_field_rejected(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "study_pi", "not a list")
    assert "error" in result


# --- bionetwork-only fields ---


def test_set_uns_ambient_count_correction(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "ambient_count_correction", "SoupX")
    assert "error" not in result
    written = ad.read_h5ad(result["output_path"])
    assert written.uns["ambient_count_correction"] == "SoupX"


def test_set_uns_doublet_detection(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "doublet_detection", "none")
    assert "error" not in result
    written = ad.read_h5ad(result["output_path"])
    assert written.uns["doublet_detection"] == "none"


def test_set_uns_bionetwork_empty_rejected(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "ambient_count_correction", "")
    assert "error" in result
    assert "non-empty" in result["error"]
