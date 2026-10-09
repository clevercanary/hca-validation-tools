"""start_download's checks: each fails before any file data is fetched."""

import pytest

from hca_tracker_client import CheckError, SelectionError, checks

from .conftest import make_file, requires_aria2


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


@pytest.mark.parametrize(
    "name", ["x-r1.h5ad\n allow-overwrite=true", "x\\r1.h5ad", "x\x00.h5ad", "x.h5ad.part", "x.h5ad.part.aria2"]
)
def test_control_characters_in_file_name_rejected(downloads, tracker, name):
    """A newline would become extra options in aria2's session file."""
    from hca_tracker_client import TrackerError

    tracker.add_file(tracker.ids["gut"], name, make_file(tracker.data_dir / "f", 10))
    with pytest.raises(TrackerError, match="unusable file name"):
        downloads.start("gut", "gut", "file-1")


def test_control_characters_in_dest_dir_rejected(downloads, small_file, tmp_path):
    """dest_dir is saved as aria2's dir option, so a newline would inject options too."""
    with pytest.raises(CheckError, match="contains a control character"):
        downloads.start("gut", "gut", "gut-r1.h5ad", dest_dir=str(tmp_path / "a\n dir=b"))


def test_file_without_checksum_refused(downloads, tracker):
    tracker.add_file(tracker.ids["gut"], "plain-r1.h5ad", make_file(tracker.data_dir / "plain", 1000), sha256=None)
    with pytest.raises(CheckError, match="has no source checksum"):
        downloads.start("gut", "gut", "plain-r1.h5ad")
    assert tracker.served_bytes == 1
    assert not downloads.store.all()


@pytest.mark.parametrize(("network", "slug"), [("..", "gut"), ("gut", "../../etc"), ("/abs", "gut")])
def test_unsafe_network_or_atlas_rejected(cache_dir, tmp_path, network, slug):
    """network and atlas become path components of the default destination."""
    from hca_tracker_client import Downloads, TrackerError
    from hca_tracker_client.testing import FakeTracker

    from .conftest import make_config

    with FakeTracker() as fake:
        atlas_id = fake.add_atlas(network, slug, 1, 0)
        fake.add_file(atlas_id, "x-r1.h5ad", make_file(tmp_path / "x", 10))
        with pytest.raises(TrackerError, match="unusable"):
            Downloads(make_config(cache_dir, fake)).start(network, slug, "x-r1.h5ad")


def test_dest_dir_inside_cache_state_rejected(downloads, small_file):
    with pytest.raises(CheckError, match="holds the download cache's own state"):
        downloads.start("gut", "gut", "gut-r1.h5ad", dest_dir=str(downloads.cache_dir / "aria2"))


def test_restart_keeps_old_files_when_a_check_fails(downloads, small_file, monkeypatch):
    part = downloads.cache_dir / "gut" / "gut_v1.0" / "gut-r1.h5ad.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"partial")
    monkeypatch.setattr(checks.shutil, "which", lambda name: None)
    with pytest.raises(CheckError, match="aria2c not found"):
        downloads.start("gut", "gut", "gut-r1.h5ad", restart=True)
    assert part.read_bytes() == b"partial"
