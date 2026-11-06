"""
Test script for the HCA validator module.

This script demonstrates how to use the validator to validate HCA data.
"""

import json
from pathlib import Path

import hca_metadata_schema.generated.core as schema
import pytest
from pydantic import ValidationError

from hca_validation.schema_utils import get_entry_sheet_optional_slots
from hca_validation.schema_utils.schema_utils import schema_classes
from hca_validation.validator import validate

# Get the path to the test data directory
TEST_DIR = Path(__file__).parent / "data"
VALID_JSON_PATH = TEST_DIR / "valid_dataset.json"
INVALID_JSON_PATH = TEST_DIR / "invalid_dataset.json"
VOIBM_JSON_PATH = TEST_DIR / "valid_or_invalid_by_model_dataset.json"


@pytest.fixture
def valid_dataset():
    """Fixture to load the valid dataset."""
    with VALID_JSON_PATH.open() as f:
        return json.load(f)


@pytest.fixture
def invalid_dataset():
    """Fixture to load the invalid dataset."""
    with INVALID_JSON_PATH.open() as f:
        return json.load(f)


@pytest.fixture
def voibm_dataset():
    """Fixture to load the valid-or-invalid-by-model dataset."""
    with VOIBM_JSON_PATH.open() as f:
        return json.load(f)


def test_validate_valid_dataset(valid_dataset):
    """Test validation of a valid dataset."""
    # Validate the dataset
    validation_error = validate(valid_dataset, class_name="Dataset")

    # Assert that validation passed
    assert not validation_error, "Valid dataset should have no validation errors"


def test_validate_invalid_dataset(invalid_dataset):
    """Test validation of an invalid dataset."""
    # Validate the dataset
    validation_error = validate(invalid_dataset, class_name="Dataset")

    # Assert that validation failed
    assert validation_error, "Invalid dataset should have validation errors"

    # Assert specific errors are present
    error_fields = {e["loc"][0] for e in validation_error.errors()}

    # Check for specific validation errors
    assert "reference_genome" in error_fields, "Should have an error for reference_genome"
    assert "sequenced_fragment" in error_fields, "Should have an error for sequenced_fragment"


def test_validate_valid_or_invalid_by_model_dataset(voibm_dataset):
    """Test validation of a dataset that is valid for the default model but invalid for a network-specific model."""

    # Validate the dataset with the default model
    default_validation_error = validate(voibm_dataset, class_name="Dataset")

    # Assert that validation passed
    assert not default_validation_error, "Dataset should have no validation errors when validated with default model"

    # Validate the dataset with a network-specific model
    gut_validation_error = validate(voibm_dataset, class_name="GutDataset")

    # Assert that validation failed
    assert gut_validation_error, "Dataset should have validation errors when validation with network-specific model"

    # Assert specific errors are present
    gut_error_fields = {e["loc"][0] for e in gut_validation_error.errors()}

    # Check for specific validation errors
    assert "ambient_count_correction" in gut_error_fields, "Should have an error for ambient_count_correction"
    assert "doublet_detection" in gut_error_fields, "Should have an error for doublet_detection"


# `study_pi`, a required Dataset slot, stands in for a tagged one, keeping these mechanism tests off the real schema.
RELAXED = frozenset({"study_pi"})


@pytest.mark.parametrize("blank", ["absent", "None"])
def test_entry_sheet_optional_slot_may_be_absent_or_blank(valid_dataset, blank):
    row = {key: value for key, value in valid_dataset.items() if key != "study_pi"}
    if blank == "None":
        row["study_pi"] = None
    assert validate(row, class_name="Dataset", entry_sheet_optional=RELAXED) is None


def test_entry_sheet_optional_slot_still_rejects_an_invalid_value(valid_dataset):
    row = {**valid_dataset, "study_pi": "not a list"}
    validation_error = validate(row, class_name="Dataset", entry_sheet_optional=RELAXED)
    assert validation_error is not None
    assert [e["loc"] for e in validation_error.errors()] == [("study_pi",)]


def test_entry_sheet_optional_slot_leaves_other_errors_unchanged(valid_dataset):
    row = {key: value for key, value in valid_dataset.items() if key not in ("study_pi", "alignment_software")}
    row["reference_genome"] = "nope"
    validation_error = validate(row, class_name="Dataset", entry_sheet_optional=RELAXED)
    errors = [(e["type"], e["loc"], e["msg"]) for e in validation_error.errors()]
    assert ("missing", ("alignment_software",), "Field required") in errors
    assert any(loc == ("reference_genome",) and kind == "enum" for kind, loc, _ in errors)
    assert all(loc != ("study_pi",) for _, loc, _ in errors)


def test_unannotated_required_slot_still_fails_when_absent(valid_dataset):
    row = {key: value for key, value in valid_dataset.items() if key != "study_pi"}
    validation_error = validate(row, class_name="Dataset")
    assert validation_error is not None
    assert [(e["type"], e["loc"]) for e in validation_error.errors()] == [("missing", ("study_pi",))]


DATASET_CLASSES = sorted(schema_classes["dataset"].values())


@pytest.mark.parametrize("class_name", DATASET_CLASSES)
@pytest.mark.parametrize("blank", ["absent", "None"])
def test_entry_sheet_dataset_row_may_omit_title(schemaview, valid_dataset, class_name, blank):
    """#836: `title` is required for h5ad files but tagged `entrySheetRequired: false`, so a sheet row may omit it."""
    row = {key: value for key, value in valid_dataset.items() if key != "title"}
    if blank == "None":
        row["title"] = None
    optional = get_entry_sheet_optional_slots(schemaview, class_name)
    errors = validate(row, class_name=class_name, entry_sheet_optional=optional)
    if class_name == "Dataset":
        assert errors is None
    else:
        # Network classes also fail on their own required slots, which the fixture leaves out; only title matters here.
        assert errors is None or all(e["loc"] != ("title",) for e in errors.errors())


@pytest.mark.parametrize("class_name", DATASET_CLASSES)
def test_dataset_model_requires_title(valid_dataset, class_name):
    """#836: outside entry sheets, building a Dataset model without `title` fails."""
    row = {key: value for key, value in valid_dataset.items() if key != "title"}
    with pytest.raises(ValidationError) as excinfo:
        getattr(schema, class_name).model_validate(row)
    assert ("missing", ("title",)) in [(e["type"], e["loc"]) for e in excinfo.value.errors()]
