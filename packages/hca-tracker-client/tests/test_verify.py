"""verify_local / adopt_download: classify an atlas folder against the tracker, hash in a worker, adopt."""

import os
import shutil
from pathlib import Path

import pytest

from hca_tracker_client import CheckError, Verifier, verify_worker
from hca_tracker_client import verify as verify_module
from hca_tracker_client.api import Probe
from hca_tracker_client.store import INTERRUPTED, JobStore
from hca_tracker_client.verify import check_sizes, file_stem
from hca_tracker_client.verify_worker import hash_entry

from .conftest import make_config, make_file, requires_aria2, wait_for

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
    target = to / (as_name or name.replace(".h5ad", "-r1.h5ad"))
    shutil.copyfile(atlas.blobs_by_name[name], target)
    return target


def by_name(result: dict) -> dict[str, dict]:
    return {row["name"]: row for row in result["files"]}


def test_file_stem():
    assert file_stem("hgca-v1-kong-2023-v3-r1-wip-6.h5ad") == "hgca-v1-kong-2023-v3"
    assert file_stem("gut-r1.h5ad") == "gut"
    assert file_stem("Human liver cell atlas - all cells.h5ad") == "Human liver cell atlas - all cells"


def test_mixed_folder_is_classified(verifier, atlas, tmp_path):
    root = tmp_path / "gut-v1"
    integrated, source = folder(root, "integrated-objects"), folder(root, "source-datasets")
    copy(atlas, "all.h5ad", integrated)  # current
    copy(atlas, "kong.h5ad", integrated)  # a source dataset in the integrated folder
    copy(atlas, "myeloid.h5ad", integrated, "myeloid-r0.h5ad")  # an older revision
    make_file(integrated / "notes.h5ad", 10)  # not a tracker file
    make_file(source / "wells-r1.h5ad", SIZE)  # the tracker's name and size, other bytes
    make_file(integrated / "stroma-r1.h5ad", SIZE + 1)  # the tracker's name, another size
    (integrated / "all-r1.h5ad.part").write_bytes(b"x")  # a download in progress: skipped
    (root / "integrated-objects" / "all-r1-edit-2026-01-01.h5ad").write_bytes(b"x")  # outside tracker-source

    started = verifier.start("gut", "gut", str(root))
    assert started["state"] in ("queued", "hashing", "done")
    result = wait_for(verifier, started["job_id"], ("done", "failed", "interrupted"))
    assert result["state"] == "done", result

    rows = by_name(result)
    assert set(rows) == {
        "all-r1.h5ad",
        "kong-r1.h5ad",
        "myeloid-r0.h5ad",
        "notes.h5ad",
        "wells-r1.h5ad",
        "stroma-r1.h5ad",
    }
    assert rows["all-r1.h5ad"]["status"] == "verified" and rows["all-r1.h5ad"]["misplaced"] is False
    assert rows["kong-r1.h5ad"]["status"] == "verified" and rows["kong-r1.h5ad"]["misplaced"] is True
    assert (rows["myeloid-r0.h5ad"]["status"], rows["myeloid-r0.h5ad"]["current_name"]) == ("stale", "myeloid-r1.h5ad")
    assert rows["notes.h5ad"]["status"] == "unknown"
    assert rows["wells-r1.h5ad"]["status"] == "mismatch"
    assert rows["stroma-r1.h5ad"]["status"] == "size_mismatch"
    assert [m["name"] for m in result["missing"]] == ["myeloid-r1.h5ad"]
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
    make_file(downloads / "nested" / "wells-r1.h5ad", SIZE)  # not directly in the folder: not read
    result = wait_for(verifier, verifier.start("gut", "gut", str(downloads))["job_id"], ("done",))
    assert result["layout"] == "folder"
    rows = by_name(result)
    assert set(rows) == {"all-r1.h5ad", "kong-r1.h5ad", "notes.h5ad"}
    assert (rows["all-r1.h5ad"]["status"], rows["all-r1.h5ad"]["kind"]) == ("verified", "integrated")
    assert (rows["kong-r1.h5ad"]["status"], rows["kong-r1.h5ad"]["kind"]) == ("verified", "source")
    assert "misplaced" not in rows["all-r1.h5ad"]
    assert "missing" not in result and "missing" not in result["counts"]


def test_no_such_folder_is_refused(verifier, tmp_path):
    with pytest.raises(CheckError, match="No folder at"):
        verifier.start("gut", "gut", str(tmp_path / "absent"))


def test_a_probe_without_a_size_falls_back_to_the_listed_size(monkeypatch):
    local = [{"name": "x-r1.h5ad", "file_id": "f", "size_bytes": 10}]
    listed = {"x-r1.h5ad": {"entry": {"sizeBytes": 99}, "presigned": None}}
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
    assert by_name(verifier.status(started["job_id"]))["all-r1.h5ad"]["status"] == "pending"


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
    shutil.copyfile(blob, folder(root, "integrated-objects") / "bare-r1.h5ad")
    result = Verifier(make_config(cache_dir, tracker)).start("gut", "gut", str(root))
    assert result["state"] == "done"
    assert by_name(result)["bare-r1.h5ad"]["status"] == "no_checksum"


def test_hash_entry_reports_a_changed_file(tmp_path):
    path = make_file(tmp_path / "f.h5ad", 100)
    stat = path.stat()
    entry = {"path": str(path), "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256_expected": "0" * 64}
    assert hash_entry(entry)["status"] == "mismatch"
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert hash_entry(entry) == {"status": "changed"}
    path.unlink()
    assert hash_entry(entry)["status"] == "unreadable"


def _verified(verifier, atlas, tmp_path) -> Path:
    root = tmp_path / "gut-v1"
    target = copy(atlas, "all.h5ad", folder(root, "integrated-objects"))
    result = wait_for(verifier, verifier.start("gut", "gut", str(root))["job_id"], ("done",))
    assert by_name(result)["all-r1.h5ad"]["status"] == "verified"
    return target


@requires_aria2
def test_adopted_file_is_a_cached_download(verifier, atlas, downloads, plenty_of_space, tmp_path):
    target = _verified(verifier, atlas, tmp_path)
    adopted = verifier.adopt("gut", "gut", str(target))
    assert (adopted["state"], adopted["verified"], adopted["path"]) == ("done", "sha256", str(target.resolve()))

    cached = downloads.start("gut", "gut", "all.h5ad", dest_dir=str(target.parent))
    assert cached["cached"] is True and cached["job_id"] == adopted["job_id"]
    again = verifier.adopt("gut", "gut", str(target))
    assert again["cached"] is True and again["job_id"] == adopted["job_id"]


def test_a_moved_file_is_adopted_where_it_now_is(verifier, atlas, cache_dir, tmp_path):
    target = _verified(verifier, atlas, tmp_path)
    moved = tmp_path / "elsewhere" / target.name
    moved.parent.mkdir()
    target.rename(moved)  # keeps size and modification time
    adopted = verifier.adopt("gut", "gut", str(moved))
    assert adopted["path"] == str(moved.resolve())
    assert [job.path for job in JobStore(cache_dir).all()] == [str(moved.resolve())]


def test_a_file_changed_since_verification_is_refused(verifier, atlas, tmp_path):
    target = _verified(verifier, atlas, tmp_path)
    stat = target.stat()
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    with pytest.raises(CheckError, match="No finished verification"):
        verifier.adopt("gut", "gut", str(target))


def test_a_mismatch_is_never_adopted(verifier, atlas, cache_dir, tmp_path):
    root = tmp_path / "gut-v1"
    bad = make_file(folder(root, "source-datasets") / "wells-r1.h5ad", SIZE)
    wait_for(verifier, verifier.start("gut", "gut", str(root))["job_id"], ("done",))
    with pytest.raises(CheckError, match="was not verified"):
        verifier.adopt("gut", "gut", str(bad))
    assert JobStore(cache_dir).all() == []


def test_a_tracker_file_replaced_since_verification_is_refused(verifier, atlas, tmp_path):
    target = _verified(verifier, atlas, tmp_path)
    blob = next(b for b in atlas.blobs.values() if b.name == "all.h5ad")
    blob.sha256 = "f" * 64  # a new upload under the same name
    with pytest.raises(CheckError, match="has changed since it was verified"):
        verifier.adopt("gut", "gut", str(target))


def test_adopt_records_the_version_it_was_verified_against(verifier, atlas, cache_dir, tmp_path):
    target = _verified(verifier, atlas, tmp_path)
    assert verifier.adopt("gut", "gut", str(target))["version"] == "v1.0"
    assert [job.version for job in JobStore(cache_dir).all()] == ["v1.0"]


def test_adopt_needs_the_atlas_it_was_verified_against(verifier, atlas, tmp_path):
    target = _verified(verifier, atlas, tmp_path)
    with pytest.raises(CheckError, match="was verified against gut/gut"):
        verifier.adopt("lung", "adipose", str(target))


def test_files_are_never_written(verifier, atlas, tmp_path):
    target = _verified(verifier, atlas, tmp_path)
    before = (target.stat().st_mtime_ns, target.read_bytes())
    verifier.adopt("gut", "gut", str(target))
    assert (target.stat().st_mtime_ns, target.read_bytes()) == before
