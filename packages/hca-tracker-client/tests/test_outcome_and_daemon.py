"""finalize under a concurrent call, and connect() trusting only the recorded aria2c."""

import copy
import os
import threading
from xmlrpc.server import SimpleXMLRPCServer

from hca_tracker_client.daemon import CONF, PIDFILE, connect, daemon_dir
from hca_tracker_client.outcome import finalize
from hca_tracker_client.store import DONE, Job, JobStore


def test_finalize_twice_from_stale_copies(tmp_path):
    """The hook and download_status can both finalize; the slower one must not fail."""
    store = JobStore(tmp_path)
    final = tmp_path / "x-r1.h5ad"
    job = Job("a1b2", "gut", "gut", "v1.0", final.name, "f1", str(final), 4, None, state="downloading")
    store.create(job)
    job.part.write_bytes(b"abcd")
    stale = copy.deepcopy(job)

    assert finalize(job, store).state == DONE
    assert finalize(stale, store).state == DONE
    assert final.read_bytes() == b"abcd"


def test_finished_record_is_never_rewritten(tmp_path):
    """A copy loaded before the hook recorded the outcome cannot undo it."""
    store = JobStore(tmp_path)
    job = Job("c3d4", "gut", "gut", "v1.0", "x", "f1", str(tmp_path / "x"), 4, "ab", state="downloading")
    store.create(job)
    stale = copy.deepcopy(job)
    store.end(job, DONE, "Size and SHA-256 verified")
    stale.state = "verifying"
    assert store.save(stale).state == DONE
    assert store.load("c3d4").state == DONE


def test_deleted_record_is_not_recreated(tmp_path):
    """A hook that loaded a job just before delete_download must not bring its record back."""
    store = JobStore(tmp_path)
    job = Job("e5f6", "gut", "gut", "v1.0", "x", "f1", str(tmp_path / "x"), 4, "ab", state="downloading")
    store.create(job)
    stale = copy.deepcopy(job)
    store.delete("e5f6")
    store.end(stale, DONE, "Size and SHA-256 verified")
    assert store.load("e5f6") is None


def test_connect_ignores_a_listener_once_the_recorded_aria2c_is_gone(tmp_path):
    """Another user listening on a dead daemon's port must not be sent anything."""
    server = SimpleXMLRPCServer(("127.0.0.1", 0), logRequests=False)
    server.register_function(lambda token: {"version": "1.37.0"}, "aria2.getVersion")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        directory = daemon_dir(tmp_path)
        directory.mkdir()
        (directory / CONF).write_text(f"rpc-listen-port={server.server_address[1]}\nrpc-secret=s\n")
        (directory / PIDFILE).write_text(str(os.getpid()))  # alive, but not aria2c
        assert connect(tmp_path) is None
        (directory / PIDFILE).unlink()
        assert connect(tmp_path) is None
    finally:
        server.shutdown()
