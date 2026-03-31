"""Tests for write_h5ad, strip_timestamp, and generate_output_path."""

import hashlib
import json
import os
import re

import anndata as ad

from hca_anndata_tools.write import (
    EDIT_LOG_KEY,
    generate_output_path,
    resolve_latest,
    strip_timestamp,
    write_h5ad,
)

TIMESTAMP_RE = re.compile(r"-edit-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}\.h5ad$")


def _make_entry(**overrides):
    """Build a minimal edit log entry for testing."""
    entry = {
        "timestamp": "2026-03-27T13:54:26Z",
        "tool": "test",
        "tool_version": "0.0.1",
        "operation": "test_op",
        "description": "test edit",
    }
    entry.update(overrides)
    return entry


# --- strip_timestamp ---


def test_strip_timestamp_removes_suffix():
    assert strip_timestamp("foo-edit-2026-03-27-13-54-26.h5ad") == "foo.h5ad"


def test_strip_timestamp_no_suffix():
    assert strip_timestamp("foo.h5ad") == "foo.h5ad"


def test_strip_timestamp_preserves_complex_basename():
    result = strip_timestamp("AlZaim_2024_reprocessed-r1-wip-5-edit-2026-03-27-13-54-26.h5ad")
    assert result == "AlZaim_2024_reprocessed-r1-wip-5.h5ad"


def test_strip_timestamp_ignores_non_h5ad():
    name = "foo-edit-2026-03-27-13-54-26.csv"
    assert strip_timestamp(name) == name


# --- generate_output_path ---


def test_generate_output_path_default_dir(sample_h5ad_for_write):
    result = generate_output_path(str(sample_h5ad_for_write))
    assert result.startswith(str(sample_h5ad_for_write.parent))
    assert TIMESTAMP_RE.search(result)


def test_generate_output_path_strips_existing_timestamp(tmp_path):
    # Simulate a file with an existing timestamp in the name
    source = tmp_path / "data-edit-2026-03-27-13-54-26.h5ad"
    source.touch()
    result = generate_output_path(str(source))
    # Should have base "data" with a NEW timestamp, not double-stamped
    basename = os.path.basename(result)
    assert basename.startswith("data-")
    # Exactly one timestamp (no double-stamping) — use unanchored pattern
    ts_pattern = r"\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}"
    assert len(re.findall(ts_pattern, basename)) == 1


def test_generate_output_path_format(sample_h5ad_for_write):
    result = generate_output_path(str(sample_h5ad_for_write))
    basename = os.path.basename(result)
    assert TIMESTAMP_RE.search(basename)
    assert basename.startswith("test-dataset-")


# --- write_h5ad ---


def test_write_h5ad_basic(sample_h5ad_for_write):
    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    result = write_h5ad(adata, str(sample_h5ad_for_write), [_make_entry()])

    assert "error" not in result
    assert "output_path" in result

    assert os.path.isfile(result["output_path"])
    assert TIMESTAMP_RE.search(result["output_path"])


def test_write_h5ad_edit_log_populated(sample_h5ad_for_write):
    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    entry = _make_entry(operation="update_obs_column", description="fix tissue values")
    result = write_h5ad(adata, str(sample_h5ad_for_write), [entry])

    written = ad.read_h5ad(result["output_path"])
    log = json.loads(written.uns[EDIT_LOG_KEY])
    assert isinstance(log, list)
    assert len(log) == 1
    assert log[0]["operation"] == "update_obs_column"
    assert log[0]["description"] == "fix tissue values"
    assert "source_file" in log[0]
    assert "source_sha256" in log[0]


def test_write_h5ad_preserves_existing_log(sample_h5ad_for_write):
    # First write
    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    result1 = write_h5ad(adata, str(sample_h5ad_for_write), [_make_entry(description="edit 1")])

    # Second write from the first output
    adata2 = ad.read_h5ad(result1["output_path"])
    result2 = write_h5ad(adata2, result1["output_path"], [_make_entry(description="edit 2")])

    written = ad.read_h5ad(result2["output_path"])
    log = json.loads(written.uns[EDIT_LOG_KEY])
    assert len(log) == 2
    assert log[0]["description"] == "edit 1"
    assert log[1]["description"] == "edit 2"


def test_write_h5ad_sha256_correct(sample_h5ad_for_write):
    # Compute expected hash independently
    h = hashlib.sha256()
    with open(sample_h5ad_for_write, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    expected_sha = h.hexdigest()

    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    result = write_h5ad(adata, str(sample_h5ad_for_write), [_make_entry()])

    written = ad.read_h5ad(result["output_path"])
    log = json.loads(written.uns[EDIT_LOG_KEY])
    assert log[0]["source_sha256"] == expected_sha


def test_write_h5ad_source_file_is_basename(sample_h5ad_for_write):
    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    result = write_h5ad(adata, str(sample_h5ad_for_write), [_make_entry()])

    written = ad.read_h5ad(result["output_path"])
    log = json.loads(written.uns[EDIT_LOG_KEY])
    source_file = log[0]["source_file"]
    assert source_file == os.path.basename(source_file)
    assert source_file == "test-dataset.h5ad"


def test_write_h5ad_missing_source(sample_h5ad_for_write):
    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    result = write_h5ad(adata, "/nonexistent/file.h5ad", [_make_entry()])

    assert "error" in result
    assert "not found" in result["error"].lower()


def test_write_h5ad_empty_entries(sample_h5ad_for_write):
    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    result = write_h5ad(adata, str(sample_h5ad_for_write), [])

    assert "error" in result


def test_write_h5ad_data_integrity(sample_h5ad_for_write):
    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    original_shape = adata.X.shape
    original_obs_cols = list(adata.obs.columns)
    original_var_cols = list(adata.var.columns)

    result = write_h5ad(adata, str(sample_h5ad_for_write), [_make_entry()])

    written = ad.read_h5ad(result["output_path"])
    assert written.X.shape == original_shape
    assert list(written.obs.columns) == original_obs_cols
    assert list(written.var.columns) == original_var_cols
    assert written.n_obs == 50
    assert written.n_vars == 20


def test_write_h5ad_roundtrip_edit_log(sample_h5ad_for_write):
    """Write -> read -> write -> read, verify full log chain."""
    # First write
    adata1 = ad.read_h5ad(str(sample_h5ad_for_write))
    r1 = write_h5ad(adata1, str(sample_h5ad_for_write), [_make_entry(description="first")])
    assert "error" not in r1

    # Second write from first output
    adata2 = ad.read_h5ad(r1["output_path"])
    r2 = write_h5ad(adata2, r1["output_path"], [_make_entry(description="second")])
    assert "error" not in r2

    # Third write from second output
    adata3 = ad.read_h5ad(r2["output_path"])
    r3 = write_h5ad(adata3, r2["output_path"], [_make_entry(description="third")])
    assert "error" not in r3

    # Verify full chain
    final = ad.read_h5ad(r3["output_path"])
    log = json.loads(final.uns[EDIT_LOG_KEY])
    assert len(log) == 3
    assert [e["description"] for e in log] == ["first", "second", "third"]


# --- validation edge cases ---


def test_write_h5ad_missing_required_keys(sample_h5ad_for_write):
    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    bad_entry = {"timestamp": "2026-03-27T00:00:00Z", "tool": "test"}
    result = write_h5ad(adata, str(sample_h5ad_for_write), [bad_entry])

    assert "error" in result
    assert "missing required keys" in result["error"]


def test_write_h5ad_corrupt_json_log(sample_h5ad_for_write):
    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    adata.uns[EDIT_LOG_KEY] = "not valid json {{"
    result = write_h5ad(adata, str(sample_h5ad_for_write), [_make_entry()])

    assert "error" in result
    assert "invalid JSON" in result["error"]


def test_write_h5ad_non_list_json_log(sample_h5ad_for_write):
    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    adata.uns[EDIT_LOG_KEY] = json.dumps({"not": "a list"})
    result = write_h5ad(adata, str(sample_h5ad_for_write), [_make_entry()])

    assert "error" in result
    assert "expected list" in result["error"]


def test_write_h5ad_unsupported_log_type(sample_h5ad_for_write):
    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    adata.uns[EDIT_LOG_KEY] = 42
    result = write_h5ad(adata, str(sample_h5ad_for_write), [_make_entry()])

    assert "error" in result
    assert "unsupported type" in result["error"]


# --- output_path override ---


def test_write_h5ad_custom_output_path(sample_h5ad_for_write, tmp_path):
    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    custom = str(tmp_path / "custom-name-edit-2026-03-29-00-00-00.h5ad")
    result = write_h5ad(adata, str(sample_h5ad_for_write), [_make_entry()], output_path=custom)

    assert "error" not in result
    assert result["output_path"] == custom
    assert os.path.isfile(custom)


# --- resolve_latest ---


def test_resolve_latest_no_timestamps(sample_h5ad_for_write):
    """Returns original when no timestamped versions exist."""
    result = resolve_latest(str(sample_h5ad_for_write))
    assert result == str(sample_h5ad_for_write)


def test_resolve_latest_finds_newest(sample_h5ad_for_write):
    """Returns the latest timestamped version."""
    d = sample_h5ad_for_write.parent
    stem = sample_h5ad_for_write.stem  # "test-dataset"
    # Create fake timestamped files
    (d / f"{stem}-edit-2026-03-27-10-00-00.h5ad").touch()
    (d / f"{stem}-edit-2026-03-28-15-30-00.h5ad").touch()
    (d / f"{stem}-edit-2026-03-27-12-00-00.h5ad").touch()

    result = resolve_latest(str(sample_h5ad_for_write))
    assert result.endswith(f"{stem}-edit-2026-03-28-15-30-00.h5ad")


def test_resolve_latest_from_timestamped_path(sample_h5ad_for_write):
    """Given a timestamped path, still finds the latest (not self)."""
    d = sample_h5ad_for_write.parent
    stem = sample_h5ad_for_write.stem
    old = d / f"{stem}-edit-2026-03-27-10-00-00.h5ad"
    new = d / f"{stem}-edit-2026-03-28-15-30-00.h5ad"
    old.touch()
    new.touch()

    result = resolve_latest(str(old))
    assert result.endswith(f"{stem}-edit-2026-03-28-15-30-00.h5ad")


# --- write_h5ad overwrite ---


def test_write_h5ad_deletes_previous_timestamped(sample_h5ad_for_write):
    """After writes, only original + one timestamped version remain."""
    adata = ad.read_h5ad(str(sample_h5ad_for_write))

    # First write: original → timestamped
    r1 = write_h5ad(adata, str(sample_h5ad_for_write), [_make_entry(description="first")])
    assert "error" not in r1
    assert os.path.isfile(str(sample_h5ad_for_write))  # original still there

    # Second write: timestamped → new timestamped
    adata2 = ad.read_h5ad(r1["output_path"])
    r2 = write_h5ad(adata2, r1["output_path"], [_make_entry(description="second")])
    assert "error" not in r2
    assert os.path.isfile(str(sample_h5ad_for_write))  # original still there
    assert os.path.isfile(r2["output_path"])  # latest version exists

    # Count h5ad files in directory — should be original + one timestamped
    d = sample_h5ad_for_write.parent
    h5ad_files = list(d.glob("*.h5ad"))
    assert len(h5ad_files) == 2  # original + latest edit


def test_write_h5ad_never_deletes_original(sample_h5ad_for_write):
    """Writing from the original never deletes it."""
    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    r1 = write_h5ad(adata, str(sample_h5ad_for_write), [_make_entry()])
    assert "error" not in r1
    assert os.path.isfile(str(sample_h5ad_for_write))

    # Write again from original
    adata2 = ad.read_h5ad(str(sample_h5ad_for_write))
    r2 = write_h5ad(adata2, str(sample_h5ad_for_write), [_make_entry()])
    assert "error" not in r2
    assert os.path.isfile(str(sample_h5ad_for_write))
