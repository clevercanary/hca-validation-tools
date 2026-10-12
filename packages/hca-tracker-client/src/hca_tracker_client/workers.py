"""Detached worker processes: how upload and verify jobs start theirs, and reap them once they exit."""

import os
import subprocess
import sys
import threading
from pathlib import Path

# A queued job with no pid this long after it was created is a spawn that never completed.
SPAWN_GRACE_SECONDS = 60

# Workers this process started, reaped on every status refresh and spawn so none is left a zombie.
_WORKERS: list[subprocess.Popen] = []
_WORKERS_LOCK = threading.Lock()


def reap_workers() -> None:
    with _WORKERS_LOCK:
        _WORKERS[:] = [worker for worker in _WORKERS if worker.poll() is None]


def worker_environment() -> dict[str, str]:
    """The worker's environment: this process's, without the tracker token it and the transfer tools never need."""
    return {key: value for key, value in os.environ.items() if key != "HCA_TRACKER_API_TOKEN"}


def spawn_worker(module: str, job_id: str, cache_dir: Path, log_path: str) -> int:
    """Start ``python -m <module> <job_id> <cache_dir>`` detached, its output going to ``log_path``; returns its pid.

    ``start_new_session`` puts the child in its own session before it runs a
    single line of ours, so a signal to this process's group can never reach
    it. The ``Popen`` is kept in ``_WORKERS`` and polled by ``reap_workers``,
    so the worker is reaped when it exits and the object is never collected
    while its child runs (which ``Popen`` warns about).
    """
    reap_workers()
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    with Path(log_path).open("ab") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", module, job_id, str(cache_dir)],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=worker_environment(),
            start_new_session=True,
            close_fds=True,
        )
    with _WORKERS_LOCK:
        _WORKERS.append(process)
    return process.pid
