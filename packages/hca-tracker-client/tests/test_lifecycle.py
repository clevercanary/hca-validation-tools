"""Download lifecycle against a real aria2 daemon and the fake tracker."""

import json
import os
import signal
import subprocess
import sys
import textwrap
import time

import pytest

from hca_tracker_client import CheckError, Downloads
from hca_tracker_client.daemon import connect, daemon_dir, shutdown

from .conftest import make_config, make_file, requires_aria2, wait_for

pytestmark = [requires_aria2, pytest.mark.usefixtures("plenty_of_space")]

SIZE = 3_000_000


@pytest.fixture
def gut_file(tracker):
    path = make_file(tracker.data_dir / "gut", SIZE)
    tracker.add_file(tracker.ids["gut"], "gut-r1.h5ad", path)
    return path


def test_download_end_to_end(downloads, tracker, gut_file):
    started = downloads.start("gut", "gut", "gut-r1.h5ad")
    assert started["state"] == "queued"
    assert started["path"].endswith("cache/gut/gut_v1.0/gut-r1.h5ad")
    assert started["verification"] == "sha256"

    done = wait_for(downloads, started["job_id"], ("done", "failed"))
    assert done["state"] == "done", done
    assert done["verified"] == "sha256"
    assert done["message"] == "Size and SHA-256 verified"
    final = downloads.cache_dir / "gut" / "gut_v1.0" / "gut-r1.h5ad"
    assert final.read_bytes() == gut_file.read_bytes()
    assert not (final.parent / "gut-r1.h5ad.part").exists()

    again = downloads.start("gut", "gut", "gut-r1.h5ad")
    assert again["cached"] is True
    assert again["state"] == "done"

    listed = downloads.list_files()["files"]
    assert [(f["path"], f["state"], f["verified"]) for f in listed] == [(str(final), "done", "sha256")]


def test_no_checksum_completes_size_only(downloads, tracker):
    path = make_file(tracker.data_dir / "plain", 1000)
    tracker.add_file(tracker.ids["gut"], "plain-r1.h5ad", path, sha256=None)
    started = downloads.start("gut", "gut", "plain-r1.h5ad")
    assert started["verification"] == "size only (no checksum available)"
    done = wait_for(downloads, started["job_id"], ("done", "failed"))
    assert done["state"] == "done"
    assert done["verified"] == "size"
    assert done["message"].startswith("Size verified, no checksum available")


def test_checksum_mismatch_keeps_part_and_blocks_resume(downloads, tracker):
    path = make_file(tracker.data_dir / "bad", 100_000)
    file_id = tracker.add_file(tracker.ids["gut"], "bad-r1.h5ad", path, sha256="0" * 64)
    started = downloads.start("gut", "gut", "bad-r1.h5ad")
    failed = wait_for(downloads, started["job_id"], ("done", "failed"))
    assert failed["state"] == "failed"
    assert failed["error_code"] == 32
    assert failed["message"].startswith("Checksum mismatch")
    part = downloads.cache_dir / "gut" / "gut_v1.0" / "bad-r1.h5ad.part"
    assert failed["partial_path"] == str(part)
    assert part.stat().st_size == 100_000
    assert not (part.parent / "bad-r1.h5ad").exists()

    # aria2 has forgotten it, so a daemon restart will not re-hash it.
    aria2 = connect(downloads.cache_dir)
    assert aria2 is not None
    assert aria2.call("tellStopped", 0, 10, ["gid"]) == []

    with pytest.raises(CheckError, match="failed its checksum and is kept at"):
        downloads.start("gut", "gut", "bad-r1.h5ad")

    tracker.blobs[file_id].sha256 = None
    restarted = downloads.start("gut", "gut", "bad-r1.h5ad", restart=True)
    assert wait_for(downloads, restarted["job_id"], ("done", "failed"))["state"] == "done"


def test_download_survives_the_starting_process(cache_dir, tracker, gut_file):
    """Start in a subprocess that exits at once; follow the job from another process."""
    tracker.rate_bps = 1_000_000
    env = {
        **os.environ,
        "HCA_TRACKER_URL": tracker.url,
        "HCA_TRACKER_API_TOKEN": tracker.token,
        "HCA_TRACKER_CACHE_DIR": str(cache_dir),
    }
    starter = textwrap.dedent(
        """
        import json
        from hca_tracker_client import Downloads, load_config
        from hca_tracker_client import checks
        checks.free_bytes = lambda path: 10**12
        print(json.dumps(Downloads(load_config()).start("gut", "gut", "gut-r1.h5ad")))
        """
    )
    begin = time.monotonic()
    result = subprocess.run([sys.executable, "-c", starter], env=env, capture_output=True, text=True, check=True)
    assert time.monotonic() - begin < 2.5, "start_download should return before the 3 s download finishes"
    job_id = json.loads(result.stdout)["job_id"]

    reader = textwrap.dedent(
        f"""
        import json
        from hca_tracker_client import Downloads, load_config
        print(json.dumps(Downloads(load_config()).status({job_id!r})))
        """
    )
    seen = []
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        out = subprocess.run([sys.executable, "-c", reader], env=env, capture_output=True, text=True, check=True)
        status = json.loads(out.stdout)
        seen.append(status["state"])
        if status["state"] in ("done", "failed"):
            break
        time.sleep(0.2)
    assert seen[-1] == "done", seen
    assert "downloading" in seen


def test_resume_after_link_expires_and_daemon_restarts(downloads, tracker, gut_file):
    tracker.rate_bps = 500_000
    started = downloads.start("gut", "gut", "gut-r1.h5ad")
    status = wait_for(downloads, started["job_id"], ("downloading",))
    deadline = time.monotonic() + 30
    while status.get("progress", {}).get("bytes_done", 0) < SIZE // 3 and time.monotonic() < deadline:
        time.sleep(0.1)
        status = downloads.status(started["job_id"])
    assert status["progress"]["rate"].endswith("/s")

    # The daemon goes away (crash, reboot) and the 48 h link expires meanwhile.
    shutdown(downloads.cache_dir)
    tracker.expire_links()
    tracker.rate_bps = 0
    served_before = tracker.served_bytes

    failed = wait_for(downloads, started["job_id"], ("failed", "done", "interrupted"))
    assert failed["state"] == "failed", failed
    assert failed["message"].startswith("The download link was refused")

    resumed = downloads.start("gut", "gut", "gut-r1.h5ad")
    assert resumed["job_id"] != started["job_id"]
    assert resumed["message"].startswith("Resuming from")
    done = wait_for(downloads, resumed["job_id"], ("done", "failed"))
    assert done["state"] == "done"
    assert done["verified"] == "sha256"
    assert tracker.served_bytes - served_before < SIZE, "resume should not fetch the whole file again"


def test_cancel_then_resume(downloads, tracker, gut_file):
    tracker.rate_bps = 300_000
    started = downloads.start("gut", "gut", "gut-r1.h5ad")
    wait_for(downloads, started["job_id"], ("downloading",))
    time.sleep(1)
    cancelled = downloads.cancel(started["job_id"])
    assert cancelled["state"] == "cancelled"
    assert cancelled["partial_path"].endswith("gut-r1.h5ad.part")

    tracker.rate_bps = 0
    resumed = downloads.start("gut", "gut", "gut-r1.h5ad")
    assert wait_for(downloads, resumed["job_id"], ("done", "failed"))["state"] == "done"


def test_queue_limit(cache_dir, tracker, gut_file):
    downloads = Downloads(make_config(cache_dir, tracker, max_concurrent=1))
    other = make_file(tracker.data_dir / "other", SIZE)
    tracker.add_file(tracker.ids["gut"], "other-r1.h5ad", other)
    tracker.rate_bps = 1_000_000
    first = downloads.start("gut", "gut", "gut-r1.h5ad")
    second = downloads.start("gut", "gut", "other-r1.h5ad")
    wait_for(downloads, first["job_id"], ("downloading",))
    assert downloads.status(second["job_id"])["state"] == "queued"
    jobs = downloads.status()["jobs"]
    assert [j["job_id"] for j in jobs] == [second["job_id"], first["job_id"]]
    tracker.rate_bps = 0
    assert wait_for(downloads, second["job_id"], ("done", "failed"))["state"] == "done"


def test_start_while_downloading_returns_the_running_job(downloads, tracker, gut_file):
    tracker.rate_bps = 500_000
    first = downloads.start("gut", "gut", "gut-r1.h5ad")
    second = downloads.start("gut", "gut", "gut-r1.h5ad")
    assert second["job_id"] == first["job_id"]
    assert second["message"] == "Already downloading"
    tracker.rate_bps = 0
    wait_for(downloads, first["job_id"], ("done",))


def test_delete_download(downloads, tracker, gut_file, tmp_path):
    started = downloads.start("gut", "gut", "gut-r1.h5ad")
    wait_for(downloads, started["job_id"], ("done",))
    with pytest.raises(Exception, match="is not in the download cache"):
        downloads.delete(str(tmp_path / "bucket" / "gut"))
    result = downloads.delete(started["path"])
    assert result["deleted"] == [started["path"]]
    assert not downloads.store.all()
    assert downloads.list_files()["files"] == []


def test_daemon_files_are_private(downloads, tracker, gut_file):
    started = downloads.start("gut", "gut", "gut-r1.h5ad")
    wait_for(downloads, started["job_id"], ("done",))
    directory = daemon_dir(downloads.cache_dir)
    assert directory.stat().st_mode & 0o777 == 0o700
    assert (directory / "aria2.conf").stat().st_mode & 0o777 == 0o600
    # The secret is not on aria2c's command line.
    ps = subprocess.run(["ps", "-ax", "-o", "command="], capture_output=True, text=True).stdout
    aria2_lines = [line for line in ps.splitlines() if "aria2c" in line and str(downloads.cache_dir) in line]
    assert aria2_lines
    assert all("rpc-secret" not in line for line in aria2_lines)


def test_status_restarts_a_dead_daemon(downloads, tracker, gut_file):
    tracker.rate_bps = 500_000
    started = downloads.start("gut", "gut", "gut-r1.h5ad")
    wait_for(downloads, started["job_id"], ("downloading",))
    pid = int((daemon_dir(downloads.cache_dir) / "pid").read_text())
    time.sleep(11)  # past save-session-interval, so the session holds the job
    os.kill(pid, signal.SIGKILL)
    tracker.rate_bps = 0
    assert wait_for(downloads, started["job_id"], ("done", "failed"))["state"] == "done"
