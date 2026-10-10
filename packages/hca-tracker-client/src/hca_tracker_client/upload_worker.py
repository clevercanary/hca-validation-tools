"""The detached process that runs one upload job: ``python -m hca_tracker_client.upload_worker <job_id> <cache_dir>``.

``Uploads.start`` spawns it in its own session with stdout and stderr on the
job's log, so the transfer tool's progress lands there and the job outlives
the MCP server. It records the outcome in the job's record; ``Uploads.status``
notices if it dies without doing so.
"""

import argparse
import sys
import time
from pathlib import Path

from .uploads import DONE, FAILED, UPLOADING, UploadStore, load_engine


def run(job_id: str, cache_dir: Path) -> int:
    store = UploadStore(cache_dir)
    job = store.load(job_id)
    if job is None:
        print(f"No upload job {job_id!r} in {store.directory}", file=sys.stderr)
        return 2
    expected = {entry["name"] for entry in job.files}

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
        store.end(job_id, FAILED, f"hca-smart-sync failed: {type(error).__name__}: {error}")
        return 1

    manifest = result.get("manifest_path")
    if result.get("error"):
        store.end(job_id, FAILED, f"hca-smart-sync reported {result['error']!r}", manifest)
        return 1
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id")
    parser.add_argument("cache_dir", type=Path)
    args = parser.parse_args(argv)
    return run(args.job_id, args.cache_dir)


if __name__ == "__main__":
    sys.exit(main())
