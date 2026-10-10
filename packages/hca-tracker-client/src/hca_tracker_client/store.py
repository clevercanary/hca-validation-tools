"""Job records: one JSON file per download in ``<cache>/jobs/``.

A record is the only place a finished job's outcome lives. aria2 forgets a
download once it ends (and is told to, for failures, so its session does not
retry them), so the hook writes the outcome here. The record never holds the
presigned URL.

``RecordStore`` is the part that is not about downloads: one JSON file per
record, written atomically, with a finished record never rewritten. Upload
jobs (``uploads.py``) keep their records the same way, in their own folder.
"""

import contextlib
import fcntl
import json
import os
import tempfile
import time
from collections.abc import Callable, Generator
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Generic, Protocol, TypeVar

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


@contextlib.contextmanager
def file_lock(path: Path) -> Generator[None, None, None]:
    """Hold an exclusive lock on path, across threads and processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def part_path(final: Path) -> Path:
    """Where aria2 writes a download until it is verified."""
    return Path(f"{final}.part")


def control_path(final: Path) -> Path:
    """aria2's control file, which records which pieces of the .part file are done."""
    return Path(f"{final}.part.aria2")


def final_path(path: Path) -> Path:
    """The final file path for a final, .part or control-file path."""
    text = str(path)
    for suffix in (".part.aria2", ".part"):
        if text.endswith(suffix):
            return Path(text[: -len(suffix)])
    return path


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
        return part_path(self.final)

    @property
    def control(self) -> Path:
        return control_path(self.final)

    @property
    def checksum_failed(self) -> bool:
        return self.state == FAILED and self.error_code == CHECKSUM_MISMATCH


class Record(Protocol):
    """What a stored record must carry: an alphanumeric id, a state and a creation time."""

    job_id: str
    state: str
    created_at: float


R = TypeVar("R", bound=Record)


class RecordStore(Generic[R]):
    """One JSON file per record in ``directory``; subclasses name the record type and its active states.

    Records outlive releases: a field added to a record type after a release
    must have a default, or records written before it become unreadable and
    an active job among them is lost to ``all()``.
    """

    record_type: type[R]
    active: tuple[str, ...]

    def __init__(self, directory: Path):
        self.directory = directory
        self._fields = {f.name for f in fields(self.record_type)}  # type: ignore[arg-type]

    def _file(self, job_id: str) -> Path:
        return self.directory / f"{job_id}.json"

    def locked(self):
        """Serialise starting jobs across threads and MCP server processes."""
        return file_lock(self.directory / ".lock")

    def create(self, job: R) -> None:
        """Write a new record; the only way a record comes into existence."""
        with file_lock(self._save_lock):
            self._write(job)

    def save(self, job: R) -> R:
        """Update an existing, unfinished record; returns the stored record.

        Two writers (the hook and the server; the upload worker and the
        server) both load, change and save records. A finished record is never
        rewritten, so a copy loaded before the outcome was recorded cannot undo
        it; a deleted one is not recreated by a late writer.
        """
        with file_lock(self._save_lock):
            current = self.load(job.job_id)
            if current is None:
                return job
            if current.state not in self.active:
                return current
            self._write(job)
        return job

    def update(self, job_id: str, change: Callable[[R], None]) -> R | None:
        """Apply ``change`` to the stored record under the lock, so two writers never clobber each other.

        Returns the record as stored afterwards; ``None`` when there is no such record. A finished
        record is returned unchanged.
        """
        with file_lock(self._save_lock):
            current = self.load(job_id)
            if current is None:
                return None
            if current.state not in self.active:
                return current
            change(current)
            self._write(current)
            return current

    @property
    def _save_lock(self) -> Path:
        return self.directory / ".save.lock"

    def _write(self, job: R) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
        with os.fdopen(fd, "w") as handle:
            json.dump(asdict(job), handle, indent=2)  # type: ignore[call-overload]
        Path(tmp).replace(self._file(job.job_id))

    def load(self, job_id: str) -> R | None:
        if not job_id.isalnum():
            return None
        try:
            data = json.loads(self._file(job_id).read_text())
        except (OSError, ValueError):
            return None
        try:
            return self.record_type(**{key: value for key, value in data.items() if key in self._fields})
        except TypeError:  # a required field this version added: unreadable, like a corrupt file
            return None

    def all(self) -> list[R]:
        """Every record, oldest first."""
        if not self.directory.is_dir():
            return []
        jobs = [self.load(path.stem) for path in self.directory.glob("*.json")]
        return sorted((job for job in jobs if job is not None), key=lambda job: job.created_at)

    def delete(self, job_id: str) -> None:
        # Under the save lock, so a save that has already loaded the record can't recreate it.
        with file_lock(self._save_lock), contextlib.suppress(FileNotFoundError):
            self._file(job_id).unlink()


class JobStore(RecordStore[Job]):
    record_type = Job
    active = ACTIVE

    def __init__(self, cache_dir: Path):
        super().__init__(cache_dir / "jobs")

    def end(self, job: Job, state: str, message: str, error_code: int | None = None) -> Job:
        """Record how a job ended and save it; returns the stored record."""
        job.state = state
        job.message = message
        job.error_code = error_code
        job.finished_at = time.time()
        return self.save(job)

    def for_path(self, path: Path) -> list[Job]:
        """Records for one final file path, oldest first."""
        return [job for job in self.all() if job.path == str(path)]
