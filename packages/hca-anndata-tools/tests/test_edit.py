"""Tests for set_uns, list_uns_fields, and replace_placeholder_values."""

import json

import anndata as ad
import numpy as np
import pandas as pd
import scipy.sparse as sp
from hca_anndata_tools.edit import (
    list_uns_fields,
    replace_placeholder_values,
    set_uns,
    view_edit_log,
)
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
    # study_pi is required but not in the test fixture
    assert "study_pi" in result["missing_required"]
    # bionetwork-only fields are in a separate list
    assert "ambient_count_correction" not in result["missing_required"]
    assert "ambient_count_correction" in result["missing_required_bionetwork"]


def test_list_uns_fields_filters_description(sample_h5ad_for_write):
    # Issue #343: LinkML's Dataset model marks `description` as a required uns
    # field, but it isn't one per HCA Tier 1 / CELLxGENE. helpers._SKIP_UNS_FIELDS
    # drops it from the registry so it's never surfaced as missing or settable.
    result = list_uns_fields(str(sample_h5ad_for_write))
    field_names = [f["name"] for f in result["fields"]]
    assert "description" not in field_names
    assert "description" not in result["missing_required"]


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
    result = set_uns(str(sample_h5ad_for_write), "title", "A test dataset")
    assert "error" not in result
    assert "output_path" in result

    written = ad.read_h5ad(result["output_path"])
    assert written.uns["title"] == "A test dataset"


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
    result = set_uns(str(sample_h5ad_for_write), "comments", "Logged edit")
    assert "error" not in result

    written = ad.read_h5ad(result["output_path"])
    log = json.loads(written.uns["provenance"][EDIT_LOG_KEY])
    assert len(log) == 1
    assert log[0]["operation"] == "set_uns"
    assert log[0]["details"]["field"] == "comments"
    assert log[0]["details"]["new_value"] == "Logged edit"


def test_set_uns_previous_value_in_details(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "title", "Updated")
    assert "error" not in result

    written = ad.read_h5ad(result["output_path"])
    log = json.loads(written.uns["provenance"][EDIT_LOG_KEY])
    assert log[0]["details"]["old_value"] == "Test Dataset"


def test_set_uns_output_in_same_dir(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "comments", "test")
    assert "error" not in result
    assert result["output_path"].startswith(str(sample_h5ad_for_write.parent))


def test_set_uns_bad_path():
    result = set_uns("/nonexistent/file.h5ad", "title", "test")
    assert "error" in result


# --- auto-resolve latest ---


def test_set_uns_auto_resolves_latest(sample_h5ad_for_write):
    """Passing the original path edits the latest timestamped version."""
    # First edit creates a timestamped copy
    r1 = set_uns(str(sample_h5ad_for_write), "title", "first edit")
    assert "error" not in r1

    # Second edit: pass original path, should auto-resolve to the timestamped version
    r2 = set_uns(str(sample_h5ad_for_write), "comments", "second edit")
    assert "error" not in r2

    # The second edit should have read from the first output (which has title updated)
    written = ad.read_h5ad(r2["output_path"])
    assert written.uns["title"] == "first edit"
    assert written.uns["comments"] == "second edit"


# --- empty value rejection ---

# ambient_count_correction is the only required str uns field without a
# Literal enum constraint, so it's the one field that exercises set_uns's
# required+str+empty code path (enum-typed fields fail Pydantic type
# validation before reaching the non-empty check).
def test_set_uns_empty_string_rejected(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "ambient_count_correction", "")
    assert "error" in result
    assert "non-empty" in result["error"]


def test_set_uns_whitespace_string_rejected(sample_h5ad_for_write):
    result = set_uns(str(sample_h5ad_for_write), "ambient_count_correction", "   ")
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
    result = set_uns(str(sample_h5ad_for_write), "title", ["not", "a", "string"])
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


# --- replace_placeholder_values ---


def _make_placeholder_h5ad(tmp_path, col_values, col_name="test_col"):
    """Create a test h5ad with a categorical column containing given values."""
    n = len(col_values)
    obs = pd.DataFrame(
        {col_name: pd.Categorical(col_values)},
        index=[f"cell_{i}" for i in range(n)],
    )
    adata = ad.AnnData(
        X=sp.csr_matrix((n, 2), dtype=np.float32),
        obs=obs,
    )
    path = tmp_path / "placeholders_test.h5ad"
    adata.write_h5ad(path)
    return path


def test_replace_placeholder_basic(tmp_path):
    path = _make_placeholder_h5ad(tmp_path, ["valid", "unknown", "valid", "na"])
    result = replace_placeholder_values(str(path), ["test_col"])
    assert "error" not in result
    assert result["total_cells_affected"] == 2
    assert "unknown" in result["columns_fixed"]["test_col"]
    assert "na" in result["columns_fixed"]["test_col"]

    written = ad.read_h5ad(result["output_path"])
    assert written.obs["test_col"].isna().sum() == 2
    assert (written.obs["test_col"].dropna() == "valid").all()


def test_replace_placeholder_case_insensitive(tmp_path):
    path = _make_placeholder_h5ad(tmp_path, ["valid", "Unknown", "NONE", "N/A"])
    result = replace_placeholder_values(str(path), ["test_col"])
    assert "error" not in result
    assert result["total_cells_affected"] == 3


def test_replace_placeholder_no_matches(tmp_path):
    path = _make_placeholder_h5ad(tmp_path, ["valid1", "valid2"])
    result = replace_placeholder_values(str(path), ["test_col"])
    assert "error" in result
    assert "No placeholder values" in result["error"]


def test_replace_placeholder_missing_column(tmp_path):
    path = _make_placeholder_h5ad(tmp_path, ["valid"])
    result = replace_placeholder_values(str(path), ["nonexistent"])
    assert "error" in result
    assert "not found" in result["error"]


def test_replace_placeholder_custom_placeholders(tmp_path):
    path = _make_placeholder_h5ad(tmp_path, ["valid", "banned", "also_banned"])
    result = replace_placeholder_values(str(path), ["test_col"], placeholders=["banned", "also_banned"])
    assert "error" not in result
    assert result["total_cells_affected"] == 2


def test_replace_placeholder_with_preexisting_nan(tmp_path):
    """Pre-existing NaN values are preserved alongside new replacements."""
    n = 5
    obs = pd.DataFrame(
        {"test_col": pd.Categorical(["valid", "unknown", np.nan, "na", "valid"])},
        index=[f"cell_{i}" for i in range(n)],
    )
    adata = ad.AnnData(X=sp.csr_matrix((n, 2), dtype=np.float32), obs=obs)
    path = tmp_path / "preexisting_nan.h5ad"
    adata.write_h5ad(path)

    result = replace_placeholder_values(str(path), ["test_col"])
    assert "error" not in result
    assert result["total_cells_affected"] == 2

    written = ad.read_h5ad(result["output_path"])
    assert written.obs["test_col"].isna().sum() == 3
    assert list(written.obs["test_col"].cat.categories) == ["valid"]
    # Verify per-cell: valid, NaN, NaN, NaN, valid
    vals = list(written.obs["test_col"])
    assert vals[0] == "valid"
    assert pd.isna(vals[1])  # was "unknown"
    assert pd.isna(vals[2])  # was NaN (pre-existing)
    assert pd.isna(vals[3])  # was "na"
    assert vals[4] == "valid"


def test_replace_placeholder_all_values_replaced(tmp_path):
    """Column where every value is a placeholder results in all NaN."""
    path = _make_placeholder_h5ad(tmp_path, ["unknown", "unknown", "na"])
    result = replace_placeholder_values(str(path), ["test_col"])
    assert "error" not in result
    assert result["total_cells_affected"] == 3

    written = ad.read_h5ad(result["output_path"])
    assert written.obs["test_col"].isna().all()
    assert len(written.obs["test_col"].cat.categories) == 0


def test_replace_placeholder_edit_log(tmp_path):
    path = _make_placeholder_h5ad(tmp_path, ["valid", "unknown"])
    result = replace_placeholder_values(str(path), ["test_col"])
    written = ad.read_h5ad(result["output_path"])
    log = json.loads(written.uns["provenance"][EDIT_LOG_KEY])
    assert len(log) >= 1
    assert log[-1]["operation"] == "replace_placeholder_values"


# --- view_edit_log ---


def test_view_edit_log_empty(sample_h5ad_for_write):
    """Unedited file returns edit_count 0 with a message."""
    result = view_edit_log(str(sample_h5ad_for_write))
    assert "error" not in result
    assert result["edit_count"] == 0
    assert result["entries"] == []
    assert "message" in result
    assert result["filename"] == sample_h5ad_for_write.name


def test_view_edit_log_after_edits(sample_h5ad_for_write):
    """After edits, entries are returned with operation and details."""
    set_uns(str(sample_h5ad_for_write), "comments", "first")
    set_uns(str(sample_h5ad_for_write), "title", "second")

    result = view_edit_log(str(sample_h5ad_for_write))
    assert "error" not in result
    assert result["edit_count"] == 2
    assert "message" not in result
    assert [e["operation"] for e in result["entries"]] == ["set_uns", "set_uns"]
    assert result["entries"][0]["details"]["field"] == "comments"
    assert result["entries"][1]["details"]["field"] == "title"
    assert all("timestamp" in e for e in result["entries"])
    assert all("source_sha256" in e for e in result["entries"])


def test_view_edit_log_auto_resolves_latest(sample_h5ad_for_write):
    """Passing the original path reads the latest timestamped version."""
    set_uns(str(sample_h5ad_for_write), "comments", "logged")
    result = view_edit_log(str(sample_h5ad_for_write))
    assert "error" not in result
    assert result["edit_count"] == 1
    assert result["filename"] != sample_h5ad_for_write.name  # resolved to timestamped


def test_view_edit_log_bad_path():
    result = view_edit_log("/nonexistent/file.h5ad")
    assert "error" in result
