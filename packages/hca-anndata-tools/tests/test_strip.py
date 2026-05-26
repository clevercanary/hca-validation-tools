"""Tests for strip_forbidden_obs_columns."""

import json
import os

import anndata as ad
import pandas as pd
from hca_anndata_tools.strip import (
    _OBS_COLUMNS_TO_STRIP,
    strip_forbidden_obs_columns,
)
from hca_anndata_tools.write import EDIT_LOG_KEY, make_edit_entry


def _to_hca_layout(path, *sre_cols):
    """Coerce the ``sample_h5ad_for_write`` fixture into an HCA-layout file
    with the named SRE columns added.

    The base fixture (``create_sample_h5ad``) sets ``uns['schema_version']``
    for historical reasons — that's the exact marker the strip tool uses to
    refuse on CellxGENE-layout input. Drop it so the test models a real
    HCA-layout file, then add the requested SRE columns to obs.
    """
    adata = ad.read_h5ad(path)
    adata.uns.pop("schema_version", None)
    for col in sre_cols:
        adata.obs[col] = pd.Categorical(["unknown"] * adata.n_obs)
    adata.write_h5ad(path)


def test_strip_both_present(sample_h5ad_for_write):
    """Happy path: both SRE columns present and get stripped."""
    _to_hca_layout(
        sample_h5ad_for_write,
        "self_reported_ethnicity_ontology_term_id",
        "self_reported_ethnicity",
    )

    result = strip_forbidden_obs_columns(str(sample_h5ad_for_write))

    assert "error" not in result
    assert "output_path" in result
    # Order must match the declared constant order (id first, label second).
    assert result["obs_columns_stripped"] == list(_OBS_COLUMNS_TO_STRIP)

    written = ad.read_h5ad(result["output_path"])
    assert "self_reported_ethnicity_ontology_term_id" not in written.obs.columns
    assert "self_reported_ethnicity" not in written.obs.columns


def test_strip_only_term_id_present(sample_h5ad_for_write):
    """Partial: only the _ontology_term_id column present (this is what
    the gut-v1 tracker-source files look like). Strip the one that's
    there, no-op the one that isn't."""
    _to_hca_layout(sample_h5ad_for_write, "self_reported_ethnicity_ontology_term_id")

    result = strip_forbidden_obs_columns(str(sample_h5ad_for_write))

    assert "error" not in result
    assert result["obs_columns_stripped"] == ["self_reported_ethnicity_ontology_term_id"]

    written = ad.read_h5ad(result["output_path"])
    assert "self_reported_ethnicity_ontology_term_id" not in written.obs.columns


def test_strip_no_op_when_neither_present(sample_h5ad_for_write):
    """No SRE columns to strip → skipped, no output file written."""
    _to_hca_layout(sample_h5ad_for_write)  # ensure HCA-layout, no SRE columns added
    result = strip_forbidden_obs_columns(str(sample_h5ad_for_write))

    assert result.get("skipped") is True
    assert "reason" in result
    # No timestamped snapshot should appear in the source directory.
    siblings = os.listdir(os.path.dirname(sample_h5ad_for_write))
    assert not any("-edit-" in name for name in siblings)


def test_strip_refuses_cellxgene_layout(cellxgene_h5ad):
    """The CellxGENE-layout fixture has uns['schema_version'] set; strip
    must refuse and direct the caller to convert_cellxgene_to_hca, which
    handles the strip as a side-effect of converting layout."""
    result = strip_forbidden_obs_columns(str(cellxgene_h5ad))

    assert "error" in result
    assert "CellxGENE-layout" in result["error"]
    assert "convert_cellxgene_to_hca" in result["error"]
    # No timestamped snapshot should appear in the source directory.
    siblings = os.listdir(os.path.dirname(cellxgene_h5ad))
    assert not any("-edit-" in name for name in siblings)


def test_strip_preserves_existing_edit_log(sample_h5ad_for_write):
    """An h5ad that already carries edit-log entries must get the new
    entry appended (not replaced). Otherwise audit history is lost."""
    # Seed an existing entry directly via anndata write — same shape the
    # other tools produce. Drop schema_version so this models a real
    # HCA-layout file (see _to_hca_layout for rationale).
    adata = ad.read_h5ad(sample_h5ad_for_write)
    adata.uns.pop("schema_version", None)
    adata.obs["self_reported_ethnicity"] = pd.Categorical(["unknown"] * adata.n_obs)
    prior_entry = make_edit_entry(
        operation="prior_synthetic_op",
        description="Synthetic prior entry to verify the strip tool appends.",
        details={"shape_before": [adata.n_obs, adata.n_vars]},
    )
    # source_file/source_sha256 are stamped at write time by build_edit_log,
    # but we're seeding by hand here — those fields aren't required by the
    # validator unless we re-stamp. Use the minimal shape that build_edit_log
    # will accept on the next read.
    seed_log = json.dumps([{
        **prior_entry,
        "source_file": "synthetic-seed.h5ad",
        "source_sha256": "0" * 64,
    }])
    adata.uns.setdefault("provenance", {})[EDIT_LOG_KEY] = seed_log
    adata.write_h5ad(sample_h5ad_for_write)

    result = strip_forbidden_obs_columns(str(sample_h5ad_for_write))
    assert "error" not in result

    written = ad.read_h5ad(result["output_path"])
    log = json.loads(written.uns["provenance"][EDIT_LOG_KEY])
    assert len(log) == 2, f"Expected 2 entries (prior + strip), got {len(log)}"
    assert log[0]["operation"] == "prior_synthetic_op"
    assert log[1]["operation"] == "strip_forbidden_obs_columns"
    assert log[1]["details"]["obs_columns_stripped"] == ["self_reported_ethnicity"]


def test_strip_missing_file():
    """Standard wrapper-style error path — surfaces a clean error string,
    not an exception."""
    result = strip_forbidden_obs_columns("/nonexistent/path/file.h5ad")
    assert "error" in result
    assert "File not found" in result["error"]
