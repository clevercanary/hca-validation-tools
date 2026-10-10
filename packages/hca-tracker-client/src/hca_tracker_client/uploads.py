"""Uploading curated h5ad files to the tracker's bucket with hca-smart-sync's engine.

The tracker ingests whatever lands under ``s3://<bucket>/<bionetwork>/<atlas-folder>/<file-type>/``;
atlas teams put files there with the ``hca-smart-sync`` CLI. This module drives that CLI's
engine (``hca_smart_sync.sync_engine.SmartSync``) and replaces only its terminal front end,
so a file uploaded here lands exactly where the CLI would put it: the bucket names, the
atlas-to-bionetwork map and the prefix layout are the CLI's own.

The engine is an optional dependency (``hca-tracker-client[upload]``); everything that needs
it imports it on first use, so the base package stays dependency-free.

Uploads are an AWS-credential action against a shared bucket, so:

- ``environment`` defaults to ``dev``; ``prod`` is explicit.
- The bucket must be the one the configured tracker ingests from, or the upload is refused.
- The AWS profile comes from hca-smart-sync's own settings, never from a tool parameter.
- ``start()`` returns the plan it is executing, and ``force`` is the only way to re-upload
  a file the bucket already holds.
"""

import contextlib
import io
import os
import pkgutil
import re
import secrets
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlparse

from .api import TrackerClient
from .checks import human_duration, human_size, version_output
from .config import DEFAULT_UPLOAD_ENGINE, ENVIRONMENTS, Config
from .daemon import process_matches
from .errors import CheckError, ConfigError, JobError, redact
from .selection import atlas_label, atlas_version, select_atlas
from .store import RecordStore

DEV, PROD = ENVIRONMENTS
# The buckets the hca-smart-sync CLI hardcodes per --environment (``sync`` in
# hca_smart_sync.cli). The engine takes any ``s3://`` URL, so these are what
# keep an upload landing where the CLI's would; test_uploads.py pins them.
BUCKETS = {DEV: "hca-atlas-tracker-data-dev", PROD: "hca-atlas-tracker-data"}
# Which bucket each tracker ingests from, by the tracker's host.
TRACKER_HOSTS = {
    "tracker.data.humancellatlas.org": PROD,
    "test-tracker.data.humancellatlas.dev.clevercanary.com": DEV,
}
SOURCE_DATASETS = "source-datasets"
INTEGRATED_OBJECTS = "integrated-objects"
FILE_TYPES = (SOURCE_DATASETS, INTEGRATED_OBJECTS)
# The CLI's ``hca-smart-sync config`` writes the profile here (hca_smart_sync.config_manager).
SMART_SYNC_CONFIG = "~/.hca-smart-sync/config.yaml"
INSTALL_HINT = "install the upload extra (hca-tracker-client[upload]) to upload files"
TRANSFER_TOOLS = ("s5cmd", "aws")

QUEUED = "queued"
UPLOADING = "uploading"
DONE = "done"
FAILED = "failed"
INTERRUPTED = "interrupted"
ACTIVE = (QUEUED, UPLOADING)
# How long a record may sit without a pid before it counts as a spawn that never completed.
SPAWN_GRACE_SECONDS = 60

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# One s5cmd progress frame: "42.81%  ━━━───  8.98 MB / 20.97 MB (6.74 MB/s) 1s left (0/1)".
_S5CMD_FRAME = re.compile(r"\d{1,3}\.\d{2}%\s+\S+\s+.*?\(\d+/\d+\)")


def smart_sync() -> Any:
    """The ``hca_smart_sync`` package, imported on first use; a clean error when the extra is missing."""
    try:
        import hca_smart_sync
        import hca_smart_sync.cli
        import hca_smart_sync.config_manager
    except ImportError:
        raise ConfigError(f"hca-smart-sync is not installed; {INSTALL_HINT}") from None
    return hca_smart_sync


def resolve_profile(environ: dict[str, str] | None = None) -> tuple[str, str]:
    """The AWS profile uploads sign with, and where it came from.

    The profile the hca-smart-sync CLI saved with ``hca-smart-sync config``,
    so both front ends sign the same way; otherwise ``AWS_PROFILE``, which
    boto3 and the transfer tools honour on their own. ``HCA_AWS_PROFILE`` is
    this package's own override, which the CLI does not read.
    """
    env = os.environ if environ is None else environ
    if env.get("HCA_AWS_PROFILE"):
        return env["HCA_AWS_PROFILE"], "HCA_AWS_PROFILE"
    manager = smart_sync().config_manager
    path = manager.get_config_path()
    try:
        saved = manager.load_config(path) or {}
    except Exception as error:  # yaml.YAMLError, in the engine's own words
        raise ConfigError(f"Could not read hca-smart-sync's settings: {error}") from None
    if saved.get("profile"):
        return str(saved["profile"]), str(path)
    if env.get("AWS_PROFILE"):
        return env["AWS_PROFILE"], "AWS_PROFILE"
    raise ConfigError(
        "No AWS profile for uploads: run `hca-smart-sync config` to save one in "
        f"{SMART_SYNC_CONFIG}, or set HCA_AWS_PROFILE"
    )


def tracker_environment(config: Config) -> tuple[str, str]:
    """The configured tracker's host and which environment (``dev`` or ``prod``) it belongs to."""
    url, _ = config.require_tracker()
    host = urlparse(url).hostname or ""
    known = TRACKER_HOSTS.get(host)
    if config.tracker_environment and known and config.tracker_environment != known:
        raise CheckError(
            f"HCA_TRACKER_ENVIRONMENT={config.tracker_environment!r} contradicts the configured tracker {host!r}, "
            f"which is the {known} tracker; unset it (it is for hosts this package does not know). Nothing was uploaded"
        )
    environment = known or config.tracker_environment
    if environment is None:
        names = ", ".join(f"{name} ({env})" for name, env in TRACKER_HOSTS.items())
        raise CheckError(
            f"The configured tracker host {host!r} is not one this package knows ({names}), so the bucket "
            "it ingests from is unknown; set HCA_TRACKER_ENVIRONMENT to dev or prod. Nothing was uploaded"
        )
    return host, environment


def bucket_for(environment: str) -> str:
    if environment not in BUCKETS:
        raise CheckError(f"environment must be {DEV!r} or {PROD!r}, got {environment!r}")
    return BUCKETS[environment]


def smart_sync_atlas(atlas: str, generation: int) -> str:
    """The name hca-smart-sync's atlas map knows a generation by, e.g. ``gut-v1``."""
    return f"{atlas}-v{generation}"


def atlas_folder(atlas: str, generation: int, revision: int) -> str:
    """The folder the tracker reads an atlas version from: ``gut-v1`` for v1.0, ``gut-v1-1`` for v1.1.

    The tracker's ``parseS3AtlasName`` (hca-atlas-tracker ``app/utils/files.ts``)
    reads ``<slug>-v<generation>`` as revision 0 and ``<slug>-v<generation>-<revision>``
    otherwise. hca-smart-sync's map names only the revision-0 form, so its CLI
    can upload to a generation's first revision only.
    """
    return f"{atlas}-v{generation}" if revision == 0 else f"{atlas}-v{generation}-{revision}"


def s3_prefix(bionetwork: str, folder: str, file_type: str) -> str:
    """The key prefix under the bucket, laid out as the CLI's ``_build_s3_path`` does."""
    return f"{bionetwork}/{folder}/{file_type}/"


@dataclass(frozen=True)
class Target:
    """Where an upload goes: an atlas version's folder in one environment's bucket.

    The bionetwork in the prefix is the tracker's ``network``; ``resolve_target``
    has checked that hca-smart-sync's map agrees before building one of these.
    """

    environment: str
    network: str
    atlas: str
    version: str
    atlas_folder: str
    file_type: str

    @property
    def bucket(self) -> str:
        return BUCKETS[self.environment]

    @property
    def prefix(self) -> str:
        return s3_prefix(self.network, self.atlas_folder, self.file_type)

    @property
    def url(self) -> str:
        return f"s3://{self.bucket}/{self.prefix}"

    def describe(self) -> dict:
        return {**asdict(self), "bucket": self.bucket, "prefix": self.prefix, "target": self.url}


def resolve_target(
    atlases: list[dict], network: str, atlas: str, generation: int | None, file_type: str, environment: str
) -> Target:
    """Build the target from the tracker's atlas record and hca-smart-sync's atlas map.

    The map (``ATLAS_BIONETWORKS`` in ``hca_smart_sync.cli``) decides the
    bionetwork, as it does for the CLI; the tracker's record cross-checks it, so
    a stale map is an error here rather than a file under the wrong prefix. The
    folder names the selected revision, and a published one is refused: the
    tracker rejects uploads to it, after the transfer, in its own log.
    """
    bucket_for(environment)
    if file_type not in FILE_TYPES:
        raise CheckError(f"file_type must be one of {', '.join(FILE_TYPES)}, got {file_type!r}")
    version = select_atlas(atlases, network, atlas, generation)
    label = atlas_label(network, atlas, atlas_version(version))
    name = smart_sync_atlas(atlas, version["generation"])
    mapped = smart_sync().cli.ATLAS_BIONETWORKS.get(name)
    if mapped is None:
        raise CheckError(
            f"hca-smart-sync does not know the atlas {name!r} ({label}); add it to ATLAS_BIONETWORKS in "
            "hca-ingest-tools (smart-sync/src/hca_smart_sync/cli.py) and release hca-smart-sync before uploading "
            "for it. Nothing was uploaded"
        )
    if mapped != network:
        raise CheckError(
            f"hca-smart-sync files {name!r} under the bionetwork {mapped!r}, but the tracker lists the atlas "
            f"under {network!r}; nothing was uploaded. One of them is wrong: fix ATLAS_BIONETWORKS in "
            "hca-ingest-tools or the tracker's record before uploading"
        )
    if version.get("publishedAt"):
        raise CheckError(
            f"Atlas version {label} is published, and the tracker refuses uploads to a published version. "
            "Create its next revision in the tracker (a draft) and upload again; nothing was uploaded"
        )
    return Target(
        environment=environment,
        network=network,
        atlas=atlas,
        version=atlas_version(version),
        atlas_folder=atlas_folder(atlas, version["generation"], version["revision"]),
        file_type=file_type,
    )


def transfer_tool() -> tuple[str, str] | None:
    """The transfer tool the engine will pick and its path: ``s5cmd`` if present, else ``aws``, else ``None``."""
    for tool in TRANSFER_TOOLS:
        path = shutil.which(tool)
        if path:
            return tool, path
    return None


def transfer_tool_note(tool: str | None) -> str | None:
    """What to say about the transfer tool found, or ``None`` when it is the preferred one."""
    if tool is None:
        return "Neither s5cmd nor aws is on PATH, so nothing can be transferred; install one"
    if tool == "aws":
        return "s5cmd is not on PATH; the slower AWS CLI will transfer the files"
    return None


def make_engine(
    profile: str,
    log: TextIO | None = None,
    on_file_start: Callable[[str], None] | None = None,
    on_file_done: Callable[[str, int], None] | None = None,
) -> Any:
    """A ``SmartSync`` configured as the CLI configures it, printing to ``log`` (or nowhere).

    The callbacks hear about each data file as the engine starts and finishes
    uploading it; the manifest it uploads last is not reported. This is the
    default engine factory; tests point ``HCA_TRACKER_UPLOAD_ENGINE`` at
    ``hca_tracker_client.testing:FakeSmartSync``, which has the same signature.
    """
    package = smart_sync()
    import boto3
    from rich.console import Console

    if profile not in boto3.Session().available_profiles:
        raise ConfigError(
            f"The AWS profile {profile!r} is not in ~/.aws/config or ~/.aws/credentials; "
            "configure it, or save a different one with `hca-smart-sync config`"
        )
    config = package.Config()  # as the CLI's _load_and_configure does
    config.aws.profile = profile
    console = Console(file=log, force_terminal=False, width=120) if log else Console(quiet=True)

    class ReportingSync(package.SmartSync):
        """The engine, with its per-file upload forwarded to the callbacks (the manifest goes up without a checksum)."""

        def _upload_file(self, local_path, s3_url, include_checksum=True, file_size=None):
            name = Path(local_path).name
            if include_checksum and on_file_start:
                on_file_start(name)
            ok = super()._upload_file(local_path, s3_url, include_checksum, file_size)
            if ok and include_checksum and on_file_done:
                on_file_done(name, file_size if file_size is not None else Path(local_path).stat().st_size)
            return ok

    return ReportingSync(config, console=console)


def load_engine(spec: str) -> Callable[..., Any]:
    """Resolve the ``module:attribute`` of an engine factory."""
    return pkgutil.resolve_name(spec)


def _file_entry(info: dict) -> dict:
    """One planned file, in this package's names (the engine's are filename/checksum/local_path)."""
    return {
        "name": info["filename"],
        "size_bytes": int(info["size"]),
        "sha256": info["checksum"],
        "reason": info["reason"],
    }


def _with_size(entry: dict) -> dict:
    return {**entry, "size": human_size(entry["size_bytes"])}


def run_plan(engine: Any, directory: Path, url: str, profile: str, force: bool) -> dict:
    """``sync(plan_only=True)`` against ``url``, with the engine's result shapes folded into one."""
    try:
        result = engine.sync(directory, url, force=force, plan_only=True)
    except RuntimeError as error:  # the engine's "Failed to check S3 status for <file>: <code> - <message>"
        raise CheckError(redact(f"hca-smart-sync could not compare {directory} with {url}: {error}")) from None
    if result.get("error") == "access_denied":
        raise CheckError(
            f"The AWS profile {profile!r} cannot list {url} (hca-smart-sync's access check failed: "
            "access denied, no such bucket, or no valid credentials for the profile). Nothing was uploaded"
        )
    planned = [_file_entry(info) for info in result.get("files_to_upload") or []]
    names = {entry["name"] for entry in planned}
    present = sorted(path.name for path in directory.glob("*.h5ad") if path.is_file())
    plan: dict = {"files": planned, "up_to_date": [name for name in present if name not in names]}
    if result.get("no_files_found"):
        plan["no_files_found"] = True
    return plan


def _local_directory(local_path: str) -> str:
    if not local_path.strip():
        raise CheckError("local_path must name the folder to upload from")
    directory = Path(local_path).expanduser().resolve()
    if directory.is_file():
        raise CheckError(
            f"local_path must be a folder, not a file: hca-smart-sync uploads every .h5ad directly in a "
            f"folder. Put {directory.name} in a folder of its own and pass that"
        )
    if not directory.is_dir():
        raise CheckError(f"local_path {str(directory)!r} is not a folder")
    return str(directory)


@dataclass
class UploadJob:
    """One upload run: a folder to a target, from start to its outcome.

    A field added after a release needs a default, so records written before
    it still load (see ``RecordStore.load``).
    """

    job_id: str
    network: str
    atlas: str
    version: str
    atlas_folder: str
    file_type: str
    environment: str
    target: str
    local_path: str
    profile: str
    transfer_tool: str
    force: bool
    files: list[dict]
    log_path: str
    engine: str = DEFAULT_UPLOAD_ENGINE
    profile_source: str = ""
    up_to_date: list[str] = field(default_factory=list)
    state: str = QUEUED
    message: str | None = None
    files_done: list[str] = field(default_factory=list)
    bytes_done: int = 0
    current_file: str | None = None
    manifest_path: str | None = None
    pid: int | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None

    @property
    def total_bytes(self) -> int:
        return sum(entry["size_bytes"] for entry in self.files)

    @property
    def target_record(self) -> Target:
        return Target(self.environment, self.network, self.atlas, self.version, self.atlas_folder, self.file_type)

    @property
    def worker_marker(self) -> str:
        """What the worker's command line contains, so a reused pid is not mistaken for it."""
        return f"hca_tracker_client.upload_worker {self.job_id}"


class UploadStore(RecordStore[UploadJob]):
    record_type = UploadJob
    active = ACTIVE

    def __init__(self, cache_dir: Path):
        super().__init__(cache_dir / "uploads")

    def end(self, job_id: str, state: str, message: str, manifest_path: str | None = None) -> UploadJob | None:
        """Record how a job ended; a job already ended keeps its first outcome."""

        def change(job: UploadJob) -> None:
            job.state = state
            job.message = message
            job.current_file = None
            job.finished_at = time.time()
            if manifest_path:
                job.manifest_path = manifest_path

        return self.update(job_id, change)


def worker_alive(job: UploadJob) -> bool:
    """Whether the job's worker process is still running.

    A worker this process spawned is reaped here once it has exited; otherwise
    it would stay a zombie that looks alive. A pid that now belongs to some
    other program (after a reboot, say) does not count as the worker.
    """
    if not job.pid:
        return False
    with contextlib.suppress(ChildProcessError):
        if os.waitpid(job.pid, os.WNOHANG) != (0, 0):
            return False
    return process_matches(job.pid, job.worker_marker)


def last_progress_line(log_path: str, tail: int = 4096) -> str | None:
    """The transfer tool's latest progress frame, as it drew it (minus terminal escapes).

    The AWS CLI redraws one line with carriage returns, so the end of the log
    is the current state. s5cmd, writing to a file rather than a terminal,
    appends each frame to the same line with no separator at all, so the last
    frame is picked out by its shape.
    """
    try:
        with Path(log_path).open("rb") as handle:
            handle.seek(0, io.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - tail))
            text = handle.read().decode("utf-8", "replace")
    except OSError:
        return None
    lines = [part.strip() for part in re.split(r"[\r\n]", _ANSI.sub("\n", text))]
    line = next((line for line in reversed(lines) if line), None)
    if line is None:
        return None
    frames = _S5CMD_FRAME.findall(line)
    return frames[-1] if frames else line[-200:]


@dataclass(frozen=True)
class Plan:
    """Everything ``start`` needs from the checks, before it is flattened for the caller."""

    target: Target
    directory: str
    profile: str
    profile_source: str
    tool: tuple[str, str] | None
    force: bool
    files: list[dict]
    up_to_date: list[str]
    no_files_found: bool

    def describe(self) -> dict:
        tool = self.tool[0] if self.tool else None
        note = transfer_tool_note(tool)
        result = {
            **self.target.describe(),
            "profile": self.profile,
            "profile_source": self.profile_source,
            "transfer_tool": tool,
            "force": self.force,
            "local_path": self.directory,
            "files": [_with_size(entry) for entry in self.files],
            "total_bytes": sum(entry["size_bytes"] for entry in self.files),
            "up_to_date": self.up_to_date,
        }
        result["total_size"] = human_size(result["total_bytes"])
        if self.no_files_found:
            result["no_files_found"] = True
        result["warnings"] = [note] if note else []
        return result


class Uploads:
    """Plan and run uploads, and report on them. One instance per call is fine."""

    def __init__(self, config: Config, tracker: TrackerClient | None = None):
        self.config = config
        self._tracker = tracker
        self.store = UploadStore(config.cache_dir)

    @property
    def tracker(self) -> TrackerClient:
        if self._tracker is None:
            self._tracker = self.config.tracker_client()
        return self._tracker

    def _check_environment(self, environment: str) -> None:
        bucket = bucket_for(environment)
        host, configured = tracker_environment(self.config)
        if configured != environment:
            raise CheckError(
                f"The configured tracker ({host}) is the {configured} tracker, which ingests from "
                f"{BUCKETS[configured]}, but environment={environment!r} names {bucket}; a file uploaded there "
                f"would never appear in this tracker's lists. Pass environment={configured!r}, or point "
                f"HCA_TRACKER_URL at the {environment} tracker. Nothing was uploaded"
            )

    def _plan(
        self,
        network: str,
        atlas: str,
        file_type: str,
        local_path: str,
        generation: int | None,
        environment: str,
        force: bool,
    ) -> Plan:
        self._check_environment(environment)
        directory = _local_directory(local_path)
        target = resolve_target(self.tracker.list_atlases(), network, atlas, generation, file_type, environment)
        profile, profile_source = resolve_profile()
        tool = transfer_tool()
        engine = load_engine(self.config.upload_engine)(profile, None, None, None)
        found = run_plan(engine, Path(directory), target.url, profile, force)
        return Plan(
            target=target,
            directory=directory,
            profile=profile,
            profile_source=profile_source,
            tool=tool,
            force=force,
            files=found["files"],
            up_to_date=found["up_to_date"],
            no_files_found=bool(found.get("no_files_found")),
        )

    def plan(
        self,
        network: str,
        atlas: str,
        file_type: str,
        local_path: str,
        generation: int | None = None,
        environment: str = DEV,
        force: bool = False,
    ) -> dict:
        """What ``start`` would upload, with no side effects.

        Every check ``start`` makes runs here too: the tracker and the bucket
        agree, the atlas resolves and hca-smart-sync knows it, a profile is
        configured, and it can list the target.
        """
        return self._plan(network, atlas, file_type, local_path, generation, environment, force).describe()

    def _active_job_for(self, directory: str) -> UploadJob | None:
        """The job still running from ``directory``, after retiring any whose worker is gone."""
        for job in self.store.all():
            if job.state in ACTIVE and job.local_path == directory and self._refresh(job).state in ACTIVE:
                return job
        return None

    def start(
        self,
        network: str,
        atlas: str,
        file_type: str,
        local_path: str,
        generation: int | None = None,
        environment: str = DEV,
        force: bool = False,
    ) -> dict:
        """Plan, then run the upload in a detached worker; returns the job and its plan at once."""
        if transfer_tool() is None:  # before hashing a folder for nothing
            raise CheckError(transfer_tool_note(None) or "")
        if self._active_job_for(_local_directory(local_path)) is not None:
            return self._already_uploading(_local_directory(local_path))
        plan = self._plan(network, atlas, file_type, local_path, generation, environment, force)
        described = plan.describe()
        if not plan.files:
            if plan.no_files_found:
                message = f"No .h5ad files directly in {plan.directory}; nothing to upload"
            else:
                message = (
                    f"Every .h5ad in {plan.directory} is already in {plan.target.url} with the same SHA-256; "
                    "nothing to upload. Pass force=true to upload them again"
                )
            return {**described, "job_id": None, "state": None, "message": message}
        assert plan.tool is not None

        with self.store.locked():
            if self._active_job_for(plan.directory) is not None:  # a second caller got here first
                return self._already_uploading(plan.directory)
            job_id = secrets.token_hex(8)
            job = UploadJob(
                job_id=job_id,
                network=plan.target.network,
                atlas=plan.target.atlas,
                version=plan.target.version,
                atlas_folder=plan.target.atlas_folder,
                file_type=plan.target.file_type,
                environment=plan.target.environment,
                target=plan.target.url,
                local_path=plan.directory,
                profile=plan.profile,
                profile_source=plan.profile_source,
                transfer_tool=plan.tool[0],
                force=force,
                files=plan.files,
                up_to_date=plan.up_to_date,
                log_path=str(self.store.directory / f"{job_id}.log"),
                engine=self.config.upload_engine,
            )
            self.store.create(job)
            try:
                pid = self._spawn(job)
            except Exception as error:  # OSError, or NotImplementedError from a libc without setsid support
                message = redact(f"The upload worker could not be started: {type(error).__name__}: {error}")
                self.store.end(job_id, FAILED, message)
                raise CheckError(f"{message}; nothing was uploaded") from None
            job = self.store.update(job_id, lambda current: setattr(current, "pid", pid)) or job
        return {**self._describe(job), "warnings": described["warnings"]}

    def _already_uploading(self, directory: str) -> dict:
        job = self._active_job_for(directory)
        assert job is not None
        return {**self._describe(job), "message": f"Already uploading from {directory}"}

    def _spawn(self, job: UploadJob) -> int:
        """Start the worker in a session of its own, its output going to the job's log.

        ``os.posix_spawn`` rather than ``Popen``: nothing waits for the worker,
        and a ``Popen`` collected while its child runs warns about it.
        """
        argv = [sys.executable, "-m", "hca_tracker_client.upload_worker", job.job_id, str(self.config.cache_dir)]
        log = os.open(job.log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            actions = [
                (os.POSIX_SPAWN_OPEN, 0, os.devnull, os.O_RDONLY, 0),
                (os.POSIX_SPAWN_DUP2, log, 1),
                (os.POSIX_SPAWN_DUP2, log, 2),
            ]
            return os.posix_spawn(sys.executable, argv, dict(os.environ), file_actions=actions, setsid=True)
        finally:
            os.close(log)

    def _refresh(self, job: UploadJob) -> UploadJob:
        """Mark a job whose worker has gone away without recording an outcome.

        A record with no pid is one whose spawn did not complete; ``start``
        records that itself, so one still queued a minute later is a failed
        spawn that nothing recorded.
        """
        if job.state not in ACTIVE:
            return job
        never_spawned = not job.pid and time.time() - job.created_at > SPAWN_GRACE_SECONDS
        if never_spawned:
            return (
                self.store.end(job.job_id, INTERRUPTED, "The upload worker was never started; run start_upload again")
                or job
            )
        if job.pid and not worker_alive(job):
            ended = self.store.end(
                job.job_id,
                INTERRUPTED,
                f"The upload worker (pid {job.pid}) stopped without finishing: {len(job.files_done)} of "
                f"{len(job.files)} files uploaded. Run start_upload again; hca-smart-sync skips the files already "
                "in the bucket",
            )
            return ended or job
        return job

    def _describe(self, job: UploadJob) -> dict:
        result: dict = {
            "job_id": job.job_id,
            "state": job.state,
            **job.target_record.describe(),
            "local_path": job.local_path,
            "profile": job.profile,
            "profile_source": job.profile_source,
            "transfer_tool": job.transfer_tool,
            "force": job.force,
            "files": [_with_size(entry) for entry in job.files],
            "files_total": len(job.files),
            "files_done": len(job.files_done),
            "uploaded": job.files_done,
            "up_to_date": job.up_to_date,
            "bytes_total": job.total_bytes,
            "bytes_done": job.bytes_done,
            "size_total": human_size(job.total_bytes),
            "size_done": human_size(job.bytes_done),
            "log_path": job.log_path,
        }
        if job.state == UPLOADING:
            result["current_file"] = job.current_file
            result["progress"] = last_progress_line(job.log_path)
            if job.started_at:
                result["elapsed"] = human_duration(time.time() - job.started_at)
        if job.manifest_path:
            result["manifest_path"] = job.manifest_path
        if job.message:
            result["message"] = job.message
        return result

    def status(self, job_id: str | None = None) -> dict:
        """One job's state and progress, or every job's when no id is given."""
        if job_id:
            job = self.store.load(job_id)
            if job is None:
                raise JobError(f"No upload job {job_id!r}")
            return self._describe(self._refresh(job))
        jobs = [self._describe(self._refresh(job)) for job in self.store.all()]
        return {"jobs": list(reversed(jobs))}


def upload_report(config: Config) -> dict:
    """What an upload needs, and whether each piece is in place: for ``check_environment``."""
    try:
        smart_sync_report: dict = {"ok": True, "version": smart_sync().__version__}
    except ConfigError as error:
        smart_sync_report = {"ok": False, "error": str(error)}

    tools: dict = {tool: {"ok": shutil.which(tool) is not None} for tool in TRANSFER_TOOLS}
    selected = transfer_tool()
    if selected:  # only the tool the engine would use is asked for its version (aws takes a third of a second)
        tool, path = selected
        tools[tool] |= {"path": path, "version": version_output(path, "version" if tool == "s5cmd" else "--version")}
    tools["selected"] = selected[0] if selected else None

    profile: str | None = None
    profile_report: dict = {}
    if smart_sync_report["ok"]:
        try:
            profile, source = resolve_profile()
            profile_report = {"ok": True, "name": profile, "source": source}
        except ConfigError as error:
            profile_report = {"ok": False, "error": str(error)}

    bucket: dict = {"ok": False}
    try:
        _, environment = tracker_environment(config)
        bucket |= {"environment": environment, "name": BUCKETS[environment]}
    except (CheckError, ConfigError) as error:
        bucket["error"] = str(error)
    if profile and "name" in bucket:
        try:
            # A plan over an empty folder runs the engine's access check and nothing else.
            with tempfile.TemporaryDirectory() as empty:
                engine = load_engine(config.upload_engine)(profile, None, None, None)
                run_plan(engine, Path(empty), f"s3://{bucket['name']}/", profile, False)
            bucket["ok"] = True
        except (CheckError, ConfigError) as error:
            bucket["error"] = str(error)

    note = transfer_tool_note(tools["selected"])
    return {
        "smart_sync": smart_sync_report,
        "transfer_tools": tools,
        "profile": profile_report,
        "bucket": bucket,
        "can_upload": bool(smart_sync_report["ok"] and selected and bucket["ok"]),
        "notes": [note] if note else [],
    }
