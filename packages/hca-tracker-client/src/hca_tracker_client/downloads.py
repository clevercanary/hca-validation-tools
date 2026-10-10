"""Starting, following, cancelling and deleting downloads.

aria2 does the transfer, the queue, resume and SHA-256 verification; this
module runs the checks before a download, maps aria2's state onto ours, and
keeps the job records. Nothing returned here contains a presigned URL or the
API token.
"""

import contextlib
import re
import secrets
import time
from pathlib import Path

from .api import TrackerClient, probe
from .catalog import atlas_files
from .checks import (
    check_space,
    check_writable,
    existing_ancestor,
    find_aria2c,
    free_bytes,
    human_duration,
    human_size,
)
from .config import Config
from .daemon import Aria2, Aria2Error, connect, daemon_dir, ensure_daemon
from .errors import AuthError, CheckError, ConfigError, JobError, TrackerError
from .outcome import finalize, record_error
from .selection import atlas_label, atlas_version, find_file, select_atlas
from .store import (
    ACTIVE,
    CANCELLED,
    DONE,
    DOWNLOADING,
    INTERRUPTED,
    QUEUED,
    VERIFYING,
    Job,
    JobStore,
    control_path,
    final_path,
    part_path,
)

_CONTROL = re.compile(r"[\x00-\x1f\x7f\\]")


def _safe_component(value: str, what: str) -> str:
    """Reject a tracker value used as one path component that would escape its folder or inject aria2 options.

    aria2 saves each download's options as ``key=value`` lines, so a newline
    would become extra options when the session is reloaded.
    """
    if not value or Path(value).name != value or value in (".", "..") or _CONTROL.search(value):
        raise TrackerError(f"The tracker returned an unusable {what}: {value!r}")
    return value


def _safe_name(filename: str) -> str:
    if filename.endswith((".part", ".aria2")):  # aria2's working-file names
        raise TrackerError(f"The tracker returned an unusable file name: {filename!r}")
    return _safe_component(filename, "file name")


def _allocated(path: Path) -> int:
    """Bytes a (possibly sparse) file occupies on disk; 0 if it does not exist."""
    try:
        return path.stat().st_blocks * 512
    except (FileNotFoundError, AttributeError):
        return 0


def _cancel_message(job: Job) -> str:
    if job.part.exists():
        return (
            f"Cancelled. The partial file is kept at {job.part}: start_download resumes it, delete_download removes it"
        )
    return "Cancelled before any data arrived. start_download starts it again"


def _progress(job: Job, live: dict) -> dict:
    total = int(live.get("totalLength") or 0) or job.size
    if job.state == VERIFYING:
        verified = int(live.get("verifiedLength") or 0)
        return {
            "verified_bytes": verified,
            "bytes_total": total,
            "percent": round(100 * verified / total, 1) if total else None,
        }
    done = int(live.get("completedLength") or 0)
    rate = int(live.get("downloadSpeed") or 0)
    eta = (total - done) / rate if rate and total > done else None
    return {
        "bytes_done": done,
        "bytes_total": total,
        "percent": round(100 * done / total, 1) if total else None,
        "rate_bytes_per_s": rate,
        "rate": f"{human_size(rate)}/s",
        "eta_seconds": round(eta) if eta is not None else None,
        "eta": human_duration(eta) if eta is not None else None,
    }


class Downloads:
    """Download jobs for one cache folder."""

    def __init__(self, config: Config, tracker: TrackerClient | None = None):
        self.config = config
        # Resolved, so job paths (built from resolved folders) and the cache scan agree
        # even when the cache is reached through a symlink.
        self.cache_dir = config.cache_dir.resolve()
        self.store = JobStore(self.cache_dir)
        self._tracker = tracker

    @property
    def tracker(self) -> TrackerClient:
        if self._tracker is None:
            self._tracker = self.config.tracker_client()
        return self._tracker

    def _daemon(self, aria2c: str | None = None) -> Aria2:
        """The running daemon, started if needed."""
        aria2c = aria2c or find_aria2c()[0]
        return ensure_daemon(self.cache_dir, aria2c, self.config.max_concurrent)

    def _running_daemon(self) -> Aria2 | None:
        """The running daemon, restarted (from its session) if jobs are active but it is not running.

        Every operation reads aria2 through this, so after a crash or reboot
        whichever call comes first resumes the unfinished downloads.
        """
        aria2 = connect(self.cache_dir)
        if aria2 is not None or not any(job.state in ACTIVE for job in self.store.all()):
            return aria2
        try:
            return self._daemon()
        except TrackerError:
            return None

    def _internal_dirs(self) -> set[Path]:
        """Folders under the cache that hold this package's own state, not downloads."""
        return {daemon_dir(self.cache_dir), self.store.directory}

    # -- state ---------------------------------------------------------------

    def _refresh(self, job: Job, aria2: Aria2 | None) -> tuple[Job, dict]:
        """Bring an active job's state up to date from aria2; returns (job, live status)."""
        if job.state not in ACTIVE or aria2 is None:
            return job, {}
        try:
            live = aria2.tell_status(job.job_id)
        except Aria2Error as error:
            return (self._lost(job) if error.not_found else job), {}

        status = live.get("status")
        if status == "complete":
            return finalize(job, self.store), {}
        if status == "error":
            return record_error(job, self.store, live, aria2), {}
        if status == "removed":
            return self.store.end(job, CANCELLED, _cancel_message(job)), {}
        if status == "active":
            verifying = "verifiedLength" in live or live.get("verifyIntegrityPending") == "true"
            new_state = VERIFYING if verifying else DOWNLOADING
        else:  # waiting, paused
            new_state = QUEUED
        if new_state != job.state:
            job.state = new_state
            job = self.store.save(job)
        return job, live

    def _lost(self, job: Job) -> Job:
        """aria2 no longer knows an active job: the hook recorded it, or it was lost."""
        fresh = self.store.load(job.job_id) or job
        if fresh.state not in ACTIVE:
            return fresh
        # aria2 deletes its control file only once a download has completed
        # (and passed its checksum), so a full-size .part without one is a
        # finished download whose hook did not run before aria2 forgot it.
        if fresh.part.exists() and not fresh.control.exists() and fresh.part.stat().st_size == fresh.size:
            return finalize(fresh, self.store)
        message = (
            "aria2 lost track of this download (e.g. a crash before its session was saved). "
            "Run start_download again to resume it"
        )
        return self.store.end(fresh, INTERRUPTED, message)

    def _describe(self, job: Job, live: dict | None = None) -> dict:
        result: dict = {
            "job_id": job.job_id,
            "state": job.state,
            "network": job.network,
            "atlas": job.atlas,
            "version": job.version,
            "file": job.file_name,
            "path": job.path,
            "size_bytes": job.size,
            "size": human_size(job.size),
        }
        if job.state in (DOWNLOADING, VERIFYING) and live:
            result["progress"] = _progress(job, live)
        if job.state not in ACTIVE and job.state != DONE and job.part.exists():
            result["partial_path"] = str(job.part)
        if job.message:
            result["message"] = job.message
        if job.error_code is not None:
            result["error_code"] = job.error_code
        if job.state == DONE:
            result["verified"] = job.verified
        return result

    def _reserved(self, directory: Path, aria2: Aria2 | None, exclude: Path) -> int:
        """Bytes still to come for other active downloads on the same filesystem."""
        device = existing_ancestor(directory).stat().st_dev
        reserved = 0
        for job in self.store.all():
            if job.state not in ACTIVE or job.path == str(exclude):
                continue
            if existing_ancestor(job.final.parent).stat().st_dev != device:
                continue
            job, live = self._refresh(job, aria2)
            if job.state in ACTIVE:
                reserved += max(job.size - int(live.get("completedLength") or 0), 0)
        return reserved

    # -- operations ----------------------------------------------------------

    def start(
        self,
        network: str,
        atlas: str,
        file: str,
        generation: int | None = None,
        published: bool = False,
        dest_dir: str | None = None,
        restart: bool = False,
    ) -> dict:
        """Check, then start downloading one file in the background.

        Returns at once with the job id and the path the file will have. Every
        check runs before anything is downloaded.
        """
        tracker = self.tracker
        version_record = select_atlas(tracker.list_atlases(), network, atlas, generation, published)
        version = atlas_version(version_record)
        label = atlas_label(network, atlas, version)
        atlas_id = version_record["id"]
        entry = find_file(atlas_files(tracker, atlas_id), file, label)

        warnings = []
        integrity = entry.get("integrityStatus")
        if integrity != "valid":
            warnings.append(f"The tracker's integrity status for this file is {integrity!r}, not 'valid'")

        presigned = tracker.presigned_url(atlas_id, entry["fileId"])
        filename = _safe_name(presigned.filename)
        safe_network = _safe_component(network, "network")
        safe_version_dir = _safe_component(f"{_safe_component(atlas, 'atlas slug')}_{version}", "atlas version")
        default_dir = self.cache_dir / safe_network / safe_version_dir
        # Resolved, so two spellings of one folder (symlink, "..") are one destination.
        directory = (Path(dest_dir).expanduser() if dest_dir else default_dir).resolve()
        if _CONTROL.search(str(directory)):
            raise CheckError(f"The download folder {str(directory)!r} contains a control character or backslash")
        if any(directory.resolve().is_relative_to(folder.resolve()) for folder in self._internal_dirs()):
            raise CheckError(f"{directory} holds the download cache's own state; choose another dest_dir")
        final = directory / filename

        probed = probe(presigned)
        listed = int(entry.get("sizeBytes") or 0)
        if probed.size is not None and listed and probed.size != listed:
            raise CheckError(
                f"The tracker lists {filename} as {listed} bytes, but the stored file is {probed.size} bytes"
            )
        size = probed.size or listed
        if not probed.sha256:
            raise CheckError(
                f"{filename} has no source checksum (x-amz-meta-source-sha256), so it could not be verified "
                "after download; nothing was downloaded. It was probably not uploaded with hca-smart-sync"
            )
        if not size:
            raise CheckError(f"The size of {filename} is unknown, so it cannot be checked after download")

        summary = {"network": network, "atlas": atlas, "version": version, "file": filename, "path": str(final)}
        summary |= {"size_bytes": size, "size": human_size(size), "warnings": warnings}

        # Two calls for the same file (or two large files competing for space)
        # must not both pass these checks before either job is recorded.
        with self.store.locked():
            aria2 = self._running_daemon()
            previous = [self._refresh(job, aria2)[0] for job in self.store.for_path(final)]
            active = [job for job in previous if job.state in ACTIVE]
            if active:
                return {**self._describe(active[-1]), "message": "Already downloading", "warnings": warnings}

            if final.exists():
                done = [job for job in previous if job.state == DONE]
                if done and final.stat().st_size == size and done[-1].sha256 == probed.sha256:
                    cached = {"job_id": done[-1].job_id, "state": DONE, "cached": True, "verified": done[-1].verified}
                    return {**summary, **cached}
                raise CheckError(
                    f"{final} already exists but is not a verified download of this file revision; "
                    "delete it with delete_download (or move it) first"
                )

            part, control = part_path(final), control_path(final)
            last = previous[-1] if previous else None
            # With restart, the old files are removed only once every check below has passed.
            if not restart and last is not None and last.checksum_failed:
                raise CheckError(
                    f"The last download of {filename} failed its checksum and is kept at {part}; "
                    "run delete_download, or pass restart=true to download it again from scratch"
                )
            if not restart and part.exists() and not control.exists():
                raise CheckError(
                    f"A partial file {part} exists without aria2's control file, so it cannot be resumed safely; "
                    "pass restart=true to download from scratch"
                )

            aria2c, _ = find_aria2c()
            check_writable(directory)
            # Resuming needs only the rest; restarting frees the old .part first. Either way
            # the net space needed is the file less what the .part already occupies.
            already = min(_allocated(part), size)
            reserved = self._reserved(directory, aria2, exclude=final)
            check_space(directory, size - already, size, reserved)
            aria2 = self._daemon(aria2c)
            if restart:
                for stale in (part, control):
                    with contextlib.suppress(FileNotFoundError):
                        stale.unlink()
                already = 0
            job = Job(
                job_id=secrets.token_hex(8),
                network=network,
                atlas=atlas,
                version=version,
                file_name=filename,
                file_id=entry["fileId"],
                path=str(final),
                size=size,
                sha256=probed.sha256,
            )
            options = {
                "gid": job.job_id,
                "dir": str(directory),
                "out": part.name,
                "checksum": f"sha-256={probed.sha256}",
            }
            try:
                aria2.call("addUri", [presigned.url], options)
            except Aria2Error as error:
                raise TrackerError(f"aria2 did not accept the download: {error}") from None
            # Saved only once aria2 knows the GID: a record visible earlier could be
            # refreshed, found missing from aria2, and marked interrupted for good.
            # If the download finishes first, the hook skips it and download_status
            # finalizes it from aria2's result.
            try:
                self.store.create(job)
            except OSError as error:  # don't leave a transfer running that no tool can see
                with contextlib.suppress(Aria2Error):
                    aria2.call("forceRemove", job.job_id)
                    aria2.call("removeDownloadResult", job.job_id)
                    aria2.call("saveSession")
                raise TrackerError(f"Could not record the download job, so it was not started: {error}") from None

            result = {**self._describe(job), "warnings": warnings}
            if already:
                # Not a byte count: aria2 writes segments across the file, so the .part's
                # disk usage overstates what has been downloaded. download_status has that.
                result["message"] = "Resuming the partial download from aria2's control file"
            return result

    def status(self, job_id: str | None = None) -> dict:
        """One job's state and progress, or every job's when no id is given."""
        aria2 = self._running_daemon()
        if job_id:
            job = self.store.load(job_id)
            if job is None:
                raise JobError(f"No download job {job_id!r}")
            return self._describe(*self._refresh(job, aria2))
        jobs = [self._describe(*self._refresh(job, aria2)) for job in self.store.all()]
        return {"jobs": list(reversed(jobs))}

    def cancel(self, job_id: str) -> dict:
        """Stop a queued or running download; its partial file is kept for resuming."""
        job = self.store.load(job_id)
        if job is None:
            raise JobError(f"No download job {job_id!r}")
        aria2 = self._running_daemon()
        job, _ = self._refresh(job, aria2)
        if job.state not in ACTIVE:
            raise JobError(f"Job {job_id} is {job.state}; there is nothing to cancel")
        # Cancelled is recorded only once aria2 has dropped the job and saved its
        # session; otherwise a later daemon start would resume it.
        if aria2 is None:
            raise JobError("aria2 is not running and could not be started, so the download was not cancelled")
        with contextlib.suppress(Aria2Error):
            aria2.call("forceRemove", job_id)
        # The download can finish between the refresh above and forceRemove;
        # record what actually happened rather than calling it cancelled.
        live: dict = {}
        forgotten = False
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                live = aria2.tell_status(job_id)
            except Aria2Error as error:
                forgotten = error.not_found
                break
            if live.get("status") in ("removed", "complete", "error"):
                break
            time.sleep(0.1)
        if live.get("status") == "complete":
            return self._describe(finalize(job, self.store))
        if live.get("status") == "error":
            return self._describe(record_error(job, self.store, live, aria2))
        if live.get("status") != "removed" and not forgotten:
            raise JobError(f"aria2 did not confirm cancelling job {job_id}; try again")
        try:
            with contextlib.suppress(Aria2Error):
                aria2.call("removeDownloadResult", job_id)  # already gone if forgotten
            aria2.call("saveSession")
        except Aria2Error as error:
            raise JobError(f"aria2 stopped job {job_id} but could not save its session: {error}") from None
        # If the hook recorded an outcome meanwhile, the store keeps it.
        return self._describe(self.store.end(job, CANCELLED, _cancel_message(job)))

    def list_files(self) -> dict:
        """Downloaded and partial files: those this cache has jobs for, and any others under the cache folder."""
        aria2 = connect(self.cache_dir)
        latest: dict[str, Job] = {}
        for job in self.store.all():
            latest[job.path] = self._refresh(job, aria2)[0]

        entries = []
        for path, job in latest.items():
            final, part = Path(path), part_path(Path(path))
            if not final.exists() and not part.exists():
                continue
            on_disk = final.stat().st_size if final.exists() else _allocated(part)
            entry = {
                "path": path,
                "state": job.state if not final.exists() or job.state == DONE else "untracked",
                "network": job.network,
                "atlas": job.atlas,
                "version": job.version,
                "size_bytes": job.size,
                "size": human_size(job.size),
                "on_disk_bytes": on_disk,
                "job_id": job.job_id,
            }
            if job.state == DONE:
                entry["verified"] = job.verified
            entries.append(entry)

        if self.cache_dir.is_dir():
            internal = self._internal_dirs()
            for path in sorted(self.cache_dir.rglob("*")):
                if not path.is_file() or path.name.startswith(".") or path.name.endswith(".aria2"):
                    continue
                if any(path.is_relative_to(folder) for folder in internal):
                    continue
                if str(final_path(path)) in latest:
                    continue
                entries.append({"path": str(path), "state": "untracked", "on_disk_bytes": path.stat().st_size})
        return {"cache_dir": str(self.cache_dir), "files": entries}

    def delete(self, path: str) -> dict:
        """Delete a downloaded or partial file (with aria2's control file) and its job records.

        Allowed for files under the cache folder, and for exactly the files a
        recorded job downloaded elsewhere (``dest_dir``) — not their neighbours.
        """
        given = Path(path).expanduser().absolute()
        final = final_path(given)
        # Under start's lock, so a download being registered can't lose its files.
        with self.store.locked():
            jobs = [job for job in self.store.all() if job.final.resolve() == final.resolve()]
            if not jobs:  # untracked: exactly the path given, never a sibling it looks related to
                final = given
            resolved = final.resolve()
            in_cache = resolved.is_relative_to(self.cache_dir.resolve()) and not any(
                resolved.is_relative_to(folder.resolve()) for folder in self._internal_dirs()
            )
            if not in_cache and not jobs:
                raise JobError(f"{path} is not in the download cache or a file a download job saved")

            aria2 = connect(self.cache_dir)
            if any(self._refresh(job, aria2)[0].state in ACTIVE for job in jobs):
                raise JobError(f"{final.name} is still downloading; cancel it with cancel_download first")

            related = (final, part_path(final), control_path(final)) if jobs else (final,)
            targets = [p for p in related if p.is_file()]
            if not targets:
                raise JobError(f"Nothing to delete at {final}")
            freed = sum(_allocated(p) for p in targets)
            for target in targets:
                target.unlink()
            for job in jobs:
                self.store.delete(job.job_id)
        return {"deleted": [str(p) for p in targets], "freed_bytes": freed, "freed": human_size(freed)}


def environment_report(config: Config) -> dict:
    """What a download needs, and whether each piece is in place."""
    report: dict = {}
    try:
        path, version = find_aria2c()
        report["aria2c"] = {"ok": True, "path": path, "version": version}
    except CheckError as error:
        report["aria2c"] = {"ok": False, "error": str(error)}

    daemon = connect(config.cache_dir)
    daemon_report: dict = {"running": daemon is not None}
    if daemon is not None:
        with contextlib.suppress(Aria2Error):
            daemon_report["version"] = daemon.version()
    report["aria2_daemon"] = daemon_report

    cache: dict = {"path": str(config.cache_dir)}
    try:
        check_writable(config.cache_dir)
        cache["writable"] = True
    except CheckError as error:
        cache["writable"] = False
        cache["error"] = str(error)
    with contextlib.suppress(OSError):
        free = free_bytes(config.cache_dir)
        cache |= {"free_bytes": free, "free": human_size(free)}
    report["cache_dir"] = cache
    report["max_concurrent_downloads"] = config.max_concurrent

    tracker: dict = {"url": config.tracker_url}
    try:
        config.tracker_client().list_atlases()
        tracker |= {"reachable": True, "token_valid": True}
    except AuthError as error:
        tracker |= {"reachable": True, "token_valid": False, "error": str(error)}
    except TrackerError as error:
        tracker |= {"reachable": None if isinstance(error, ConfigError) else False, "token_valid": None}
        tracker["error"] = str(error)
    report["tracker"] = tracker
    return report
