"""Unit tests for the validate_schema + validate_cell_annotation MCP wrappers."""

import anndata as ad
import pytest

from hca_anndata_mcp.tools.validate import validate_cell_annotation, validate_schema
from hca_anndata_tools.testing import create_sample_h5ad
from hca_schema_validator.cell_annotation_validator import NO_SETS_ERROR
from hca_schema_validator.testing import create_cap_annotated_h5ad, create_labelable_h5ad


def test_validate_schema_shape(sample_h5ad):
    result = validate_schema(str(sample_h5ad), object_kind="source")
    assert set(result.keys()) == {
        "filename",
        "object_kind",
        "is_valid",
        "error_count",
        "warning_count",
        "errors",
        "warnings",
    }
    assert result["object_kind"] == "source"
    assert isinstance(result["is_valid"], bool)
    assert result["error_count"] == len(result["errors"])
    assert result["warning_count"] == len(result["warnings"])


def test_validate_schema_missing_file():
    result = validate_schema("/nonexistent/file.h5ad", object_kind="source")
    assert "error" in result


# ---------------------------------------------------------------------------
# object_kind (#770): required, said by the caller, never read off the path


def test_validate_schema_requires_object_kind(sample_h5ad):
    """No default and no inference from the path: the caller says which kind it is."""
    with pytest.raises(TypeError, match="object_kind"):
        validate_schema(str(sample_h5ad))  # type: ignore[call-arg]


@pytest.mark.parametrize("kind", ["source", "integrated"])
def test_validate_schema_reports_the_kind_it_was_given(tmp_path, kind):
    # The path says the opposite of the parameter; the parameter is what counts.
    folder = tmp_path / ("integrated-objects" if kind == "source" else "source-datasets")
    folder.mkdir()
    path = create_sample_h5ad(folder / "dataset.h5ad")

    result = validate_schema(str(path), object_kind=kind)

    assert result["object_kind"] == kind


def test_validate_schema_object_kind_does_not_change_the_verdict(sample_h5ad):
    """Plumbing only (#770): same file, either kind, same verdict and messages."""
    as_source = validate_schema(str(sample_h5ad), object_kind="source")
    as_integrated = validate_schema(str(sample_h5ad), object_kind="integrated")

    assert as_source["is_valid"] == as_integrated["is_valid"]
    assert as_source["errors"] == as_integrated["errors"]
    assert as_source["warnings"] == as_integrated["warnings"]


def test_validate_schema_surfaces_cosmetic_check(tmp_path):
    """Confirm the producer-cosmetic-column check (issues #377, #443) surfaces
    through the MCP wrapper. The wrapper just returns the validator's
    warnings/errors, so this test exercises the integration boundary
    rather than re-testing the underlying logic.
    """
    path = create_labelable_h5ad(tmp_path / "cosmetic.h5ad")
    adata = ad.read_h5ad(path)
    adata.obs["tissue"] = "WRONG_TISSUE_LABEL"
    adata.write_h5ad(path)

    result = validate_schema(str(path), object_kind="source")

    assert any("'WRONG_TISSUE_LABEL'" in e and "Either delete the cosmetic column" in e for e in result["errors"]), (
        result["errors"]
    )
    # #443: a drifting label is an error, never a "delete the column" warning.
    assert not any("obs['tissue']" in w for w in result["warnings"]), result["warnings"]
    assert result["is_valid"] is False


def test_validate_schema_no_cosmetic_warning_when_labels_match(tmp_path):
    """#443 at the integration boundary: a verified-canonical label column is silent."""
    path = create_labelable_h5ad(tmp_path / "matching.h5ad")
    adata = ad.read_h5ad(path)
    adata.obs["tissue"] = "lung"  # canonical for UBERON:0002048
    adata.write_h5ad(path)

    result = validate_schema(str(path), object_kind="source")

    assert not any("obs['tissue']" in w for w in result["warnings"]), result["warnings"]
    assert not any("obs['tissue']" in e for e in result["errors"]), result["errors"]


def test_validate_schema_resolves_latest(tmp_path):
    """Confirm the wrapper validates the snapshot's bytes, not just echoes its
    filename. Strip ``uns['title']`` from the snapshot so it produces a distinct
    error the original lacks, then verify the lineage call's output matches the
    snapshot's direct validation result."""
    original = tmp_path / "dataset.h5ad"
    create_sample_h5ad(original)

    # Capture the original's baseline before any snapshot exists in the
    # directory — otherwise resolve_latest would pick the snapshot when we
    # ask about the original path.
    direct_original = validate_schema(str(original), object_kind="source")

    snapshot = tmp_path / "dataset-edit-2026-04-17-06-00-00.h5ad"
    create_sample_h5ad(snapshot)
    adata = ad.read_h5ad(snapshot)
    del adata.uns["title"]
    adata.write_h5ad(snapshot)

    direct_snapshot = validate_schema(str(snapshot), object_kind="source")
    via_lineage = validate_schema(str(original), object_kind="source")  # resolve_latest picks the snapshot

    assert direct_original["errors"] != direct_snapshot["errors"]  # discriminator works
    assert via_lineage == direct_snapshot


# ---------------------------------------------------------------------------
# validate_cell_annotation


def test_validate_cell_annotation_shape(tmp_path):
    path = create_cap_annotated_h5ad(tmp_path / "cap.h5ad")
    result = validate_cell_annotation(str(path))
    assert set(result.keys()) == {
        "filename",
        "is_valid",
        "error_count",
        "warning_count",
        "errors",
        "warnings",
    }
    assert isinstance(result["is_valid"], bool)
    assert result["error_count"] == len(result["errors"])
    assert result["warning_count"] == len(result["warnings"])


def test_validate_cell_annotation_happy_path(tmp_path):
    path = create_cap_annotated_h5ad(tmp_path / "cap.h5ad")
    result = validate_cell_annotation(str(path))
    assert result["is_valid"] is True
    assert result["error_count"] == 0
    assert result["errors"] == []
    # Pin the warnings contract too — without this, a future addition of
    # non-fatal warnings (e.g. Phase 2 #363) would silently change the
    # wrapper's surfaced API without test failure.
    assert result["warning_count"] == 0
    assert result["warnings"] == []


def test_validate_cell_annotation_missing_file():
    result = validate_cell_annotation("/nonexistent/file.h5ad")
    assert "error" in result


def test_validate_cell_annotation_surfaces_no_sets_error(tmp_path):
    """Confirm underlying validator errors come through the MCP wrapper.

    A file with no CAP annotation set should surface NO_SETS_ERROR
    verbatim — proves the wrapper exposes the validator's full error list
    rather than just a boolean verdict.
    """
    path = tmp_path / "no-cap.h5ad"
    create_sample_h5ad(path)
    result = validate_cell_annotation(str(path))
    assert result["is_valid"] is False
    assert NO_SETS_ERROR in result["errors"]
