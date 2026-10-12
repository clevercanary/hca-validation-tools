"""Checking whether files already on disk are current copies of the tracker's.

``Verifier.start`` answers that for a folder: an atlas folder's two
``tracker-source/`` folders, or any other folder's own ``.h5ad`` files (a
browser download, a copy from another machine). It matches each to the
tracker's download names and hashes the matches in a detached worker against
the SHA-256 the tracker stores with each file.

Like the upload worker, the hashing worker never sees the tracker token: every
tracker call happens in ``start``.
"""

import re
import secrets
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .api import TrackerClient, probe
from .catalog import atlas_files
from .checks import human_duration, human_size
from .config import Config
from .daemon import process_matches
from .errors import CheckError, JobError
from .selection import INTEGRATED, SOURCE, atlas_version, select_atlas
from .store import DONE, FAILED, INTERRUPTED, VERIFY_DIR, RecordStore
from .uploads import INTEGRATED_OBJECTS, SOURCE_DATASETS
from .workers import SPAWN_GRACE_SECONDS, reap_workers, spawn_worker

QUEUED = "queued"
HASHING = "hashing"
ACTIVE = (QUEUED, HASHING)

TRACKER_SOURCE = "tracker-source"
FOLDER_KINDS = {INTEGRATED_OBJECTS: INTEGRATED, SOURCE_DATASETS: SOURCE}
# Tracker requests (presign, ranged GET) run this many at a time; each is one round trip.
TRACKER_THREADS = 8

# A local file's status. The first group is decided from names and sizes, the
# second by hashing; PENDING is a file still waiting for the worker.
AMBIGUOUS = "ambiguous"  # its name is the download name of more than one tracker file
STALE = "stale"  # another revision or wip of a file the tracker lists; current_name is the one it lists
UNKNOWN = "unknown"  # not a file the tracker lists
SIZE_MISMATCH = "size_mismatch"  # the tracker's name, a different size
NO_CHECKSUM = "no_checksum"  # the tracker stores no SHA-256 for it, so it cannot be verified
PENDING = "pending"
VERIFIED = "verified"
MISMATCH = "mismatch"
CHANGED = "changed"  # its size or modification time changed after start, so its hash proves nothing
UNREADABLE = "unreadable"

# The tracker's download names end in -r<revision>-wip-<n> (-r<revision> alone on the test double); the part
# before is the file's stem.
_VERSIONED = re.compile(r"^(?P<stem>.+)-r\d+(?:-wip-\d+)?\.h5ad$")


def file_stem(name: str) -> str:
    """The part of a download name shared by every revision and wip of one file."""
    match = _VERSIONED.match(name)
    return match.group("stem") if match else name.removesuffix(".h5ad")


@dataclass
class VerifyJob:
    """One verification of an atlas folder against the tracker, from start to its outcome.

    ``files`` holds every local ``.h5ad`` with its status; the worker fills in
    the hashed ones. A field added after a release needs a default, so records
    written before it still load (see ``RecordStore.load``).
    """

    job_id: str
    network: str
    atlas: str
    version: str
    root: str
    files: list[dict]
    missing: list[dict]
    log_path: str
    # Download names the tracker gives to more than one file: {"name", "kinds"}.
    duplicate_names: list[dict] = field(default_factory=list)
    # "atlas" (its tracker-source/ folders, missing files listed) or "folder" (its own files, no missing list).
    layout: str = "atlas"
    state: str = QUEUED
    message: str | None = None
    pid: int | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None

    @property
    def to_hash(self) -> list[dict]:
        return [entry for entry in self.files if "sha256_expected" in entry]

    @property
    def hashed(self) -> list[dict]:
        return [entry for entry in self.to_hash if entry["status"] != PENDING]

    @property
    def worker_marker(self) -> str:
        """What the worker's command line contains, so a reused pid is not mistaken for it."""
        return f"hca_tracker_client.verify_worker {self.job_id}"


class VerifyStore(RecordStore[VerifyJob]):
    record_type = VerifyJob
    active = ACTIVE

    def __init__(self, cache_dir: Path):
        super().__init__(cache_dir / VERIFY_DIR)

    def end(self, job_id: str, state: str, message: str) -> VerifyJob | None:
        """Record how a job ended; a job already ended keeps its first outcome."""

        def change(job: VerifyJob) -> None:
            job.state = state
            job.message = message
            job.finished_at = time.time()

        return self.update(job_id, change)


def folders_to_scan(root: Path) -> tuple[str, dict[str | None, Path]]:
    """The layout and the folders to read, by the kind of file each should hold.

    An atlas folder is read through its ``tracker-source`` folders; any other
    folder (a download folder, say) is read itself, its files of either kind.
    """
    if not root.is_dir():
        raise CheckError(f"No folder at {root}")
    folders: dict[str | None, Path] = {
        kind: root / folder / TRACKER_SOURCE
        for folder, kind in FOLDER_KINDS.items()
        if (root / folder / TRACKER_SOURCE).is_dir()
    }
    return ("atlas", folders) if folders else ("folder", {None: root})


def local_files(folders: dict[str | None, Path]) -> list[dict]:
    """Every ``.h5ad`` directly in each folder, with its size and modification time; partial downloads skipped."""
    found = []
    for kind, folder in folders.items():
        for path in sorted(folder.iterdir()):
            if path.suffix != ".h5ad" or path.name.startswith(".") or not path.is_file():
                continue
            stat = path.stat()
            found.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "folder_kind": kind,
                    "size_bytes": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
            )
    return found


def tracker_names(tracker: TrackerClient, atlas_id: str) -> dict[str, list[dict]]:
    """The listed, unarchived files by download name (what a ``start_download`` would save each as).

    A name with more than one file is a duplicate the tracker should not hold; it is reported, never guessed at.
    """
    entries = [entry for entry in atlas_files(tracker, atlas_id) if not entry.get("isArchived")]
    with ThreadPoolExecutor(TRACKER_THREADS) as pool:
        presigned = list(pool.map(lambda entry: tracker.presigned_url(atlas_id, entry["fileId"]), entries))
    names: dict[str, list[dict]] = {}
    for entry, link in zip(entries, presigned, strict=True):
        names.setdefault(link.filename, []).append({"entry": entry, "presigned": link})
    return names


def duplicates(listed: dict[str, list[dict]]) -> list[dict]:
    return [
        {"name": name, "kinds": sorted(item["entry"]["kind"] for item in items)}
        for name, items in sorted(listed.items())
        if len(items) > 1
    ]


def classify(local: list[dict], listed: dict[str, list[dict]]) -> list[dict]:
    """Set each local file's status from names alone; returns the listed files with no local copy.

    A file the tracker lists gets ``kind`` and ``file_id``, and ``misplaced`` when it was found in a
    folder of one kind; ``check_sizes`` then decides whether it is hashed.
    """
    stems = {file_stem(name): name for name in listed}
    present = set()
    for entry in local:
        matches = listed.get(entry["name"])
        if matches is None:
            current = stems.get(file_stem(entry["name"]))
            entry.update({"status": STALE, "current_name": current} if current else {"status": UNKNOWN})
            continue
        present.add(entry["name"])
        if len(matches) > 1:
            entry.update({"status": AMBIGUOUS, "matches": sorted(item["entry"]["kind"] for item in matches)})
            continue
        match = matches[0]
        kind = match["entry"]["kind"]
        entry.update({"kind": kind, "file_id": match["entry"]["fileId"]})
        if entry["folder_kind"] is not None:
            entry["misplaced"] = kind != entry["folder_kind"]
    missing = []
    for name, items in sorted(listed.items()):
        if name in present:
            continue
        for item in items:
            size = int(item["entry"].get("sizeBytes") or 0)
            missing.append({"name": name, "kind": item["entry"]["kind"], "size_bytes": size, "size": human_size(size)})
    return missing


def check_sizes(local: list[dict], listed: dict[str, list[dict]]) -> None:
    """Read the stored size and checksum of each listed local file; those that can be hashed become pending."""
    matched = [entry for entry in local if "file_id" in entry]
    with ThreadPoolExecutor(TRACKER_THREADS) as pool:
        probes = list(pool.map(lambda entry: probe(listed[entry["name"]][0]["presigned"]), matched))
    for entry, probed in zip(matched, probes, strict=True):
        listed_size = int(listed[entry["name"]][0]["entry"].get("sizeBytes") or 0)
        size = probed.size if probed.size is not None else listed_size
        entry["tracker_size_bytes"] = size
        if size != entry["size_bytes"]:
            entry["status"] = SIZE_MISMATCH
        elif not probed.sha256:
            entry["status"] = NO_CHECKSUM
        else:
            entry.update({"status": PENDING, "sha256_expected": probed.sha256})


class Verifier:
    """Verify a folder against the tracker: ``start`` it, follow it with ``status``."""

    def __init__(self, config: Config, tracker: TrackerClient | None = None):
        self.config = config
        self.cache_dir = config.cache_dir.resolve()
        self.store = VerifyStore(self.cache_dir)
        self._tracker = tracker

    @property
    def tracker(self) -> TrackerClient:
        if self._tracker is None:
            self._tracker = self.config.tracker_client()
        return self._tracker

    # -- start ---------------------------------------------------------------

    def start(
        self, network: str, atlas: str, path: str, generation: int | None = None, published: bool = False
    ) -> dict:
        """Classify the folder's files, then hash the matches in a detached worker; returns at once."""
        root = Path(path).expanduser().resolve()
        layout, folders = folders_to_scan(root)
        running = self._active_job_for(root)
        if running is not None:
            return {**self._describe(running), "message": f"Already verifying {root}"}

        record = select_atlas(self.tracker.list_atlases(), network, atlas, generation, published)
        listed = tracker_names(self.tracker, record["id"])
        files = local_files(folders)
        missing = classify(files, listed)
        if layout == "folder":  # a folder of downloads is not expected to hold the whole atlas
            missing = []
        check_sizes(files, listed)

        job_id = secrets.token_hex(8)
        job = VerifyJob(
            job_id=job_id,
            network=network,
            atlas=atlas,
            version=atlas_version(record),
            root=str(root),
            files=files,
            missing=missing,
            log_path=str(self.store.directory / f"{job_id}.log"),
            layout=layout,
            duplicate_names=duplicates(listed),
        )
        if not job.to_hash:  # nothing to hash: the answer is complete now
            job.state, job.finished_at = DONE, time.time()
            job.message = "No file matched a tracker file of the same size and checksum to hash"
            self.store.create(job)
            return self._describe(job)

        with self.store.locked():
            running = self._active_job_for(root)
            if running is not None:  # a second caller got here first
                return {**self._describe(running), "message": f"Already verifying {root}"}
            self.store.create(job)
            try:
                pid = spawn_worker("hca_tracker_client.verify_worker", job_id, self.cache_dir, job.log_path)
            except Exception as error:  # OSError, or whatever a platform's posix_spawn refuses
                message = f"The verify worker could not be started: {type(error).__name__}: {error}"
                self.store.end(job_id, FAILED, message)
                raise CheckError(f"{message}; nothing was hashed") from None
            job = self.store.update(job_id, lambda current: setattr(current, "pid", pid)) or job
        return self._describe(job)

    def _active_job_for(self, root: Path) -> VerifyJob | None:
        for job in self.store.all():
            if job.root == str(root) and self._refresh(job).state in ACTIVE:
                return job
        return None

    # -- status --------------------------------------------------------------

    def _refresh(self, job: VerifyJob) -> VerifyJob:
        """Mark a job whose worker has gone away without recording an outcome."""
        reap_workers()
        if job.state not in ACTIVE:
            return job
        if job.state == QUEUED and not job.pid and time.time() - job.created_at > SPAWN_GRACE_SECONDS:
            message = "The verify worker was never started; run verify_local again"
            return self.store.end(job.job_id, INTERRUPTED, message) or job
        if job.pid and not process_matches(job.pid, job.worker_marker):
            message = (
                f"The verify worker (pid {job.pid}) stopped without finishing: {len(job.hashed)} of "
                f"{len(job.to_hash)} files hashed. Run verify_local again"
            )
            return self.store.end(job.job_id, INTERRUPTED, message) or job
        return job

    def _summary(self, job: VerifyJob) -> dict:
        """The job without its per-file rows: what a listing of every job shows."""
        total = sum(entry["size_bytes"] for entry in job.to_hash)
        done = sum(entry["size_bytes"] for entry in job.hashed)
        result: dict = {
            "job_id": job.job_id,
            "state": job.state,
            "network": job.network,
            "atlas": job.atlas,
            "version": job.version,
            "root": job.root,
            "layout": job.layout,
            "counts": dict(Counter(entry["status"] for entry in job.files)),
            "files_to_hash": len(job.to_hash),
            "files_hashed": len(job.hashed),
            "bytes_total": total,
            "bytes_done": done,
            "size_total": human_size(total),
            "size_done": human_size(done),
        }
        if job.layout == "atlas":
            result["counts"]["missing"] = len(job.missing)
        if job.duplicate_names:
            result["duplicate_names"] = job.duplicate_names
        if job.state == HASHING and job.started_at:
            result["elapsed"] = human_duration(time.time() - job.started_at)
        if job.message:
            result["message"] = job.message
        return result

    def _describe(self, job: VerifyJob) -> dict:
        result = {**self._summary(job), "files": [_row(entry) for entry in job.files]}
        if job.layout == "atlas":
            result["missing"] = job.missing
        return result

    def status(self, job_id: str | None = None) -> dict:
        """One job's state and per-file results, or a summary of every job when no id is given."""
        if job_id:
            job = self.store.load(job_id)
            if job is None:
                raise JobError(f"No verify job {job_id!r}")
            return self._describe(self._refresh(job))
        return {"jobs": [self._summary(self._refresh(job)) for job in reversed(self.store.all())]}


def _row(entry: dict) -> dict:
    """A file's entry as reported: what was found and its status, without the worker's internals."""
    row = {
        "name": entry["name"],
        "path": entry["path"],
        "status": entry["status"],
        "size_bytes": entry["size_bytes"],
        "size": human_size(entry["size_bytes"]),
        "folder_kind": entry["folder_kind"],
    }
    for key in ("kind", "matches", "misplaced", "current_name", "tracker_size_bytes", "sha256", "error"):
        if key in entry:
            row[key] = entry[key]
    return row
