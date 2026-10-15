"""The detached process that runs one verify job: ``python -m hca_tracker_client.verify_worker <job_id> <cache_dir>``.

``Verifier.start`` spawns it in a session of its own, so it outlives the MCP
server. It hashes the job's pending files and records each result in the
job's record; ``Verifier.status`` notices if it dies without finishing.
"""

import argparse
import contextlib
import hashlib
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .store import DONE
from .verify import CHANGED, HASHING, MISMATCH, PENDING, UNREADABLE, VERIFIED, VerifyJob, VerifyStore

CHUNK = 8 << 20
WORKERS = 4


def _identity(stat: os.stat_result) -> tuple[int, ...]:
    """Which file it is and its state: the change time moves on any write or timestamp reset."""
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def hash_entry(entry: dict) -> dict:
    """The file's outcome: verified or mismatch by SHA-256, changed if it was modified or replaced around the hash."""
    path = Path(entry["path"])
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if (opened.st_size, opened.st_mtime_ns) != (entry["size_bytes"], entry["mtime_ns"]):
                return {"status": CHANGED}
            while chunk := handle.read(CHUNK):
                digest.update(chunk)
            # Written to, or another file put at the path, while it was being read.
            if not _identity(opened) == _identity(os.fstat(handle.fileno())) == _identity(path.stat()):
                return {"status": CHANGED}
    except OSError as error:
        return {"status": UNREADABLE, "error": f"{error.strerror}: {error.filename}"}
    sha256 = digest.hexdigest()
    return {"status": VERIFIED if sha256 == entry["sha256_expected"] else MISMATCH, "sha256": sha256}


def run(job_id: str, cache_dir: Path) -> int:
    store = VerifyStore(cache_dir)
    job = store.load(job_id)
    if job is None:
        print(f"No verify job {job_id!r} in {store.directory}", file=sys.stderr)
        return 2

    def begin(current: VerifyJob) -> None:
        current.state = HASHING
        current.started_at = time.time()
        current.pid = os.getpid()  # the parent records it too; this covers a parent that could not

    if (current := store.update(job_id, begin)) is None or current.state != HASHING:
        return 0  # ended (or deleted) before the worker began: nothing it hashed would be kept
    # Largest first, so the biggest file never runs alone at the end while the other threads sit idle.
    pending = sorted(
        (i for i, entry in enumerate(job.files) if entry["status"] == PENDING),
        key=lambda i: -job.files[i]["size_bytes"],
    )

    def work(index: int) -> None:
        current = store.load(job_id)
        if current is None or current.state != HASHING:  # ended under the worker: stop reading files
            return
        outcome = hash_entry(job.files[index])
        store.update(job_id, lambda current: current.files[index].update(outcome))

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(work, pending))

    final = store.load(job_id) or job
    counts = Counter(final.files[index]["status"] for index in pending)
    summary = ", ".join(f"{n} {status}" for status, n in sorted(counts.items()))
    store.end(job_id, DONE, f"{len(pending)} files hashed: {summary}")
    return 0


def main(argv: list[str] | None = None) -> int:
    with contextlib.suppress(OSError):  # a session leader already when Verifier.start spawned it
        os.setsid()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id")
    parser.add_argument("cache_dir", type=Path)
    args = parser.parse_args(argv)
    return run(args.job_id, args.cache_dir)


if __name__ == "__main__":
    sys.exit(main())
