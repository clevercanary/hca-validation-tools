"""Tests for HCA Validator."""

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from hca_schema_validator import HCAValidator

# Test fixtures directory
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "h5ads"


def _validate_from_fixture(adata):
    """Write adata to a temp file and validate it, returning (is_valid, validator)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / "test.h5ad"
        adata.write_h5ad(str(tmp_path))
        validator = HCAValidator()
        is_valid = validator.validate_adata(str(tmp_path))
        return is_valid, validator


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


def test_valid_adata_passes():
    """Test that the full valid adata fixture (with all new fields) passes validation."""
    from .fixtures.hca_fixtures import adata

    is_valid, validator = _validate_from_fixture(adata)
    assert is_valid is True, f"Validation failed with errors: {validator.errors}"


def test_study_pi_missing():
    """Test that removing study_pi from uns produces an error."""
    import anndata
    from .fixtures.hca_fixtures import adata

    modified = adata.copy()
    del modified.uns["study_pi"]
    is_valid, validator = _validate_from_fixture(modified)
    assert is_valid is False
    error_messages = " ".join(validator.errors)
    assert "study_pi" in error_messages


def test_study_pi_empty_list():
    """Test that an empty study_pi list produces an error."""
    import anndata
    from .fixtures.hca_fixtures import adata

    modified = adata.copy()
    modified.uns["study_pi"] = []
    is_valid, validator = _validate_from_fixture(modified)
    assert is_valid is False
    error_messages = " ".join(validator.errors)
    assert "study_pi" in error_messages


def test_study_pi_non_string_element():
    """Test that a non-string element in study_pi produces an error."""
    import anndata
    from .fixtures.hca_fixtures import adata

    modified = adata.copy()
    modified.uns["study_pi"] = [123]
    is_valid, validator = _validate_from_fixture(modified)
    assert is_valid is False
    error_messages = " ".join(validator.errors)
    assert "study_pi" in error_messages
    assert "string" in error_messages.lower()


def test_missing_required_obs_column():
    """Test that dropping a required new obs column produces an error."""
    import anndata
    import numpy
    from scipy import sparse
    from .fixtures.hca_fixtures import good_obs, good_var, good_uns, good_obsm

    obs = good_obs.copy()
    obs = obs.drop(columns=["sample_id"])
    X = sparse.csr_matrix((obs.shape[0], good_var.shape[0]), dtype=numpy.float32)
    test_adata = anndata.AnnData(X=X, obs=obs, uns=good_uns.copy(), obsm=good_obsm.copy(), var=good_var.copy())
    test_adata.raw = test_adata.copy()
    test_adata.raw.var.drop("feature_is_filtered", axis=1, inplace=True)

    is_valid, validator = _validate_from_fixture(test_adata)
    assert is_valid is False
    error_messages = " ".join(validator.errors)
    assert "sample_id" in error_messages


def test_enum_invalid_value():
    """Test that an invalid enum value for manner_of_death produces an error."""
    import anndata
    import numpy
    from scipy import sparse
    from .fixtures.hca_fixtures import good_obs, good_var, good_uns, good_obsm

    obs = good_obs.copy()
    obs["manner_of_death"] = obs["manner_of_death"].cat.add_categories(["invalid_value"])
    obs["manner_of_death"] = "invalid_value"
    X = sparse.csr_matrix((obs.shape[0], good_var.shape[0]), dtype=numpy.float32)
    test_adata = anndata.AnnData(X=X, obs=obs, uns=good_uns.copy(), obsm=good_obsm.copy(), var=good_var.copy())
    test_adata.raw = test_adata.copy()
    test_adata.raw.var.drop("feature_is_filtered", axis=1, inplace=True)

    is_valid, validator = _validate_from_fixture(test_adata)
    assert is_valid is False
    error_messages = " ".join(validator.errors)
    assert "manner_of_death" in error_messages


def test_pattern_invalid_cell_enrichment():
    """Test that an invalid cell_enrichment value not matching pattern produces an error."""
    import anndata
    import numpy
    from scipy import sparse
    from .fixtures.hca_fixtures import good_obs, good_var, good_uns, good_obsm

    obs = good_obs.copy()
    obs["cell_enrichment"] = obs["cell_enrichment"].cat.add_categories(["INVALID"])
    obs["cell_enrichment"] = "INVALID"
    X = sparse.csr_matrix((obs.shape[0], good_var.shape[0]), dtype=numpy.float32)
    test_adata = anndata.AnnData(X=X, obs=obs, uns=good_uns.copy(), obsm=good_obsm.copy(), var=good_var.copy())
    test_adata.raw = test_adata.copy()
    test_adata.raw.var.drop("feature_is_filtered", axis=1, inplace=True)

    is_valid, validator = _validate_from_fixture(test_adata)
    assert is_valid is False
    error_messages = " ".join(validator.errors)
    assert "cell_enrichment" in error_messages
    assert "not valid" in error_messages.lower()
    assert "cell ontology" in error_messages.lower()


def test_pattern_invalid_gene_annotation_version():
    """Test that gene_annotation_version 'v50' does not match the version pattern."""
    import anndata
    import numpy
    from scipy import sparse
    from .fixtures.hca_fixtures import good_obs, good_var, good_uns, good_obsm

    obs = good_obs.copy()
    obs["gene_annotation_version"] = obs["gene_annotation_version"].cat.add_categories(["v50"])
    obs["gene_annotation_version"] = "v50"
    X = sparse.csr_matrix((obs.shape[0], good_var.shape[0]), dtype=numpy.float32)
    test_adata = anndata.AnnData(X=X, obs=obs, uns=good_uns.copy(), obsm=good_obsm.copy(), var=good_var.copy())
    test_adata.raw = test_adata.copy()
    test_adata.raw.var.drop("feature_is_filtered", axis=1, inplace=True)

    is_valid, validator = _validate_from_fixture(test_adata)
    assert is_valid is False
    error_messages = " ".join(validator.errors)
    assert "gene_annotation_version" in error_messages
    assert "not valid" in error_messages.lower()
    assert "gencode" in error_messages.lower()


def test_pattern_valid_na_cell_enrichment():
    """Test that 'na' is a valid value for cell_enrichment (matches pattern)."""
    import anndata
    from .fixtures.hca_fixtures import good_obs, good_var, good_uns, good_obsm, non_raw_X, X

    obs = good_obs.copy()
    obs["cell_enrichment"] = obs["cell_enrichment"].cat.add_categories(["na"])
    obs["cell_enrichment"] = "na"
    test_adata = anndata.AnnData(X=X.copy(), obs=obs, uns=good_uns.copy(), obsm=good_obsm.copy(), var=good_var.copy())
    test_adata.raw = test_adata.copy()
    test_adata.X = non_raw_X
    test_adata.raw.var.drop("feature_is_filtered", axis=1, inplace=True)

    is_valid, validator = _validate_from_fixture(test_adata)
    assert is_valid is True, f"Validation failed with errors: {validator.errors}"


def test_pattern_rejects_cell_enrichment_with_trailing_garbage():
    """Test that cell_enrichment rejects a valid prefix with trailing characters."""
    import anndata
    import numpy
    from scipy import sparse
    from .fixtures.hca_fixtures import good_obs, good_var, good_uns, good_obsm

    obs = good_obs.copy()
    obs["cell_enrichment"] = obs["cell_enrichment"].cat.add_categories(["CL:0000066+garbage"])
    obs["cell_enrichment"] = "CL:0000066+garbage"
    X = sparse.csr_matrix((obs.shape[0], good_var.shape[0]), dtype=numpy.float32)
    test_adata = anndata.AnnData(X=X, obs=obs, uns=good_uns.copy(), obsm=good_obsm.copy(), var=good_var.copy())
    test_adata.raw = test_adata.copy()
    test_adata.raw.var.drop("feature_is_filtered", axis=1, inplace=True)

    is_valid, validator = _validate_from_fixture(test_adata)
    assert is_valid is False
    error_messages = " ".join(validator.errors)
    assert "cell_enrichment" in error_messages
    assert "not valid" in error_messages.lower()


def test_pattern_rejects_gene_annotation_version_with_trailing_garbage():
    """Test that gene_annotation_version rejects a valid prefix with trailing characters."""
    import anndata
    import numpy
    from scipy import sparse
    from .fixtures.hca_fixtures import good_obs, good_var, good_uns, good_obsm

    obs = good_obs.copy()
    obs["gene_annotation_version"] = obs["gene_annotation_version"].cat.add_categories(["v101xyz"])
    obs["gene_annotation_version"] = "v101xyz"
    X = sparse.csr_matrix((obs.shape[0], good_var.shape[0]), dtype=numpy.float32)
    test_adata = anndata.AnnData(X=X, obs=obs, uns=good_uns.copy(), obsm=good_obsm.copy(), var=good_var.copy())
    test_adata.raw = test_adata.copy()
    test_adata.raw.var.drop("feature_is_filtered", axis=1, inplace=True)

    is_valid, validator = _validate_from_fixture(test_adata)
    assert is_valid is False
    error_messages = " ".join(validator.errors)
    assert "gene_annotation_version" in error_messages
    assert "not valid" in error_messages.lower()


# ---------------------------------------------------------------------------
# Direct unit tests for _validate_list and _validate_column overrides
# ---------------------------------------------------------------------------

class TestValidateList:
    """Direct unit tests for HCAValidator._validate_list with element_type 'string'."""

    def _make_validator(self):
        validator = HCAValidator()
        validator.errors = []
        return validator

    def test_valid_strings_no_errors(self):
        v = self._make_validator()
        v._validate_list("study_pi", ["Smith, Jane", "Doe, John"], "string")
        assert v.errors == []

    def test_non_string_element_produces_error(self):
        v = self._make_validator()
        v._validate_list("study_pi", [123], "string")
        assert len(v.errors) == 1
        assert "123" in v.errors[0]
        assert "string" in v.errors[0].lower()

    def test_empty_string_element_produces_error(self):
        v = self._make_validator()
        v._validate_list("study_pi", [""], "string")
        assert len(v.errors) == 1
        assert "empty" in v.errors[0].lower() or "whitespace" in v.errors[0].lower()

    def test_whitespace_only_element_produces_error(self):
        v = self._make_validator()
        v._validate_list("study_pi", ["   "], "string")
        assert len(v.errors) == 1
        assert "whitespace" in v.errors[0].lower()

    def test_multiple_bad_elements_produce_multiple_errors(self):
        v = self._make_validator()
        v._validate_list("study_pi", [42, "", "  "], "string")
        assert len(v.errors) == 3

    def test_non_string_element_type_ignored(self):
        """element_type values other than 'string' should not trigger string checks."""
        v = self._make_validator()
        # Use an unknown element_type that won't trigger the base class adata access
        v._validate_list("some_list", [123], "other_type")
        string_errors = [e for e in v.errors if "must be a string" in e]
        assert string_errors == []


class TestValidateColumn:
    """Direct unit tests for HCAValidator._validate_column with pattern support."""

    def _make_validator(self):
        validator = HCAValidator()
        validator.errors = []
        return validator

    def test_matching_values_no_errors(self):
        v = self._make_validator()
        col = pd.Series(["abc", "abc"], dtype="category")
        v._validate_column(col, "test_col", "obs", {"pattern": "^abc$"})
        assert v.errors == []

    def test_non_matching_value_produces_error(self):
        v = self._make_validator()
        col = pd.Series(["xyz", "xyz"], dtype="category")
        v._validate_column(col, "test_col", "obs", {"pattern": "^abc$"})
        pattern_errors = [e for e in v.errors if "pattern" in e.lower()]
        assert len(pattern_errors) == 1
        assert "test_col" in pattern_errors[0]
        assert "xyz" in pattern_errors[0]

    def test_nan_values_skipped(self):
        v = self._make_validator()
        col = pd.Series([np.nan, "abc"], dtype="object")
        v._validate_column(col, "test_col", "obs", {"pattern": "^abc$"})
        pattern_errors = [e for e in v.errors if "pattern" in e.lower()]
        assert pattern_errors == []

    def test_column_def_without_pattern_no_pattern_errors(self):
        """A column_def with no 'pattern' key should not trigger pattern checks."""
        v = self._make_validator()
        col = pd.Series(["anything", "anything"], dtype="category")
        v._validate_column(col, "test_col", "obs", {"type": "categorical"})
        pattern_errors = [e for e in v.errors if "pattern" in e.lower()]
        assert pattern_errors == []

    def test_mixed_valid_and_invalid_values(self):
        v = self._make_validator()
        col = pd.Series(["abc", "xyz", "abc"], dtype="category")
        v._validate_column(col, "test_col", "obs", {"pattern": "^abc$"})
        pattern_errors = [e for e in v.errors if "pattern" in e.lower()]
        assert len(pattern_errors) == 1
        assert "xyz" in pattern_errors[0]
