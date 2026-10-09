"""Each check before downloading fails with a message that says what to do."""

import subprocess
from pathlib import Path

import pytest

from hca_tracker_client import CheckError, checks


def fake_aria2c(monkeypatch, which, stdout="", returncode=0):
    monkeypatch.setattr(checks.shutil, "which", lambda name: which)
    monkeypatch.setattr(
        checks.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, returncode, stdout=stdout, stderr=""),
    )


def test_aria2c_missing(monkeypatch):
    fake_aria2c(monkeypatch, None)
    with pytest.raises(CheckError, match=r"aria2c not found on PATH; install aria2: `brew install aria2`"):
        checks.find_aria2c()


def test_aria2c_too_old(monkeypatch):
    fake_aria2c(monkeypatch, "/usr/bin/aria2c", stdout="aria2 version 1.34.0\nCopyright...")
    with pytest.raises(CheckError, match=r"aria2c 1.34.0 at /usr/bin/aria2c is older than the minimum 1.35.0"):
        checks.find_aria2c()


def test_aria2c_unparseable(monkeypatch):
    fake_aria2c(monkeypatch, "/usr/bin/aria2c", stdout="garbage")
    with pytest.raises(CheckError, match="does not report a version"):
        checks.find_aria2c()


def test_aria2c_ok(monkeypatch):
    fake_aria2c(monkeypatch, "/opt/bin/aria2c", stdout="aria2 version 1.37.0\n")
    assert checks.find_aria2c() == ("/opt/bin/aria2c", "1.37.0")


def test_folder_not_writable(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        with pytest.raises(CheckError, match=f"Folder {locked} is not writable"):
            checks.check_writable(locked)
    finally:
        locked.chmod(0o700)


def test_folder_created(tmp_path):
    target = tmp_path / "a" / "b"
    checks.check_writable(target)
    assert target.is_dir()
    assert list(target.iterdir()) == []


def test_not_enough_space(tmp_path, monkeypatch):
    gb = checks.GB
    monkeypatch.setattr(checks, "free_bytes", lambda path: 41 * gb)
    with pytest.raises(CheckError) as error:
        checks.check_space(tmp_path, remaining=50 * gb, size=50 * gb, reserved=8 * gb)
    assert str(error.value) == (
        f"Not enough space: needs 63.0 GB (including 8.0 GB reserved for other downloads), 41.0 GB free on {tmp_path}"
    )


def test_margin_is_larger_of_ten_percent_and_five_gb():
    assert checks.margin(10 * checks.GB) == 5 * checks.GB
    assert checks.margin(80 * checks.GB) == 8 * checks.GB


def test_space_check_on_folder_not_yet_created(tmp_path):
    free = checks.check_space(tmp_path / "new" / "deeper", remaining=1, size=1, reserved=0)
    assert free > 0
    assert checks.existing_ancestor(Path(tmp_path / "new" / "deeper")) == tmp_path
