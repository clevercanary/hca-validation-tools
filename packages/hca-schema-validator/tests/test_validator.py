"""Tests for HCA Validator."""

import tempfile
from pathlib import Path

import pytest
from hca_schema_validator import HCAValidator

# Test fixtures directory
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "h5ads"


def test_import():
    """Test that HCAValidator can be imported."""
    assert HCAValidator is not None


def test_instantiate():
    """Test that HCAValidator can be instantiated."""
    validator = HCAValidator()
    assert validator is not None
    assert hasattr(validator, 'validate_adata')


def test_inheritance():
    """Test that HCAValidator inherits from Validator."""
    from hca_schema_validator._vendored.cellxgene_schema.validate import Validator
    
    validator = HCAValidator()
    assert isinstance(validator, Validator)


def test_has_validation_methods():
    """Test that HCAValidator has expected validation methods."""
    validator = HCAValidator()
    
    # Public methods
    assert hasattr(validator, 'validate_adata')
    
    # Protected methods (can override later)
    assert hasattr(validator, '_deep_check')
    assert hasattr(validator, '_validate_feature_ids')
    assert hasattr(validator, '_set_schema_def')


def test_validate_valid_h5ad():
    """
    Test validation of a CELLxGENE v6+ h5ad file.
    
    This test verifies that HCA schema correctly rejects CELLxGENE v6+ files
    that have organism in uns instead of obs.
    """
    test_file = FIXTURES_DIR / "example_valid.h5ad"
    
    if not test_file.exists():
        pytest.skip(f"Test fixture not found: {test_file}")
    
    validator = HCAValidator()
    is_valid = validator.validate_adata(str(test_file))
    
    # Should FAIL validation because CELLxGENE v6+ files have organism in uns,
    # but HCA schema requires it in obs
    assert is_valid is False
    assert len(validator.errors) > 0
    # Should have an error about missing organism_ontology_term_id in obs
    error_messages = " ".join(validator.errors)
    assert "organism_ontology_term_id" in error_messages.lower()


def test_validate_invalid_h5ad():
    """Test validation of an invalid h5ad file."""
    test_file = FIXTURES_DIR / "example_invalid_CL.h5ad"
    
    if not test_file.exists():
        pytest.skip(f"Test fixture not found: {test_file}")
    
    validator = HCAValidator()
    is_valid = validator.validate_adata(str(test_file))
    
    # Should fail validation
    assert is_valid is False
    assert len(validator.errors) > 0


def test_organism_in_obs():
    """
    Test that HCA schema accepts organism_ontology_term_id in obs.
    
    This is the HCA requirement - organism fields should be in obs, not uns
    (reverting the CELLxGENE v6 change that moved them to uns).
    """
    from .fixtures.hca_fixtures import adata
    
    # Use TemporaryDirectory for automatic cleanup
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / "test.h5ad"
        adata.write_h5ad(str(tmp_path))
        
        validator = HCAValidator()
        is_valid = validator.validate_adata(str(tmp_path))
        
        # HCA requirement: Should accept organism_ontology_term_id in obs
        assert is_valid is True, f"Validation failed with errors: {validator.errors}"
        
        # Should not have errors about organism being deprecated in obs
        for error in validator.errors:
            assert not ("organism" in error.lower() and "deprecated" in error.lower()), \
                "organism_ontology_term_id should not be deprecated in obs for HCA schema"
