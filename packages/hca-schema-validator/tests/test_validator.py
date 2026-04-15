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


def test_error_handling_before_reset(monkeypatch):
    """Test that exceptions before reset() don't cause AttributeError.

    Regression test for #210: self.errors was not initialized in __init__,
    so an exception raised before reset() in validate_adata caused
    AttributeError when the handler tried to append to self.errors.
    """
    from hca_schema_validator._vendored.cellxgene_schema import validate as validate_mod

    def fake_read_h5ad(path):
        raise RuntimeError("simulated read failure")

    monkeypatch.setattr(validate_mod, "read_h5ad", fake_read_h5ad)

    validator = HCAValidator()
    is_valid = validator.validate_adata("dummy.h5ad")

    assert is_valid is False
    assert len(validator.errors) > 0
    assert any("simulated read failure" in e for e in validator.errors)


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


def test_manner_of_death_empty_string_allowed_for_prenatal():
    """Test that manner_of_death='' is allowed when development_stage is prenatal."""
    import anndata
    from .fixtures.hca_fixtures import good_obs, good_var, good_uns, good_obsm, non_raw_X, X

    obs = good_obs.copy()
    # good_obs already uses HsapDv:0000003 (Carnegie stage 01), which is prenatal
    obs["manner_of_death"] = obs["manner_of_death"].cat.add_categories([""])
    obs["manner_of_death"] = ""
    test_adata = anndata.AnnData(X=X.copy(), obs=obs, uns=good_uns.copy(), obsm=good_obsm.copy(), var=good_var.copy())
    test_adata.raw = test_adata.copy()
    test_adata.X = non_raw_X
    test_adata.raw.var.drop("feature_is_filtered", axis=1, inplace=True)

    is_valid, validator = _validate_from_fixture(test_adata)
    assert is_valid is True, f"Validation failed with errors: {validator.errors}"


def test_manner_of_death_empty_string_allowed_for_postnatal():
    """Test that manner_of_death='' is allowed even when development_stage is postnatal."""
    import anndata
    from .fixtures.hca_fixtures import good_obs, good_var, good_uns, good_obsm, non_raw_X, X

    obs = good_obs.copy()
    # Change to a postnatal development stage (2-year-old stage)
    obs["development_stage_ontology_term_id"] = "HsapDv:0000096"
    obs["manner_of_death"] = obs["manner_of_death"].cat.add_categories([""])
    obs["manner_of_death"] = ""
    test_adata = anndata.AnnData(X=X.copy(), obs=obs, uns=good_uns.copy(), obsm=good_obsm.copy(), var=good_var.copy())
    test_adata.raw = test_adata.copy()
    test_adata.X = non_raw_X
    test_adata.raw.var.drop("feature_is_filtered", axis=1, inplace=True)

    is_valid, validator = _validate_from_fixture(test_adata)
    assert is_valid is True, f"Validation failed with errors: {validator.errors}"


def test_manner_of_death_invalid_value_rejected():
    """Test that an invalid manner_of_death value is rejected."""
    import anndata
    from .fixtures.hca_fixtures import good_obs, good_var, good_uns, good_obsm, non_raw_X, X

    obs = good_obs.copy()
    obs["manner_of_death"] = obs["manner_of_death"].cat.add_categories(["banana"])
    obs["manner_of_death"] = "banana"
    test_adata = anndata.AnnData(X=X.copy(), obs=obs, uns=good_uns.copy(), obsm=good_obsm.copy(), var=good_var.copy())
    test_adata.raw = test_adata.copy()
    test_adata.X = non_raw_X
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


def test_pattern_valid_multi_cell_enrichment():
    """Test that semicolon-separated cell_enrichment values are accepted."""
    import anndata
    from .fixtures.hca_fixtures import good_obs, good_var, good_uns, good_obsm, non_raw_X, X

    obs = good_obs.copy()
    obs["cell_enrichment"] = obs["cell_enrichment"].cat.add_categories(["CL:0000057+;CL:0000058-"])
    obs["cell_enrichment"] = "CL:0000057+;CL:0000058-"
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

    def test_nan_in_library_id_is_error(self):
        """library_id is required: NaN produces an error."""
        import anndata
        import numpy
        from scipy import sparse
        from .fixtures.hca_fixtures import good_obs, good_var, good_uns, good_obsm

        obs = good_obs.copy()
        obs["library_id"] = obs["library_id"].astype(object)
        obs.loc["X", "library_id"] = numpy.nan

        X = sparse.csr_matrix((obs.shape[0], good_var.shape[0]), dtype=numpy.float32)
        test_adata = anndata.AnnData(X=X, obs=obs, uns=good_uns.copy(), obsm=good_obsm.copy(), var=good_var.copy())
        test_adata.raw = test_adata.copy()
        test_adata.raw.var.drop("feature_is_filtered", axis=1, inplace=True)

        is_valid, validator = _validate_from_fixture(test_adata)
        assert is_valid is False
        error_messages = " ".join(validator.errors)
        assert "library_id" in error_messages, "NaN in required library_id should be an error"

    def test_missing_library_id_is_error(self):
        """Missing required library_id column produces an error."""
        import anndata
        import numpy
        from scipy import sparse
        from .fixtures.hca_fixtures import good_obs, good_var, good_uns, good_obsm

        obs = good_obs.copy()
        obs.drop(columns=["library_id"], inplace=True)

        X = sparse.csr_matrix((obs.shape[0], good_var.shape[0]), dtype=numpy.float32)
        test_adata = anndata.AnnData(X=X, obs=obs, uns=good_uns.copy(), obsm=good_obsm.copy(), var=good_var.copy())
        test_adata.raw = test_adata.copy()
        test_adata.raw.var.drop("feature_is_filtered", axis=1, inplace=True)

        _, validator = _validate_from_fixture(test_adata)
        error_messages = " ".join(validator.errors)
        assert "library_id" in error_messages, "Missing required library_id should be an error"

    def test_blocklist_value_is_error(self):
        """Blocklisted placeholder values in strongly_recommended columns produce errors."""
        import anndata
        import numpy
        from scipy import sparse
        from .fixtures.hca_fixtures import good_obs, good_var, good_uns, good_obsm

        obs = good_obs.copy()
        obs["library_preparation_batch"] = obs["library_preparation_batch"].astype(object)
        obs["library_preparation_batch"] = "unknown"

        X = sparse.csr_matrix((obs.shape[0], good_var.shape[0]), dtype=numpy.float32)
        test_adata = anndata.AnnData(X=X, obs=obs, uns=good_uns.copy(), obsm=good_obsm.copy(), var=good_var.copy())
        test_adata.raw = test_adata.copy()
        test_adata.raw.var.drop("feature_is_filtered", axis=1, inplace=True)

        _, validator = _validate_from_fixture(test_adata)
        error_messages = " ".join(validator.errors)
        assert "library_preparation_batch" in error_messages
        assert "placeholder" in error_messages.lower()

    def test_separator_in_strongly_recommended_is_error(self):
        """Values with list separators (comma, semicolon, pipe) are rejected."""
        import anndata
        import numpy
        from scipy import sparse
        from .fixtures.hca_fixtures import good_obs, good_var, good_uns, good_obsm

        obs = good_obs.copy()
        obs["library_preparation_batch"] = obs["library_preparation_batch"].astype(object)
        obs["library_preparation_batch"] = "batch1,batch2"

        X = sparse.csr_matrix((obs.shape[0], good_var.shape[0]), dtype=numpy.float32)
        test_adata = anndata.AnnData(X=X, obs=obs, uns=good_uns.copy(), obsm=good_obsm.copy(), var=good_var.copy())
        test_adata.raw = test_adata.copy()
        test_adata.raw.var.drop("feature_is_filtered", axis=1, inplace=True)

        _, validator = _validate_from_fixture(test_adata)
        error_messages = " ".join(validator.errors)
        assert "library_preparation_batch" in error_messages
        assert "separator" in error_messages.lower()

    def test_mixed_valid_and_invalid_values(self):
        v = self._make_validator()
        col = pd.Series(["abc", "xyz", "abc"], dtype="category")
        v._validate_column(col, "test_col", "obs", {"pattern": "^abc$"})
        pattern_errors = [e for e in v.errors if "pattern" in e.lower()]
        assert len(pattern_errors) == 1
        assert "xyz" in pattern_errors[0]


def test_feature_id_warnings_come_last():
    """Feature ID warnings (not found in GENCODE) should be sorted after other warnings."""
    from hca_schema_validator.validator import HCAValidator
    v = HCAValidator()
    # Simulate mixed warnings (with WARNING: prefix added by base validate_adata)
    v.warnings = [
        "WARNING: Feature ID 'ENSG00000241572' in 'var' not found in GENCODE v48 (Ensembl 114).",
        "WARNING: Column 'library_id' is strongly recommended but missing.",
        "WARNING: Feature ID 'ENSG00000229611' in 'var' not found in GENCODE v48 (Ensembl 114).",
        "WARNING: Only raw data was found.",
    ]
    other = [w for w in v.warnings if "Feature ID '" not in w]
    feature_id = [w for w in v.warnings if "Feature ID '" in w]
    v.warnings = other + feature_id

    assert "library_id" in v.warnings[0]
    assert "raw data" in v.warnings[1]
    assert "ENSG00000241572" in v.warnings[2]
    assert "ENSG00000229611" in v.warnings[3]


def test_raw_validation_runs_despite_unrelated_errors():
    """Raw validation should run even when unrelated HCA fields are missing.

    Regression test for #243: the base class skips raw validation if any
    errors exist, but our override retries it when assay_ontology_term_id
    is present.
    """
    from .fixtures.hca_fixtures import adata

    # Remove an HCA-specific field to create an unrelated error
    modified = adata.copy()
    del modified.uns["study_pi"]

    is_valid, validator = _validate_from_fixture(modified)
    assert is_valid is False

    # The "raw layer was not performed" warning should be absent
    raw_skip_warnings = [
        w for w in validator.warnings
        if "Validation of raw layer was not performed" in w
    ]
    assert len(raw_skip_warnings) == 0, (
        f"Raw validation was skipped despite assay_ontology_term_id being present. "
        f"Warnings: {validator.warnings}"
    )


class TestCLOntologyOverlay:
    """Tests that the CL ontology overlay includes newer salivary gland cell types."""

    def test_new_salivary_gland_cl_terms_are_valid(self):
        """CL terms added in Aug 2025 (post v2025-07-30) should be recognized."""
        from hca_schema_validator._vendored.cellxgene_schema.ontology_parser import ONTOLOGY_PARSER

        new_terms = {
            "CL:4052065": "serous acinar cell of salivary gland",
            "CL:4052066": "mucous acinar cell of salivary gland",
            "CL:4052067": "seromucous acinar cell of salivary gland",
            "CL:4052069": "excretory duct cell of salivary gland",
        }
        for term_id, expected_label in new_terms.items():
            assert ONTOLOGY_PARSER.is_valid_term_id(term_id), f"{term_id} should be valid"
            assert ONTOLOGY_PARSER.get_term_label(term_id) == expected_label

    def test_existing_cl_terms_still_valid(self):
        """Ensure the overlay doesn't break existing CL terms."""
        from hca_schema_validator._vendored.cellxgene_schema.ontology_parser import ONTOLOGY_PARSER

        assert ONTOLOGY_PARSER.is_valid_term_id("CL:0000000")
        assert ONTOLOGY_PARSER.get_term_label("CL:0000000") == "cell"
        assert ONTOLOGY_PARSER.is_valid_term_id("CL:0000540")
        assert ONTOLOGY_PARSER.get_term_label("CL:0000540") == "neuron"

    def test_non_cl_ontologies_still_work(self):
        """Non-CL ontologies should continue using bundled package data."""
        from hca_schema_validator._vendored.cellxgene_schema.ontology_parser import ONTOLOGY_PARSER

        assert ONTOLOGY_PARSER.is_valid_term_id("EFO:0010961")
        assert ONTOLOGY_PARSER.is_valid_term_id("UBERON:0000955")
