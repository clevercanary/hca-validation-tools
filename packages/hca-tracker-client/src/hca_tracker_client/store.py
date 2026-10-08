"""Job records: one JSON file per download in ``<cache>/jobs/``.

A record is the only place a finished job's outcome lives. aria2 forgets a
download once it ends (and is told to, for failures, so its session does not
retry them), so the hook writes the outcome here. The record never holds the
presigned URL.
"""

import contextlib
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

QUEUED = "queued"
DOWNLOADING = "downloading"
VERIFYING = "verifying"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"
INTERRUPTED = "interrupted"
ACTIVE = (QUEUED, DOWNLOADING, VERIFYING)

# aria2 error codes (see "EXIT STATUS" in the aria2c manual).
CHECKSUM_MISMATCH = 32


@dataclass
class Job:
    """One download, from start to its outcome.

    ``job_id`` is also the aria2 GID, so a hook call or an aria2 status maps
    straight back to its record.
    """

    job_id: str
    network: str
    atlas: str
    version: str
    file_name: str
    file_id: str
    path: str
    size: int
    sha256: str | None
    state: str = QUEUED
    message: str | None = None
    error_code: int | None = None
    verified: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    @property
    def final(self) -> Path:
        return Path(self.path)

    @property
    def part(self) -> Path:
        return Path(self.path + ".part")

    @property
    def control(self) -> Path:
        """aria2's control file, which records which pieces are done."""
        return Path(self.path + ".part.aria2")

    @property
    def checksum_failed(self) -> bool:
        return self.state == FAILED and self.error_code == CHECKSUM_MISMATCH


class JobStore:
    def __init__(self, cache_dir: Path):
        self.directory = cache_dir / "jobs"

    def _file(self, job_id: str) -> Path:
        return self.directory / f"{job_id}.json"

    def save(self, job: Job) -> None:
        """Write the record atomically: the hook and the server may both write."""
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
        with os.fdopen(fd, "w") as handle:
            json.dump(asdict(job), handle, indent=2)
        Path(tmp).replace(self._file(job.job_id))

    def load(self, job_id: str) -> Job | None:
        if not job_id.isalnum():
            return None
        try:
            data = json.loads(self._file(job_id).read_text())
        except (OSError, ValueError):
            return None
        known = {f.name for f in fields(Job)}
        return Job(**{key: value for key, value in data.items() if key in known})

    def all(self) -> list[Job]:
        """Every record, oldest first."""
        if not self.directory.is_dir():
            return []
        jobs = [self.load(path.stem) for path in self.directory.glob("*.json")]
        return sorted((job for job in jobs if job is not None), key=lambda job: job.created_at)

    def for_path(self, path: Path) -> list[Job]:
        """Records for one final file path, oldest first."""
        return [job for job in self.all() if job.path == str(path)]

    def delete(self, job_id: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._file(job_id).unlink()
