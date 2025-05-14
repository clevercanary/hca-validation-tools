"""
Test script for the HCA validator module.

This script demonstrates how to use the validator to validate HCA data.
"""
import json
import os
from pathlib import Path

import pytest

from hca_validation.validator import validate, clear_cache

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
    report = validate(valid_dataset, schema_type="dataset")

    # Assert that validation passed
    assert not report.results, "Valid dataset should have no validation errors"


def test_validate_invalid_dataset(invalid_dataset):
    """Test validation of an invalid dataset."""
    # Validate the dataset
    report = validate(invalid_dataset, schema_type="dataset")

    # Assert that validation failed
    assert report.results, "Invalid dataset should have validation errors"

    # Assert specific errors are present
    error_messages = [result.message for result in report.results]
    error_text = '\n'.join(error_messages)

    # Check for specific validation errors
    assert "reference_genome" in error_text, "Should have an error for reference_genome"
    assert "sequenced_fragment" in error_text, "Should have an error for sequenced_fragment"


def test_validator_caching(valid_dataset):
    """Test that the validator is cached properly."""
    # Clear the cache to start fresh
    clear_cache()
    
    # First validation call should create a new validator
    report1 = validate(valid_dataset, schema_type="dataset")
    assert not report1.results, "First validation should pass"
    
    # Second validation call should use the cached validator
    report2 = validate(valid_dataset, schema_type="dataset")
    assert not report2.results, "Second validation should pass"
    
    # Clear the cache
    clear_cache()
    
    # Third validation call should create a new validator again
    report3 = validate(valid_dataset, schema_type="dataset")
    assert not report3.results, "Third validation should pass"
    
    # We can't directly test that caching works from the outside,
    # but we can verify that clearing the cache and revalidating still works
