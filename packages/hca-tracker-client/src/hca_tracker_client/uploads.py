"""Uploading curated h5ad files to the tracker's bucket with hca-smart-sync's engine.

The tracker ingests whatever lands under ``s3://<bucket>/<bionetwork>/<atlas>/<file-type>/``;
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
import importlib
import io
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlparse

from .api import TrackerClient
from .checks import human_duration, human_size
from .config import DEFAULT_UPLOAD_ENGINE, Config
from .errors import CheckError, ConfigError, JobError
from .selection import atlas_label, atlas_version, select_atlas
from .store import RecordStore

DEV = "dev"
PROD = "prod"
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

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


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

    ``HCA_AWS_PROFILE`` is the explicit override; otherwise the profile the
    hca-smart-sync CLI saved with ``hca-smart-sync config``; otherwise
    ``AWS_PROFILE``, which boto3 and the transfer tools honour on their own.
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


def tracker_environment(config: Config) -> str:
    """Which environment (``dev`` or ``prod``) the configured tracker belongs to, by its host."""
    if config.tracker_environment:
        return config.tracker_environment
    config.require_tracker()  # a missing HCA_TRACKER_URL is named as such, not as an unknown host
    host = urlparse(config.tracker_url or "").hostname
    environment = TRACKER_HOSTS.get(host or "")
    if environment is None:
        known = ", ".join(f"{name} ({env})" for name, env in TRACKER_HOSTS.items())
        raise CheckError(
            f"The configured tracker host {host!r} is not one this package knows ({known}), so the bucket "
            "it ingests from is unknown; set HCA_TRACKER_ENVIRONMENT to dev or prod. Nothing was uploaded"
        )
    return environment


def bucket_for(environment: str) -> str:
    if environment not in BUCKETS:
        raise CheckError(f"environment must be {DEV!r} or {PROD!r}, got {environment!r}")
    return BUCKETS[environment]


def smart_sync_atlas(atlas: str, generation: int) -> str:
    """The name hca-smart-sync knows an atlas version by, e.g. ``gut-v1``."""
    return f"{atlas}-v{generation}"


def s3_prefix(bionetwork: str, name: str, file_type: str) -> str:
    """The key prefix under the bucket, exactly as the CLI's ``_build_s3_path`` lays it out."""
    return f"{bionetwork}/{name}/{file_type}/"


@dataclass(frozen=True)
class Target:
    """Where an upload goes: a bucket and the atlas's prefix in it."""

    environment: str
    bucket: str
    prefix: str
    network: str
    atlas: str
    version: str
    smart_sync_atlas: str
    file_type: str

    @property
    def url(self) -> str:
        return f"s3://{self.bucket}/{self.prefix}"

    def describe(self) -> dict:
        return {
            "environment": self.environment,
            "bucket": self.bucket,
            "prefix": self.prefix,
            "target": self.url,
            "network": self.network,
            "atlas": self.atlas,
            "version": self.version,
            "smart_sync_atlas": self.smart_sync_atlas,
            "file_type": self.file_type,
        }


def resolve_target(
    atlases: list[dict], network: str, atlas: str, generation: int | None, file_type: str, environment: str
) -> Target:
    """Build the target from the tracker's atlas record and hca-smart-sync's atlas map.

    The map (``ATLAS_BIONETWORKS`` in ``hca_smart_sync.cli``) decides the
    prefix, as it does for the CLI; the tracker's record cross-checks it, so a
    stale map is an error here rather than a file under the wrong prefix.
    """
    bucket = bucket_for(environment)
    if file_type not in FILE_TYPES:
        raise CheckError(f"file_type must be one of {', '.join(FILE_TYPES)}, got {file_type!r}")
    version = select_atlas(atlases, network, atlas, generation)
    name = smart_sync_atlas(atlas, version["generation"])
    mapped = smart_sync().cli.ATLAS_BIONETWORKS.get(name)
    if mapped is None:
        raise CheckError(
            f"hca-smart-sync does not know the atlas {name!r} ({atlas_label(network, atlas, atlas_version(version))}); "
            "add it to ATLAS_BIONETWORKS in hca-ingest-tools (smart-sync/src/hca_smart_sync/cli.py) and release "
            "hca-smart-sync before uploading for it. Nothing was uploaded"
        )
    if mapped != network:
        raise CheckError(
            f"hca-smart-sync files {name!r} under the bionetwork {mapped!r}, but the tracker lists the atlas "
            f"under {network!r}; nothing was uploaded. One of them is wrong: fix ATLAS_BIONETWORKS in "
            "hca-ingest-tools or the tracker's record before uploading"
        )
    return Target(
        environment=environment,
        bucket=bucket,
        prefix=s3_prefix(mapped, name, file_type),
        network=network,
        atlas=atlas,
        version=atlas_version(version),
        smart_sync_atlas=name,
        file_type=file_type,
    )


def transfer_tool() -> str | None:
    """The transfer tool the engine will pick: ``s5cmd`` if present, else ``aws``, else ``None``."""
    return next((tool for tool in TRANSFER_TOOLS if shutil.which(tool)), None)


# The engine factory: (profile, log, on_file_start, on_file_done) -> an object with
# SmartSync.sync's signature. Tests swap in hca_tracker_client.testing.fake_engine.
EngineFactory = Callable[[str, TextIO | None, Callable[[str], None] | None, Callable[[str, int], None] | None], Any]


def make_engine(
    profile: str,
    log: TextIO | None = None,
    on_file_start: Callable[[str], None] | None = None,
    on_file_done: Callable[[str, int], None] | None = None,
) -> Any:
    """A ``SmartSync`` configured as the CLI configures it, printing to ``log`` (or nowhere).

    The callbacks hear about each data file as the engine starts and finishes
    uploading it; the manifest it uploads last is not reported.
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
        """The engine, with its two per-file hooks forwarded to the callbacks."""

        def _upload_file(self, local_path, s3_url, include_checksum=True, file_size=None):
            if include_checksum and on_file_start:  # the manifest goes up without a checksum
                on_file_start(Path(local_path).name)
            return super()._upload_file(local_path, s3_url, include_checksum, file_size)

        def _report_upload_success(self, filename, file_size, start_time):
            super()._report_upload_success(filename, file_size, start_time)
            if on_file_done and not filename.endswith(".json"):
                on_file_done(filename, file_size)

    return ReportingSync(config, console=console)


def load_engine(spec: str) -> EngineFactory:
    """Resolve ``module:attribute`` to an engine factory."""
    module_name, _, attribute = spec.partition(":")
    return getattr(importlib.import_module(module_name), attribute)


def _file_entry(info: dict) -> dict:
    """One planned file, in this package's names (the engine's are filename/checksum/local_path)."""
    size = int(info["size"])
    return {
        "name": info["filename"],
        "size_bytes": size,
        "size": human_size(size),
        "sha256": info["checksum"],
        "reason": info["reason"],
    }


def run_plan(engine: Any, directory: Path, target: Target, profile: str, force: bool) -> dict:
    """``sync(plan_only=True)``, with the engine's result shapes folded into one."""
    try:
        result = engine.sync(directory, target.url, force=force, plan_only=True)
    except RuntimeError as error:  # the engine's "Failed to check S3 status for <file>: <code> - <message>"
        raise CheckError(f"hca-smart-sync could not compare {directory} with {target.url}: {error}") from None
    if result.get("error") == "access_denied":
        raise CheckError(
            f"The AWS profile {profile!r} cannot list {target.url} (hca-smart-sync's access check failed: "
            "access denied, no such bucket, or no valid credentials for the profile). Nothing was uploaded"
        )
    planned = [_file_entry(info) for info in result.get("files_to_upload") or []]
    names = {entry["name"] for entry in planned}
    present = sorted(path.name for path in directory.glob("*.h5ad") if path.is_file())
    plan: dict = {
        "local_path": str(directory),
        "files": planned,
        "total_bytes": sum(entry["size_bytes"] for entry in planned),
        "up_to_date": [name for name in present if name not in names],
    }
    plan["total_size"] = human_size(plan["total_bytes"])
    if result.get("no_files_found"):
        plan["no_files_found"] = True
    return plan


def _local_directory(local_path: str) -> Path:
    directory = Path(local_path).expanduser().resolve()
    if directory.is_file():
        raise CheckError(
            f"local_path must be a folder, not a file: hca-smart-sync uploads every .h5ad directly in a "
            f"folder. Put {directory.name} in a folder of its own and pass that"
        )
    if not directory.is_dir():
        raise CheckError(f"local_path {str(directory)!r} is not a folder")
    return directory


@dataclass
class UploadJob:
    """One upload run: a folder to a target, from start to its outcome."""

    job_id: str
    network: str
    atlas: str
    version: str
    smart_sync_atlas: str
    file_type: str
    environment: str
    bucket: str
    prefix: str
    local_path: str
    profile: str
    transfer_tool: str
    force: bool
    files: list[dict]
    total_bytes: int
    log_path: str
    engine: str = DEFAULT_UPLOAD_ENGINE
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
    def target(self) -> str:
        return f"s3://{self.bucket}/{self.prefix}"


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


def _alive(pid: int | None) -> bool:
    """Whether the worker process is still running.

    A worker this process spawned is reaped here when it has exited;
    otherwise it would stay a zombie that ``kill(pid, 0)`` reports as alive.
    """
    if not pid:
        return False
    with contextlib.suppress(ChildProcessError):
        return os.waitpid(pid, os.WNOHANG) == (0, 0)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# One s5cmd progress frame: "42.81%  ━━━───  8.98 MB / 20.97 MB (6.74 MB/s) 1s left (0/1)".
_S5CMD_FRAME = re.compile(r"\d{1,3}\.\d{2}%\s+\S+\s+.*?\(\d+/\d+\)")


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


class Uploads:
    """Plan and run uploads, and report on them. One instance per call is fine."""

    def __init__(self, config: Config, tracker: TrackerClient | None = None):
        self.config = config
        self._tracker = tracker
        self.engine = config.upload_engine
        self.cache_dir = config.cache_dir
        self.store = UploadStore(config.cache_dir)

    @property
    def tracker(self) -> TrackerClient:
        if self._tracker is None:
            self._tracker = self.config.tracker_client()
        return self._tracker

    def _check_environment(self, environment: str) -> None:
        bucket = bucket_for(environment)
        configured = tracker_environment(self.config)
        if configured != environment:
            host = urlparse(self.config.tracker_url or "").hostname
            raise CheckError(
                f"The configured tracker ({host}) is the {configured} tracker, which ingests from "
                f"{BUCKETS[configured]}, but environment={environment!r} names {bucket}; a file uploaded there "
                f"would never appear in this tracker's lists. Pass environment={configured!r}, or point "
                f"HCA_TRACKER_URL at the {environment} tracker. Nothing was uploaded"
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
        self._check_environment(environment)
        directory = _local_directory(local_path)
        target = resolve_target(self.tracker.list_atlases(), network, atlas, generation, file_type, environment)
        profile, profile_source = resolve_profile()
        engine = load_engine(self.engine)(profile, None, None, None)
        plan = run_plan(engine, directory, target, profile, force)
        tool = transfer_tool()
        warnings = []
        if tool is None:
            warnings.append("Neither s5cmd nor aws is on PATH, so start_upload would refuse; install one")
        elif tool == "aws":
            warnings.append("s5cmd is not on PATH; the slower AWS CLI will transfer the files")
        return {
            **target.describe(),
            "profile": profile,
            "profile_source": profile_source,
            "transfer_tool": tool,
            "force": force,
            **plan,
            "warnings": warnings,
        }

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
        plan = self.plan(network, atlas, file_type, local_path, generation, environment, force)
        if plan["transfer_tool"] is None:
            raise CheckError("Neither s5cmd nor aws is on PATH, so nothing can be transferred; install one")
        directory = plan["local_path"]
        if not plan["files"]:
            if plan.get("no_files_found"):
                message = f"No .h5ad files directly in {directory}; nothing to upload"
            else:
                message = (
                    f"Every .h5ad in {directory} is already in {plan['target']} with the same SHA-256; "
                    "nothing to upload. Pass force=true to upload them again"
                )
            return {**plan, "job_id": None, "state": None, "message": message}

        with self.store.locked():
            for job in self.store.all():
                job = self._refresh(job)
                if job.state in ACTIVE and job.local_path == directory:
                    return {**self._describe(job), "message": f"Already uploading from {directory}"}
            job_id = secrets.token_hex(8)
            job = UploadJob(
                job_id=job_id,
                network=network,
                atlas=atlas,
                version=plan["version"],
                smart_sync_atlas=plan["smart_sync_atlas"],
                file_type=file_type,
                environment=environment,
                bucket=plan["bucket"],
                prefix=plan["prefix"],
                local_path=directory,
                profile=plan["profile"],
                transfer_tool=plan["transfer_tool"],
                force=force,
                files=plan["files"],
                total_bytes=plan["total_bytes"],
                log_path=str(self.store.directory / f"{job_id}.log"),
                engine=self.engine,
            )
            self.store.create(job)
            try:
                pid = self._spawn(job)
            except OSError as error:
                self.store.end(job_id, FAILED, f"The upload worker could not be started: {error}")
                raise CheckError(f"The upload worker could not be started, so nothing was uploaded: {error}") from None
            job = self.store.update(job_id, lambda current: setattr(current, "pid", pid)) or job
        return {**self._describe(job), "up_to_date": plan["up_to_date"], "warnings": plan["warnings"]}

    def _spawn(self, job: UploadJob) -> int:
        """Start the worker in a session of its own, its output going to the job's log.

        ``os.posix_spawn`` rather than ``Popen``: nothing waits for the worker,
        and a ``Popen`` collected while its child runs warns about it.
        """
        argv = [sys.executable, "-m", "hca_tracker_client.upload_worker", job.job_id, str(self.cache_dir)]
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
        """Mark a job whose worker has gone away without recording an outcome."""
        if job.state in ACTIVE and job.pid and not _alive(job.pid):
            done = len(job.files_done)
            ended = self.store.end(
                job.job_id,
                INTERRUPTED,
                f"The upload worker (pid {job.pid}) stopped without finishing: {done} of {len(job.files)} files "
                f"uploaded. Run start_upload again; hca-smart-sync skips the files already in the bucket",
            )
            return ended or job
        return job

    def _describe(self, job: UploadJob) -> dict:
        result: dict = {
            "job_id": job.job_id,
            "state": job.state,
            "environment": job.environment,
            "target": job.target,
            "network": job.network,
            "atlas": job.atlas,
            "version": job.version,
            "file_type": job.file_type,
            "local_path": job.local_path,
            "profile": job.profile,
            "transfer_tool": job.transfer_tool,
            "force": job.force,
            "files": job.files,
            "files_total": len(job.files),
            "files_done": len(job.files_done),
            "uploaded": job.files_done,
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


def _tool_version(tool: str, path: str) -> str | None:
    args = [path, "version"] if tool == "s5cmd" else [path, "--version"]
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
        line = (result.stdout or result.stderr).strip().splitlines()
        return line[0] if line else None
    return None


def upload_report(config: Config) -> dict:
    """What an upload needs, and whether each piece is in place: for ``check_environment``."""
    report: dict = {"smart_sync": {}, "transfer_tools": {}, "profile": {}, "bucket": {}}
    try:
        package = smart_sync()
        report["smart_sync"] = {"ok": True, "version": package.__version__}
    except ConfigError as error:
        report["smart_sync"] = {"ok": False, "error": str(error)}

    for tool in TRANSFER_TOOLS:
        path = shutil.which(tool)
        entry: dict = {"ok": path is not None}
        if path:
            entry |= {"path": path, "version": _tool_version(tool, path)}
        report["transfer_tools"][tool] = entry
    tool = transfer_tool()
    report["transfer_tools"]["selected"] = tool

    profile: str | None = None
    if report["smart_sync"]["ok"]:
        try:
            profile, source = resolve_profile()
            report["profile"] = {"ok": True, "name": profile, "source": source}
        except ConfigError as error:
            report["profile"] = {"ok": False, "error": str(error)}

    bucket: dict = {"ok": False}
    try:
        environment = tracker_environment(config)
        bucket |= {"environment": environment, "name": BUCKETS[environment]}
    except CheckError as error:
        bucket["error"] = str(error)
    if profile and "name" in bucket:
        target = Target(bucket["environment"], bucket["name"], "", "", "", "", "", SOURCE_DATASETS)  # the bucket root
        try:
            # A plan over an empty folder runs the engine's access check and nothing else.
            with tempfile.TemporaryDirectory() as empty:
                engine = load_engine(config.upload_engine)(profile, None, None, None)
                run_plan(engine, Path(empty), target, profile, False)
            bucket["ok"] = True
        except (CheckError, ConfigError) as error:
            bucket["error"] = str(error)
    report["bucket"] = bucket

    notes = []
    if tool == "aws":
        notes.append("Only the AWS CLI was found; s5cmd is faster for multi-GB files")
    report["can_upload"] = bool(report["smart_sync"]["ok"] and tool and bucket["ok"])
    report["notes"] = notes
    return report
