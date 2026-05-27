"""Integration tests for the populate_labels MCP wrapper.

The substantive per-column logic is tested at the validator layer in
``hca_schema_validator/tests/test_populator.py``. These tests cover only
the wrapper's file-I/O contract + the cellxgene-imported origin refusal
(which lives in the wrapper, not the validator).
"""

import json

import anndata as ad
from hca_anndata_mcp.tools.populate import populate_labels
from hca_anndata_tools.write import EDIT_LOG_KEY, make_edit_entry
from hca_schema_validator.testing import create_labelable_h5ad


def test_missing_file():
    result = populate_labels("/nonexistent/file.h5ad")
    assert "error" in result
    assert "File not found" in result["error"]


def test_smoke_end_to_end(tmp_path):
    """Empty fixture → tool writes a snapshot, edit log appended, output
    file readable. Validates the file-I/O contract (snapshot naming,
    edit-log entry, return shape)."""
    path = create_labelable_h5ad(tmp_path / "empty.h5ad")

    result = populate_labels(str(path))

    assert "error" not in result, result
    assert "output_path" in result
    assert result["matched"] == []
    assert len(result["filled"]) > 0

    written = ad.read_h5ad(result["output_path"])
    log = json.loads(written.uns["provenance"][EDIT_LOG_KEY])
    assert log[-1]["operation"] == "populate_labels"
    assert log[-1]["details"]["filled"] == result["filled"]


def test_refuse_cellxgene_imported(tmp_path):
    """Wrapper-level refusal: edit log contains an import_cellxgene entry
    → tool refuses without delegating to the validator-side populator."""
    path = create_labelable_h5ad(tmp_path / "cxg_imported.h5ad")
    adata = ad.read_h5ad(path)
    entry = make_edit_entry(
        operation="import_cellxgene",
        description="Imported from CellxGENE Discover: test",
        details={},
    )
    log = json.dumps([{
        **entry,
        "source_file": "test.h5ad",
        "source_sha256": "0" * 64,
    }])
    adata.uns.setdefault("provenance", {})[EDIT_LOG_KEY] = log
    adata.write_h5ad(path)

    result = populate_labels(str(path))
    assert "error" in result
    assert "import_cellxgene" in result["error"]


def test_preserves_existing_edit_log(tmp_path):
    """Non-cxg seed entry → new entry appended (not replaced)."""
    path = create_labelable_h5ad(tmp_path / "with_log.h5ad")
    adata = ad.read_h5ad(path)
    prior = make_edit_entry(
        operation="strip_forbidden_obs_columns",
        description="Stripped HCA-forbidden obs columns (privacy): ['self_reported_ethnicity']",
        details={"obs_columns_stripped": ["self_reported_ethnicity"]},
    )
    seed = json.dumps([{
        **prior,
        "source_file": "synthetic-seed.h5ad",
        "source_sha256": "0" * 64,
    }])
    adata.uns.setdefault("provenance", {})[EDIT_LOG_KEY] = seed
    adata.write_h5ad(path)

    result = populate_labels(str(path))
    assert "error" not in result, result

    written = ad.read_h5ad(result["output_path"])
    log = json.loads(written.uns["provenance"][EDIT_LOG_KEY])
    assert len(log) == 2
    assert log[0]["operation"] == "strip_forbidden_obs_columns"
    assert log[1]["operation"] == "populate_labels"


def test_passes_through_validator_skipped_sentinel(tmp_path):
    """If populate_in_memory returns skipped, the wrapper passes it
    through unchanged (no output file, no edit-log entry)."""
    # Build a fully-populated file by populating once first.
    path = create_labelable_h5ad(tmp_path / "to_match.h5ad")
    first = populate_labels(str(path))
    assert "error" not in first

    # Run again on the just-populated output — everything already
    # matches, so the validator returns skipped.
    result = populate_labels(first["output_path"])
    assert result.get("skipped") is True, result
