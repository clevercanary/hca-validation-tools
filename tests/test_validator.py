"""
Test script for the HCA validator module.

This script demonstrates how to use the validator to validate HCA data.
"""
import json
import os
from pathlib import Path

import pytest

from hca_validation.validator import validate

# Get the path to the test data directory
TEST_DIR = Path(__file__).parent / "data"
VALID_JSON_PATH = TEST_DIR / "valid_dataset.json"
INVALID_JSON_PATH = TEST_DIR / "invalid_dataset.json"


@pytest.fixture
def valid_dataset():
    """Fixture to load the valid dataset."""
    with open(VALID_JSON_PATH, 'r') as f:
        return json.load(f)


@pytest.fixture
def invalid_dataset():
    """Fixture to load the invalid dataset."""
    with open(INVALID_JSON_PATH, 'r') as f:
        return json.load(f)


def test_validate_valid_dataset(valid_dataset):
    """Test validation of a valid dataset."""
    # Validate the dataset
    validation_error = validate(valid_dataset, schema_type="dataset")

    # Assert that validation passed
    assert not validation_error, "Valid dataset should have no validation errors"


def test_validate_invalid_dataset(invalid_dataset):
    """Test validation of an invalid dataset."""
    # Validate the dataset
    validation_error = validate(invalid_dataset, schema_type="dataset")

    # Assert that validation failed
    assert validation_error, "Invalid dataset should have validation errors"

    # Assert specific errors are present
    error_fields = {e["loc"][0] for e in validation_error.errors()}

    # Check for specific validation errors
    assert "reference_genome" in error_fields, "Should have an error for reference_genome"
    assert "sequenced_fragment" in error_fields, "Should have an error for sequenced_fragment"

