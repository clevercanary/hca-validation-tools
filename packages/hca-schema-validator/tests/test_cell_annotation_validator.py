"""Tests for HCACellAnnotationValidator (Phase 1 structural checks)."""

from __future__ import annotations

import anndata as ad
import pytest

from hca_schema_validator import HCACellAnnotationValidator
from hca_schema_validator.cell_annotation_validator import (
    LEGACY_LAYOUT_ERROR,
    NO_SETS_ERROR,
)
from hca_schema_validator.testing import create_cap_annotated_h5ad


@pytest.fixture
def cap_h5ad(tmp_path):
    return create_cap_annotated_h5ad(tmp_path / "cap.h5ad")


def _rewrite(path, mutate):
    adata = ad.read_h5ad(path)
    mutate(adata)
    adata.write_h5ad(path)
    return path


def _mutate_cap(adata, fn):
    """Apply ``fn`` to a copy of uns['cap_metadata'] and reassign it.

    Reassigning (rather than mutating in place) guarantees the change persists
    through ``write_h5ad``.
    """
    cap = dict(adata.uns["cap_metadata"])
    fn(cap)
    adata.uns["cap_metadata"] = cap


def test_happy_path(cap_h5ad):
    v = HCACellAnnotationValidator()
    assert v.validate_adata(str(cap_h5ad)) is True
    assert v.errors == []
    assert v.warnings == []


def test_no_cellannotation_metadata_errors(cap_h5ad):
    def mutate(adata):
        _mutate_cap(adata, lambda cap: cap.pop("cellannotation_metadata"))
    _rewrite(cap_h5ad, mutate)

    v = HCACellAnnotationValidator()
    assert v.validate_adata(str(cap_h5ad)) is False
    assert NO_SETS_ERROR in v.errors


def test_legacy_toplevel_layout_errors(cap_h5ad):
    # Downgrade to the deprecated top-level layout: lift cap_metadata's keys to
    # the top level of uns and drop the wrapper.
    def mutate(adata):
        cap = dict(adata.uns.pop("cap_metadata"))
        for key, value in cap.items():
            adata.uns[key] = value
    _rewrite(cap_h5ad, mutate)

    v = HCACellAnnotationValidator()
    assert v.validate_adata(str(cap_h5ad)) is False
    assert LEGACY_LAYOUT_ERROR in v.errors


def test_missing_cap_metadata_errors(tmp_path):
    # A file with no CAP at all gets NO_SETS_ERROR, not the legacy message.
    from hca_schema_validator.testing import create_labelable_h5ad

    path = create_labelable_h5ad(tmp_path / "no_cap.h5ad")
    v = HCACellAnnotationValidator()
    assert v.validate_adata(str(path)) is False
    assert NO_SETS_ERROR in v.errors


def test_empty_metadata_errors(cap_h5ad):
    def mutate(adata):
        _mutate_cap(adata, lambda cap: cap.update(cellannotation_metadata={}))
    _rewrite(cap_h5ad, mutate)

    v = HCACellAnnotationValidator()
    assert v.validate_adata(str(cap_h5ad)) is False
    assert NO_SETS_ERROR in v.errors


def test_metadata_wrong_type_errors(cap_h5ad):
    def mutate(adata):
        _mutate_cap(adata, lambda cap: cap.update(cellannotation_metadata="not-a-dict"))
    _rewrite(cap_h5ad, mutate)

    v = HCACellAnnotationValidator()
    assert v.validate_adata(str(cap_h5ad)) is False
    assert any("must be a dict" in e for e in v.errors)


def test_missing_schema_version_errors(cap_h5ad):
    def mutate(adata):
        _mutate_cap(adata, lambda cap: cap.pop("cellannotation_schema_version"))
    _rewrite(cap_h5ad, mutate)

    v = HCACellAnnotationValidator()
    assert v.validate_adata(str(cap_h5ad)) is False
    assert any("cellannotation_schema_version" in e and "missing" in e for e in v.errors)


def test_malformed_schema_version_errors(cap_h5ad):
    def mutate(adata):
        _mutate_cap(adata, lambda cap: cap.update(cellannotation_schema_version="not-a-version"))
    _rewrite(cap_h5ad, mutate)

    v = HCACellAnnotationValidator()
    assert v.validate_adata(str(cap_h5ad)) is False
    assert any("semver" in e for e in v.errors)


def test_set_metadata_wrong_type_errors(cap_h5ad):
    def mutate(adata):
        _mutate_cap(
            adata,
            lambda cap: cap.update(cellannotation_metadata={"author_annotation": "not-a-dict"}),
        )
    _rewrite(cap_h5ad, mutate)

    v = HCACellAnnotationValidator()
    assert v.validate_adata(str(cap_h5ad)) is False
    assert any("author_annotation" in e and "must be a dict" in e for e in v.errors)


def test_missing_required_obs_column_errors(cap_h5ad):
    def mutate(adata):
        adata.obs.drop(columns=["author_annotation--rationale"], inplace=True)
    _rewrite(cap_h5ad, mutate)

    v = HCACellAnnotationValidator()
    assert v.validate_adata(str(cap_h5ad)) is False
    assert any(
        "author_annotation" in e and "author_annotation--rationale" in e
        for e in v.errors
    )


def test_validate_adata_resets_state(cap_h5ad, tmp_path):
    bad_path = tmp_path / "bad.h5ad"
    create_cap_annotated_h5ad(bad_path)
    _rewrite(bad_path, lambda a: _mutate_cap(a, lambda cap: cap.pop("cellannotation_metadata")))

    v = HCACellAnnotationValidator()
    assert v.validate_adata(str(bad_path)) is False
    assert v.errors

    assert v.validate_adata(str(cap_h5ad)) is True
    assert v.errors == []


def test_unreadable_file_errors(tmp_path):
    v = HCACellAnnotationValidator()
    assert v.validate_adata(str(tmp_path / "nonexistent.h5ad")) is False
    assert any("Unable to read h5ad file" in e for e in v.errors)
