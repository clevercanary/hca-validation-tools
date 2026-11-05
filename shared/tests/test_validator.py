"""
Test script for the HCA validator module.

This script demonstrates how to use the validator to validate HCA data.
"""

import json
from pathlib import Path

import pytest

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


# `study_pi`, a required Dataset slot, stands in for one tagged `entrySheetRequired: false`; no real slot is tagged yet.
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


def test_rebuilt_errors_keep_custom_error_messages():
    """A filtered ValidationError is rebuilt; a PydanticCustomError type must survive with its rendered message."""
    from pydantic import BaseModel, ValidationError, field_validator
    from pydantic_core import PydanticCustomError

    from hca_validation.validator.validator import _line_error

    class Model(BaseModel):
        a: str

        @field_validator("a")
        @classmethod
        def reject(cls, value):
            raise PydanticCustomError("custom_type", "bad {thing}, pattern \\d{{1,3}}", {"thing": value})

    with pytest.raises(ValidationError) as excinfo:
        Model(a="x")
    [original] = excinfo.value.errors()
    [rebuilt] = ValidationError.from_exception_data("Model", [_line_error(original)]).errors()
    assert (rebuilt["type"], rebuilt["loc"], rebuilt["msg"]) == (original["type"], original["loc"], original["msg"])
    assert "{" in original["msg"]
