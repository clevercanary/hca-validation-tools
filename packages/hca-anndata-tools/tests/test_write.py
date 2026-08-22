"""Tests for write_h5ad, strip_timestamp, and generate_output_path."""

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

import anndata as ad
import pytest

from hca_anndata_tools.write import (
    EDIT_LOG_KEY,
    SameSecondSnapshotError,
    _copy_with_sha256,
    generate_output_path,
    resolve_latest,
    snapshot_copy,
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
    basename = Path(result).name
    assert basename.startswith("data-")
    # Exactly one timestamp (no double-stamping) — use unanchored pattern
    ts_pattern = r"\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}"
    assert len(re.findall(ts_pattern, basename)) == 1


def test_generate_output_path_format(sample_h5ad_for_write):
    result = generate_output_path(str(sample_h5ad_for_write))
    basename = Path(result).name
    assert TIMESTAMP_RE.search(basename)
    assert basename.startswith("test-dataset-")


# --- write_h5ad ---


def test_write_h5ad_basic(sample_h5ad_for_write):
    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    result = write_h5ad(adata, str(sample_h5ad_for_write), [_make_entry()])

    assert "error" not in result
    assert "output_path" in result

    assert Path(result["output_path"]).is_file()
    assert TIMESTAMP_RE.search(result["output_path"])


def test_write_h5ad_edit_log_populated(sample_h5ad_for_write):
    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    entry = _make_entry(operation="update_obs_column", description="fix tissue values")
    result = write_h5ad(adata, str(sample_h5ad_for_write), [entry])

    written = ad.read_h5ad(result["output_path"])
    log = json.loads(written.uns["provenance"][EDIT_LOG_KEY])
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
    log = json.loads(written.uns["provenance"][EDIT_LOG_KEY])
    assert len(log) == 2
    assert log[0]["description"] == "edit 1"
    assert log[1]["description"] == "edit 2"


def test_write_h5ad_sha256_correct(sample_h5ad_for_write):
    # Compute expected hash independently
    h = hashlib.sha256()
    with Path(sample_h5ad_for_write).open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    expected_sha = h.hexdigest()

    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    result = write_h5ad(adata, str(sample_h5ad_for_write), [_make_entry()])

    written = ad.read_h5ad(result["output_path"])
    log = json.loads(written.uns["provenance"][EDIT_LOG_KEY])
    assert log[0]["source_sha256"] == expected_sha


def test_write_h5ad_source_file_is_basename(sample_h5ad_for_write):
    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    result = write_h5ad(adata, str(sample_h5ad_for_write), [_make_entry()])

    written = ad.read_h5ad(result["output_path"])
    log = json.loads(written.uns["provenance"][EDIT_LOG_KEY])
    source_file = log[0]["source_file"]
    assert source_file == Path(source_file).name
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
    log = json.loads(final.uns["provenance"][EDIT_LOG_KEY])
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
    adata.uns.setdefault("provenance", {})[EDIT_LOG_KEY] = "not valid json {{"
    result = write_h5ad(adata, str(sample_h5ad_for_write), [_make_entry()])

    assert "error" in result
    assert "invalid JSON" in result["error"]


def test_write_h5ad_non_list_json_log(sample_h5ad_for_write):
    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    adata.uns.setdefault("provenance", {})[EDIT_LOG_KEY] = json.dumps({"not": "a list"})
    result = write_h5ad(adata, str(sample_h5ad_for_write), [_make_entry()])

    assert "error" in result
    assert "expected list" in result["error"]


def test_write_h5ad_unsupported_log_type(sample_h5ad_for_write):
    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    adata.uns.setdefault("provenance", {})[EDIT_LOG_KEY] = 42
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
    assert Path(custom).is_file()


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
    assert Path(sample_h5ad_for_write).is_file()  # original still there

    # Second write: timestamped → new timestamped
    adata2 = ad.read_h5ad(r1["output_path"])
    r2 = write_h5ad(adata2, r1["output_path"], [_make_entry(description="second")])
    assert "error" not in r2
    assert Path(sample_h5ad_for_write).is_file()  # original still there
    assert Path(r2["output_path"]).is_file()  # latest version exists

    # Count h5ad files in directory — should be original + one timestamped
    d = sample_h5ad_for_write.parent
    h5ad_files = list(d.glob("*.h5ad"))
    assert len(h5ad_files) == 2  # original + latest edit


def test_write_h5ad_never_deletes_original(sample_h5ad_for_write):
    """Writing from the original never deletes it."""
    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    r1 = write_h5ad(adata, str(sample_h5ad_for_write), [_make_entry()])
    assert "error" not in r1
    assert Path(sample_h5ad_for_write).is_file()

    # Write again from original
    adata2 = ad.read_h5ad(str(sample_h5ad_for_write))
    r2 = write_h5ad(adata2, str(sample_h5ad_for_write), [_make_entry()])
    assert "error" not in r2
    assert Path(sample_h5ad_for_write).is_file()


# --- has_edit_log_operation ---


def test_has_edit_log_operation_finds_matching_entry(sample_h5ad_for_write):
    """Seed an edit log entry, then assert the operation is detected."""
    from hca_anndata_tools.write import has_edit_log_operation

    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    entry = _make_entry(operation="import_cellxgene", description="Imported from CXG")
    seed = json.dumps(
        [
            {
                **entry,
                "source_file": "fake.h5ad",
                "source_sha256": "0" * 64,
            }
        ]
    )
    adata.uns.setdefault("provenance", {})[EDIT_LOG_KEY] = seed

    assert has_edit_log_operation(adata, "import_cellxgene") is True
    assert has_edit_log_operation(adata, "normalize_raw") is False


def test_has_edit_log_operation_missing_log(sample_h5ad_for_write):
    """No provenance / no edit_history → False, not an error."""
    from hca_anndata_tools.write import has_edit_log_operation

    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    # No provenance set on this fixture
    assert has_edit_log_operation(adata, "import_cellxgene") is False


def test_has_edit_log_operation_malformed_log_returns_false(sample_h5ad_for_write):
    """Garbage JSON in the log → False rather than raising."""
    from hca_anndata_tools.write import has_edit_log_operation

    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    adata.uns.setdefault("provenance", {})[EDIT_LOG_KEY] = "this is not json"

    assert has_edit_log_operation(adata, "import_cellxgene") is False


def test_has_edit_log_operation_accepts_list_shape(sample_h5ad_for_write):
    """Edit log can be a Python list in-memory during write transforms
    (mirroring build_edit_log's input handling). The helper should
    handle that shape too, not just the on-disk JSON string."""
    from hca_anndata_tools.write import has_edit_log_operation

    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    entry = _make_entry(operation="import_cellxgene", description="Imported from CXG")
    log_list = [{**entry, "source_file": "fake.h5ad", "source_sha256": "0" * 64}]
    # Assign as a Python list (not a JSON string).
    adata.uns.setdefault("provenance", {})[EDIT_LOG_KEY] = log_list

    assert has_edit_log_operation(adata, "import_cellxgene") is True
    assert has_edit_log_operation(adata, "normalize_raw") is False


# --- _copy_with_sha256 ---


def test_copy_with_sha256_copies_and_hashes_in_one_pass(tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"hello h5ad")
    dst = tmp_path / "dst.bin"

    digest = _copy_with_sha256(str(src), str(dst))

    assert dst.read_bytes() == b"hello h5ad"
    assert digest == hashlib.sha256(b"hello h5ad").hexdigest()


def test_copy_with_sha256_refuses_same_path(tmp_path):
    """Opening dest with 'wb' would truncate the source before reading it —
    a same-path call must fail like shutil.copy2, not zero out the file."""
    src = tmp_path / "src.bin"
    src.write_bytes(b"do not truncate")

    with pytest.raises(shutil.SameFileError):
        _copy_with_sha256(str(src), str(src))

    assert src.read_bytes() == b"do not truncate"


def test_copy_with_sha256_refuses_hard_link(tmp_path):
    """Two hard links share an inode but not a resolved path — the guard
    must compare filesystem identity, not path strings."""
    src = tmp_path / "src.bin"
    src.write_bytes(b"do not truncate")
    link = tmp_path / "link.bin"
    os.link(src, link)

    with pytest.raises(shutil.SameFileError):
        _copy_with_sha256(str(src), str(link))

    assert src.read_bytes() == b"do not truncate"


# --- snapshot_copy: the shared create-and-clean-up contract (#598) ------------


def test_snapshot_copy_yields_a_distinct_copy(tmp_path):
    """The happy path: a real copy under a fresh name, source untouched."""
    src = tmp_path / "d.h5ad"
    src.write_bytes(b"payload")

    with snapshot_copy(str(src)) as out:
        assert Path(out) != src
        assert Path(out).read_bytes() == b"payload"

    assert Path(out).is_file()  # a clean exit keeps the snapshot
    assert src.read_bytes() == b"payload"


def test_snapshot_copy_waits_out_a_collision(tmp_path, monkeypatch):
    """A name equal to the source is retried after the second boundary rather
    than failing the run — these tools collide routinely when chained."""
    src = tmp_path / "d.h5ad"
    src.write_bytes(b"payload")
    fresh = tmp_path / "d-edit-2026-08-22-00-00-01.h5ad"
    names = iter([str(src), str(fresh)])
    monkeypatch.setattr("hca_anndata_tools.write.generate_output_path", lambda p: next(names))
    slept = []
    monkeypatch.setattr("hca_anndata_tools.write.time.sleep", slept.append)

    with snapshot_copy(str(src)) as out:
        assert Path(out) == fresh

    assert slept == [1]


def test_snapshot_copy_refuses_an_unresolvable_collision(tmp_path, monkeypatch):
    """A collision that survives the wait raises, and the source is untouched."""
    src = tmp_path / "d.h5ad"
    src.write_bytes(b"payload")
    monkeypatch.setattr("hca_anndata_tools.write.generate_output_path", lambda p: p)
    monkeypatch.setattr("hca_anndata_tools.write.time.sleep", lambda _: None)

    with pytest.raises(SameSecondSnapshotError), snapshot_copy(str(src)):
        pass  # pragma: no cover - the context manager raises on entry

    assert src.read_bytes() == b"payload"


def test_snapshot_copy_never_removes_a_file_it_did_not_create(tmp_path, monkeypatch):
    """A destination that is already occupied — by a sibling tool's snapshot
    from this same second, not by the source — is refused before the copy, so
    the cleanup can never reach a file we did not write."""
    src = tmp_path / "d.h5ad"
    src.write_bytes(b"source")
    occupied = tmp_path / "d-edit-2026-08-22-00-00-01.h5ad"
    occupied.write_bytes(b"a sibling's snapshot")
    monkeypatch.setattr("hca_anndata_tools.write.generate_output_path", lambda p: str(occupied))
    monkeypatch.setattr("hca_anndata_tools.write.time.sleep", lambda _: None)

    def must_not_run(*args, **kwargs):  # pragma: no cover - asserts unreachable
        raise AssertionError("copy2 must not run against an occupied destination")

    monkeypatch.setattr("hca_anndata_tools.write.shutil.copy2", must_not_run)

    with pytest.raises(SameSecondSnapshotError), snapshot_copy(str(src)):
        pass  # pragma: no cover - the context manager raises on entry

    assert occupied.read_bytes() == b"a sibling's snapshot"


def test_snapshot_copy_refuses_a_broken_symlink_destination(tmp_path, monkeypatch):
    """A broken symlink occupies the name even though Path.exists() reports it
    absent — exists() follows the link. Claiming that name would write through
    the symlink and then unlink a symlink we did not create."""
    src = tmp_path / "d.h5ad"
    src.write_bytes(b"source")
    dangling = tmp_path / "d-edit-2026-08-22-00-00-01.h5ad"
    dangling.symlink_to(tmp_path / "gone.h5ad")
    assert not dangling.exists() and dangling.is_symlink()  # the trap
    monkeypatch.setattr("hca_anndata_tools.write.generate_output_path", lambda p: str(dangling))
    monkeypatch.setattr("hca_anndata_tools.write.time.sleep", lambda _: None)

    with pytest.raises(SameSecondSnapshotError), snapshot_copy(str(src)):
        pass  # pragma: no cover - the context manager raises on entry

    assert dangling.is_symlink()  # not ours to remove


def test_snapshot_copy_refuses_an_alias_without_unlinking_it(tmp_path, monkeypatch):
    """A hard link to the source occupies the generated name, so the claim step
    refuses it before any copy is attempted. The destination is left alone: it
    predates the call, and an alias naming the source's own directory entry
    (a './'-prefixed path) would take the source with it."""
    src = tmp_path / "d.h5ad"
    src.write_bytes(b"payload")
    alias = tmp_path / "d-edit-2026-08-22-00-00-01.h5ad"
    os.link(src, alias)
    monkeypatch.setattr("hca_anndata_tools.write.generate_output_path", lambda p: str(alias))
    monkeypatch.setattr("hca_anndata_tools.write.time.sleep", lambda _: None)

    with pytest.raises(SameSecondSnapshotError), snapshot_copy(str(src)):
        pass  # pragma: no cover - the context manager raises on entry

    assert alias.is_file()
    assert src.read_bytes() == b"payload"


def test_snapshot_copy_removes_a_partially_written_snapshot(tmp_path, monkeypatch):
    """copyfile opens the destination 'wb' and leaves it behind if the copy
    dies partway. A leftover would win resolve_latest on the next call."""
    src = tmp_path / "d.h5ad"
    src.write_bytes(b"payload")
    written = {}

    def die_partway(s, dst, *args, **kwargs):
        Path(dst).write_bytes(b"partial")
        written["dst"] = dst
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("hca_anndata_tools.write.shutil.copy2", die_partway)

    with pytest.raises(OSError, match="No space left"), snapshot_copy(str(src)):
        pass  # pragma: no cover - the context manager raises on entry

    assert not Path(written["dst"]).exists()


def test_snapshot_copy_removes_the_snapshot_when_the_body_fails(tmp_path):
    """A body that raises leaves no half-edited snapshot behind, and the
    exception still reaches the caller's own handler."""
    src = tmp_path / "d.h5ad"
    src.write_bytes(b"payload")
    seen = {}

    with pytest.raises(ValueError, match="boom"), snapshot_copy(str(src)) as out:
        seen["out"] = out
        raise ValueError("boom")

    assert not Path(seen["out"]).exists()
    assert src.read_bytes() == b"payload"
