"""The detached process that runs one upload job: ``python -m hca_tracker_client.upload_worker <job_id> <cache_dir>``.

``Uploads.start`` spawns it in a session of its own with stdout and stderr on
the job's log, so the transfer tool's progress lands there and it outlives
the MCP server. It records the outcome in the job's record; ``Uploads.status``
notices if it dies without doing so.
"""

import argparse
import contextlib
import os
import sys
import time
from pathlib import Path

from .errors import redact
from .uploads import DONE, FAILED, UPLOADING, UploadStore, folder_changes, load_engine


def run(job_id: str, cache_dir: Path) -> int:
    store = UploadStore(cache_dir)
    job = store.load(job_id)
    if job is None:
        print(f"No upload job {job_id!r} in {store.directory}", file=sys.stderr)
        return 2
    expected = {entry["name"] for entry in job.files}
    changes = folder_changes(Path(job.local_path), job.snapshot)
    if changes:  # the plan start() returned is the plan that runs; a changed folder needs a new one
        store.end(
            job_id,
            FAILED,
            f"The folder changed since the plan: {changes}; nothing was uploaded. Run start_upload again",
        )
        return 1

    def started(name: str) -> None:
        store.update(job_id, lambda current: setattr(current, "current_file", name))

    def finished(name: str, size: int) -> None:
        def change(current) -> None:
            if name in expected and name not in current.files_done:
                current.files_done.append(name)
                current.bytes_done += size
            current.current_file = None

        store.update(job_id, change)

    def begin(current) -> None:
        current.state = UPLOADING
        current.started_at = time.time()

    store.update(job_id, begin)
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    try:
        engine = load_engine(job.engine)(job.profile, sys.stdout, started, finished)
        result = engine.sync(Path(job.local_path), job.target, force=job.force)
    except Exception as error:
        current = store.load(job_id)
        unconfirmed = sorted(expected - set(current.files_done if current else []))
        store.end(
            job_id,
            FAILED,
            redact(  # the error text last: a URL in it would swallow any punctuation after it
                f"hca-smart-sync failed; not confirmed uploaded: {', '.join(unconfirmed) or 'none'}. Run start_upload "
                f"again (files already in the bucket are skipped). Error: {type(error).__name__}: {error}"
            ),
        )
        return 1

    manifest = result.get("manifest_path")
    if result.get("error") == "access_denied":  # access that the plan had can be gone by the time the worker runs
        store.end(
            job_id,
            FAILED,
            f"The AWS profile {job.profile!r} can no longer list {job.target} (hca-smart-sync's access check failed: "
            f"access denied, no such bucket, or no valid credentials for the profile). Not uploaded: "
            f"{', '.join(sorted(expected))}. Run start_upload again once access is restored",
        )
        return 1
    if result.get("error"):
        store.end(
            job_id,
            FAILED,
            f"hca-smart-sync reported {result['error']!r}; not uploaded: {', '.join(sorted(expected))}. "
            "Run start_upload again",
            manifest,
        )
        return 1
    if result.get("all_up_to_date"):  # uploaded by someone else between the plan and now

        def all_done(current) -> None:
            current.files_done = [entry["name"] for entry in current.files]
            current.bytes_done = current.total_bytes

        store.update(job_id, all_done)
        store.end(job_id, DONE, "Every file was already in the bucket with the same SHA-256; nothing to upload")
        return 0
    uploaded = set(result.get("files") or [])
    missing = sorted(expected - uploaded)
    if missing:
        store.end(
            job_id,
            FAILED,
            f"{len(uploaded)} of {len(expected)} files uploaded; not uploaded: {', '.join(missing)}. "
            "See the log, then run start_upload again (files already in the bucket are skipped)",
            manifest,
        )
        return 1
    store.end(job_id, DONE, f"{len(uploaded)} files uploaded and the manifest written", manifest)
    return 0


def main(argv: list[str] | None = None) -> int:
    with contextlib.suppress(OSError):  # a session leader already when Uploads.start spawned it
        os.setsid()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id")
    parser.add_argument("cache_dir", type=Path)
    args = parser.parse_args(argv)
    return run(args.job_id, args.cache_dir)


if __name__ == "__main__":
    sys.exit(main())
