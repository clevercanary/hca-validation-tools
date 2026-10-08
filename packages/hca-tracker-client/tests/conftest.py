"""Shared fixtures: a fake tracker with a few atlases, and a cache folder with its own aria2 daemon."""

import os
import shutil
import time
from pathlib import Path

import pytest

from hca_tracker_client import Config, Downloads
from hca_tracker_client.daemon import shutdown
from hca_tracker_client.testing import FakeTracker

requires_aria2 = pytest.mark.skipif(shutil.which("aria2c") is None, reason="aria2c is not installed")


def make_file(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(os.urandom(size))
    return path


@pytest.fixture
def tracker(tmp_path):
    """Atlases mirroring the cases selection has to handle.

    ``adipose`` exists in two networks; ``lung/adipose`` has two generations
    with two revisions each, only some published.
    """
    with FakeTracker() as fake:
        fake.ids = {
            "adipose": fake.add_atlas("adipose", "adipose", 1, 0, published=True),
            "lung-1.0": fake.add_atlas("lung", "adipose", 1, 0, published=True),
            "lung-1.1": fake.add_atlas("lung", "adipose", 1, 1),
            "lung-2.0": fake.add_atlas("lung", "adipose", 2, 0, published=True),
            "lung-2.1": fake.add_atlas("lung", "adipose", 2, 1),
            "gut": fake.add_atlas("gut", "gut", 1, 0),
        }
        fake.data_dir = tmp_path / "bucket"
        yield fake


@pytest.fixture
def cache_dir(tmp_path):
    cache = tmp_path / "cache"
    yield cache
    shutdown(cache)


def make_config(cache_dir: Path, tracker: FakeTracker, **overrides) -> Config:
    values = {
        "tracker_url": tracker.url,
        "api_token": tracker.token,
        "cache_dir": cache_dir,
        "confirm_bytes": 5_000_000_000,
        "max_concurrent": 2,
    }
    values.update(overrides)
    return Config(**values)


@pytest.fixture
def downloads(cache_dir, tracker):
    return Downloads(make_config(cache_dir, tracker))


@pytest.fixture
def plenty_of_space(monkeypatch):
    """Pretend the disk has 1 TB free, so the 5 GB margin never blocks a test download."""
    monkeypatch.setattr("hca_tracker_client.checks.free_bytes", lambda path: 1_000_000_000_000)


def wait_for(downloads: Downloads, job_id: str, states: tuple[str, ...], timeout: float = 60) -> dict:
    """Poll a job until it reaches one of ``states``."""
    deadline = time.monotonic() + timeout
    while True:
        status = downloads.status(job_id)
        if status["state"] in states:
            return status
        if time.monotonic() > deadline:
            raise AssertionError(f"job {job_id} still {status['state']} after {timeout}s: {status}")
        time.sleep(0.1)
