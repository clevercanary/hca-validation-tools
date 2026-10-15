"""verify_local: classify a folder against the tracker, hash in a worker."""

import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from hca_tracker_client import CheckError, Verifier, verify_worker
from hca_tracker_client import verify as verify_module
from hca_tracker_client.api import Probe
from hca_tracker_client.store import INTERRUPTED
from hca_tracker_client.verify import check_sizes, classify, file_stem
from hca_tracker_client.verify_worker import hash_entry

from .conftest import make_config, make_file, wait_for

SIZE = 50_000


@pytest.fixture
def atlas(tracker):
    """The gut atlas with three integrated objects and two source datasets, their bytes in the fake bucket."""
    atlas_id = tracker.ids["gut"]
    blobs = {}
    for name, kind in [
        ("all.h5ad", "integrated"),
        ("myeloid.h5ad", "integrated"),
        ("stroma.h5ad", "integrated"),
        ("kong.h5ad", "source"),
        ("wells.h5ad", "source"),
    ]:
        blobs[name] = make_file(tracker.data_dir / name, SIZE)
        tracker.add_file(atlas_id, name, blobs[name], kind=kind)
    tracker.blobs_by_name = blobs
    return tracker


@pytest.fixture
def verifier(cache_dir, atlas):
    return Verifier(make_config(cache_dir, atlas))


def folder(root: Path, kind: str) -> Path:
    path = root / kind / "tracker-source"
    path.mkdir(parents=True, exist_ok=True)
    return path


def copy(atlas, name: str, to: Path, as_name: str | None = None) -> Path:
    target = to / (as_name or name.replace(".h5ad", "-r1-wip-1.h5ad"))
    shutil.copyfile(atlas.blobs_by_name[name], target)
    return target


def by_name(result: dict) -> dict[str, dict]:
    return {row["name"]: row for row in result["files"]}


def test_file_stem():
    assert file_stem("hgca-v1-kong-2023-v3-r1-wip-6.h5ad") == "hgca-v1-kong-2023-v3"
    assert file_stem("gut-r1-wip-1.h5ad") == "gut"
    assert file_stem("ihbca-v1-gray-2022-r1.h5ad") == "ihbca-v1-gray-2022"  # a published version's name
    assert file_stem("Human liver cell atlas - all cells.h5ad") is None
    assert file_stem("all.h5ad") is None


def test_a_wip_of_a_published_file_is_stale():
    """A published version's download names end in -r<revision>, with no -wip-<n>."""
    listed = {"gray-r1.h5ad": [{"entry": {"kind": "source", "fileId": "a", "fileName": "gray.h5ad"}}]}
    local = [{"name": "gray-r1-wip-3.h5ad", "folder_kind": None}, {"name": "gray-r1.h5ad", "folder_kind": None}]
    assert classify(local, listed) == []
    assert (local[0]["status"], local[0]["current_name"]) == ("stale", "gray-r1.h5ad")
    assert local[1]["tracker_name"] == "gray-r1.h5ad"


def test_an_unversioned_name_is_never_stale():
    listed = {"all-r1-wip-2.h5ad": [{"entry": {"kind": "integrated", "fileId": "a", "fileName": "all_v2.h5ad"}}]}
    local = [{"name": "all.h5ad", "folder_kind": None}]
    classify(local, listed)
    assert local[0]["status"] == "unknown"


def test_mixed_folder_is_classified(verifier, atlas, tmp_path):
    root = tmp_path / "gut-v1"
    integrated, source = folder(root, "integrated-objects"), folder(root, "source-datasets")
    copy(atlas, "all.h5ad", integrated)  # current
    copy(atlas, "kong.h5ad", integrated)  # a source dataset in the integrated folder
    copy(atlas, "myeloid.h5ad", integrated, "myeloid-r1-wip-0.h5ad")  # an older revision
    make_file(integrated / "notes.h5ad", 10)  # not a tracker file
    make_file(source / "wells-r1-wip-1.h5ad", SIZE)  # the tracker's name and size, other bytes
    make_file(integrated / "stroma-r1-wip-1.h5ad", SIZE + 1)  # the tracker's name, another size
    (integrated / "all-r1-wip-1.h5ad.part").write_bytes(b"x")  # a download in progress: skipped
    (root / "integrated-objects" / "all-r1-edit-2026-01-01.h5ad").write_bytes(b"x")  # outside tracker-source

    started = verifier.start("gut", "gut", str(root))
    assert started["state"] in ("queued", "hashing", "done")
    result = wait_for(verifier, started["job_id"], ("done", "failed", "interrupted"))
    assert result["state"] == "done", result

    rows = by_name(result)
    assert set(rows) == {
        "all-r1-wip-1.h5ad",
        "kong-r1-wip-1.h5ad",
        "myeloid-r1-wip-0.h5ad",
        "notes.h5ad",
        "wells-r1-wip-1.h5ad",
        "stroma-r1-wip-1.h5ad",
    }
    assert rows["all-r1-wip-1.h5ad"]["status"] == "verified" and rows["all-r1-wip-1.h5ad"]["misplaced"] is False
    assert rows["kong-r1-wip-1.h5ad"]["status"] == "verified" and rows["kong-r1-wip-1.h5ad"]["misplaced"] is True
    assert (rows["myeloid-r1-wip-0.h5ad"]["status"], rows["myeloid-r1-wip-0.h5ad"]["current_name"]) == (
        "stale",
        "myeloid-r1-wip-1.h5ad",
    )
    assert rows["myeloid-r1-wip-0.h5ad"]["kind"] == "integrated"
    assert rows["notes.h5ad"]["status"] == "unknown"
    assert rows["wells-r1-wip-1.h5ad"]["status"] == "mismatch"
    assert rows["stroma-r1-wip-1.h5ad"]["status"] == "size_mismatch"
    assert [m["name"] for m in result["missing"]] == ["myeloid-r1-wip-1.h5ad"]
    assert result["counts"] == {
        "verified": 2,
        "stale": 1,
        "unknown": 1,
        "mismatch": 1,
        "size_mismatch": 1,
        "missing": 1,
    }
    assert (result["files_to_hash"], result["files_hashed"]) == (3, 3)


def test_a_plain_folder_is_its_own_files_of_either_kind(verifier, atlas, tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    copy(atlas, "all.h5ad", downloads)
    copy(atlas, "kong.h5ad", downloads)
    make_file(downloads / "notes.h5ad", 10)
    make_file(downloads / "nested" / "wells-r1-wip-1.h5ad", SIZE)  # not directly in the folder: not read
    result = wait_for(verifier, verifier.start("gut", "gut", str(downloads))["job_id"], ("done",))
    assert result["layout"] == "folder"
    rows = by_name(result)
    assert set(rows) == {"all-r1-wip-1.h5ad", "kong-r1-wip-1.h5ad", "notes.h5ad"}
    assert (rows["all-r1-wip-1.h5ad"]["status"], rows["all-r1-wip-1.h5ad"]["kind"]) == ("verified", "integrated")
    assert (rows["kong-r1-wip-1.h5ad"]["status"], rows["kong-r1-wip-1.h5ad"]["kind"]) == ("verified", "source")
    assert "misplaced" not in rows["all-r1-wip-1.h5ad"]
    assert "missing" not in result and "missing" not in result["counts"]


def test_no_such_folder_is_refused(verifier, tmp_path):
    with pytest.raises(CheckError, match="No folder at"):
        verifier.start("gut", "gut", str(tmp_path / "absent"))


def test_a_probe_without_a_size_falls_back_to_the_listed_size(monkeypatch):
    local = [{"name": "x.h5ad", "tracker_name": "x-r1-wip-1.h5ad", "file_id": "f", "size_bytes": 10}]
    listed = {"x-r1-wip-1.h5ad": [{"entry": {"sizeBytes": 99}, "presigned": None}]}
    monkeypatch.setattr(verify_module, "probe", lambda presigned: Probe(size=None, sha256="a" * 64))
    check_sizes(local, listed)
    assert (local[0]["status"], local[0]["tracker_size_bytes"]) == ("size_mismatch", 99)


def test_the_worker_hashes_nothing_for_an_ended_job(verifier, atlas, tmp_path, monkeypatch):
    root = tmp_path / "gut-v1"
    copy(atlas, "all.h5ad", folder(root, "integrated-objects"))
    monkeypatch.setattr(verify_module, "spawn_worker", lambda *args: 0)  # start records the job, runs nothing
    started = verifier.start("gut", "gut", str(root))
    verifier.store.end(started["job_id"], INTERRUPTED, "ended before the worker began")
    assert verify_worker.run(started["job_id"], verifier.cache_dir) == 0
    assert by_name(verifier.status(started["job_id"]))["all-r1-wip-1.h5ad"]["status"] == "pending"


def test_nothing_to_hash_finishes_at_once(verifier, tmp_path):
    root = tmp_path / "gut-v1"
    make_file(folder(root, "source-datasets") / "notes.h5ad", 10)
    result = verifier.start("gut", "gut", str(root))
    assert result["state"] == "done"
    assert result["counts"] == {"unknown": 1, "missing": 5}


def test_a_file_without_a_tracker_checksum_is_not_hashed(cache_dir, tracker, tmp_path):
    blob = make_file(tracker.data_dir / "bare.h5ad", SIZE)
    tracker.add_file(tracker.ids["gut"], "bare.h5ad", blob, sha256=None)
    root = tmp_path / "gut-v1"
    shutil.copyfile(blob, folder(root, "integrated-objects") / "bare-r1-wip-1.h5ad")
    result = Verifier(make_config(cache_dir, tracker)).start("gut", "gut", str(root))
    assert result["state"] == "done"
    assert by_name(result)["bare-r1-wip-1.h5ad"]["status"] == "no_checksum"


def test_hash_entry_reports_a_changed_file(tmp_path):
    path = make_file(tmp_path / "f.h5ad", 100)
    stat = path.stat()
    entry = {"path": str(path), "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256_expected": "0" * 64}
    assert hash_entry(entry)["status"] == "mismatch"
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert hash_entry(entry) == {"status": "changed"}
    path.unlink()
    assert hash_entry(entry)["status"] == "unreadable"


def test_a_file_replaced_while_it_is_hashed_is_changed(tmp_path, monkeypatch):
    """A same-size copy with the same modification time, renamed over the file mid-hash."""
    path = make_file(tmp_path / "f.h5ad", 100)
    stat = path.stat()
    entry = {"path": str(path), "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    entry["sha256_expected"] = hash_entry({**entry, "sha256_expected": ""})["sha256"]
    real = verify_worker.hashlib.sha256

    def swapping():
        digest = real()
        update = digest.update

        def swap_then_update(chunk):
            other = tmp_path / "other.h5ad"
            other.write_bytes(b"y" * stat.st_size)
            os.utime(other, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            other.replace(path)
            update(chunk)

        return SimpleNamespace(update=swap_then_update, hexdigest=digest.hexdigest)

    monkeypatch.setattr(verify_worker, "hashlib", SimpleNamespace(sha256=swapping))
    assert hash_entry(entry) == {"status": "changed"}


def test_duplicate_tracker_names_are_reported_not_guessed(cache_dir, tracker, tmp_path):
    blob = make_file(tracker.data_dir / "twin.h5ad", SIZE)
    tracker.add_file(tracker.ids["gut"], "twin.h5ad", blob, kind="integrated")
    tracker.add_file(tracker.ids["gut"], "twin.h5ad", blob, kind="source")
    root = tmp_path / "gut-v1"
    shutil.copyfile(blob, folder(root, "integrated-objects") / "twin-r1-wip-1.h5ad")
    result = Verifier(make_config(cache_dir, tracker)).start("gut", "gut", str(root))
    assert result["state"] == "done"  # nothing to hash
    row = by_name(result)["twin-r1-wip-1.h5ad"]
    assert (row["status"], row["matches"]) == (
        "ambiguous",
        [{"name": "twin-r1-wip-1.h5ad", "kind": "integrated"}, {"name": "twin-r1-wip-1.h5ad", "kind": "source"}],
    )
    assert result["duplicate_names"] == [{"name": "twin-r1-wip-1.h5ad", "kinds": ["integrated", "source"]}]
    assert [(m["name"], m["kind"]) for m in result["missing"]] == [  # neither twin is known to be on disk
        ("twin-r1-wip-1.h5ad", "integrated"),
        ("twin-r1-wip-1.h5ad", "source"),
    ]
    shutil.copyfile(blob, folder(root, "integrated-objects") / "twin-r1-wip-0.h5ad")  # another wip of the twins
    again = by_name(Verifier(make_config(cache_dir, tracker)).start("gut", "gut", str(root)))["twin-r1-wip-0.h5ad"]
    assert again["status"] == "ambiguous" and len(again["matches"]) == 2


def test_files_are_never_written(verifier, atlas, tmp_path):
    root = tmp_path / "gut-v1"
    target = copy(atlas, "all.h5ad", folder(root, "integrated-objects"))
    before = (target.stat().st_mtime_ns, target.read_bytes())
    result = wait_for(verifier, verifier.start("gut", "gut", str(root))["job_id"], ("done",))
    assert by_name(result)["all-r1-wip-1.h5ad"]["status"] == "verified"
    assert (target.stat().st_mtime_ns, target.read_bytes()) == before


def test_a_copy_under_its_upload_name_is_hashed(verifier, atlas, tmp_path):
    """A file that never went through start_download usually carries the name it was uploaded under."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    shutil.copyfile(atlas.blobs_by_name["all.h5ad"], downloads / "all.h5ad")
    row = by_name(wait_for(verifier, verifier.start("gut", "gut", str(downloads))["job_id"], ("done",)))["all.h5ad"]
    assert (row["status"], row["tracker_name"], row["kind"]) == ("verified", "all-r1-wip-1.h5ad", "integrated")


def test_two_tracker_files_with_one_stem_are_reported_not_guessed():
    listed = {
        "x-r1-wip-3.h5ad": [{"entry": {"kind": "integrated", "fileId": "a", "fileName": "x.h5ad"}}],
        "x-r1-wip-1.h5ad": [{"entry": {"kind": "source", "fileId": "b", "fileName": "x.h5ad"}}],
    }
    for name in ("x-r1-wip-2.h5ad", "x.h5ad"):  # another wip of either, or the name both were uploaded under
        local = [{"name": name, "folder_kind": None}]
        classify(local, listed)
        assert local[0]["status"] == "ambiguous", name
        assert [m["name"] for m in local[0]["matches"]] == ["x-r1-wip-1.h5ad", "x-r1-wip-3.h5ad"]


def test_a_download_name_that_is_another_files_upload_name_is_ambiguous():
    listed = {
        "x-r1-wip-1.h5ad": [{"entry": {"kind": "integrated", "fileId": "a", "fileName": "x.h5ad"}}],
        "x-r1-wip-1-r1-wip-1.h5ad": [{"entry": {"kind": "source", "fileId": "b", "fileName": "x-r1-wip-1.h5ad"}}],
    }
    local = [{"name": "x-r1-wip-1.h5ad", "folder_kind": None}]
    missing = classify(local, listed)
    assert local[0]["status"] == "ambiguous" and "file_id" not in local[0]
    assert [m["name"] for m in local[0]["matches"]] == ["x-r1-wip-1-r1-wip-1.h5ad", "x-r1-wip-1.h5ad"]
    assert [m["name"] for m in missing] == ["x-r1-wip-1-r1-wip-1.h5ad", "x-r1-wip-1.h5ad"]


def test_a_folder_with_no_h5ad_files_says_so(verifier, tmp_path):
    (tmp_path / "empty").mkdir()
    result = verifier.start("gut", "gut", str(tmp_path / "empty"))
    assert result["state"] == "done" and result["message"] == f"No .h5ad files in {(tmp_path / 'empty').resolve()}"


def test_an_unreadable_folder_is_refused_by_name(verifier, atlas, tmp_path, monkeypatch):
    (tmp_path / "locked").mkdir()

    def denied(self):
        raise PermissionError(1, "Operation not permitted", str(self))

    monkeypatch.setattr(Path, "iterdir", denied)
    with pytest.raises(CheckError, match="Cannot read .*locked: Operation not permitted"):
        verifier.start("gut", "gut", str(tmp_path / "locked"))
    assert not atlas.links  # refused before any file was presigned


def test_a_running_job_for_the_same_folder_is_reused(verifier, atlas, tmp_path, monkeypatch):
    root, other = tmp_path / "gut-v1", tmp_path / "Downloads"
    copy(atlas, "all.h5ad", folder(root, "integrated-objects"))
    other.mkdir()
    copy(atlas, "all.h5ad", other)
    monkeypatch.setattr(verify_module, "spawn_worker", lambda *args: 0)  # the job stays queued
    first = verifier.start("gut", "gut", str(root))
    again = verifier.start("gut", "gut", str(root))
    assert again["job_id"] == first["job_id"] and again["message"] == f"Already verifying {root.resolve()}"
    assert verifier.start("gut", "gut", str(other))["job_id"] != first["job_id"]
