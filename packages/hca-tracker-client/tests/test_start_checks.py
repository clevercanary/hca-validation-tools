"""start_download's checks: each fails (or asks for confirmation) before any file data is fetched."""

import pytest

from hca_tracker_client import CheckError, SelectionError, checks

from .conftest import make_config, make_file, requires_aria2


@pytest.fixture
def small_file(tracker):
    path = make_file(tracker.data_dir / "small", 2_000_000)
    tracker.add_file(tracker.ids["gut"], "gut-r1.h5ad", path)
    return path


def test_selection_errors_come_first(downloads, small_file):
    with pytest.raises(SelectionError, match="network must be given"):
        downloads.start("", "gut", "gut-r1.h5ad")


def test_aria2c_missing_fails_before_download(downloads, tracker, small_file, monkeypatch, plenty_of_space):
    monkeypatch.setattr(checks.shutil, "which", lambda name: None)
    with pytest.raises(CheckError, match="aria2c not found on PATH"):
        downloads.start("gut", "gut", "gut-r1.h5ad")
    assert tracker.served_bytes == 1  # the 1-byte probe only
    assert not downloads.store.all()


@requires_aria2
def test_not_enough_space(downloads, tracker, small_file, monkeypatch):
    monkeypatch.setattr(checks, "free_bytes", lambda path: 3_000_000_000)
    with pytest.raises(CheckError, match=r"Not enough space: needs 5.0 GB, 3.0 GB free on "):
        downloads.start("gut", "gut", "gut-r1.h5ad")
    assert tracker.served_bytes == 1


@requires_aria2
def test_folder_not_writable(downloads, tracker, small_file, tmp_path, plenty_of_space):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        with pytest.raises(CheckError, match="is not writable"):
            downloads.start("gut", "gut", "gut-r1.h5ad", dest_dir=str(locked / "sub"))
    finally:
        locked.chmod(0o700)


@requires_aria2
def test_over_threshold_needs_confirm(cache_dir, tracker, small_file, plenty_of_space):
    from hca_tracker_client import Downloads

    downloads = Downloads(make_config(cache_dir, tracker, confirm_bytes=1_000_000))
    result = downloads.start("gut", "gut", "gut-r1.h5ad")
    assert result["needs_confirmation"] is True
    assert result["size"] == "2.0 MB"
    assert result["free"] == "1.0 TB"
    assert result["estimated_time"] is None
    assert result["message"].endswith("Call start_download again with confirm=true to download it")
    assert tracker.served_bytes == 1
    assert not downloads.store.all()


def test_existing_unverified_file_is_not_overwritten(downloads, tracker, small_file):
    target = downloads.cache_dir / "gut" / "gut_v1.0" / "gut-r1.h5ad"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"someone else's file")
    with pytest.raises(CheckError, match="already exists but is not a verified download"):
        downloads.start("gut", "gut", "gut-r1.h5ad")
    assert target.read_bytes() == b"someone else's file"


def test_size_mismatch_between_tracker_and_object(downloads, tracker):
    path = make_file(tracker.data_dir / "f", 1000)
    tracker.add_file(tracker.ids["gut"], "gut-r1.h5ad", path, listed_size=999)
    with pytest.raises(CheckError, match="lists gut-r1.h5ad as 999 bytes, but the stored file is 1000 bytes"):
        downloads.start("gut", "gut", "gut-r1.h5ad")


def test_unsafe_file_name_rejected(downloads, tracker):
    from hca_tracker_client import TrackerError

    tracker.add_file(tracker.ids["gut"], "../escape.h5ad", make_file(tracker.data_dir / "f", 10))
    with pytest.raises(TrackerError, match="unusable file name"):
        downloads.start("gut", "gut", "file-1")
