"""Starting, following, cancelling and deleting downloads.

aria2 does the transfer, the queue, resume and SHA-256 verification; this
module runs the checks before a download, maps aria2's state onto ours, and
keeps the job records. Nothing returned here contains a presigned URL or the
API token.
"""

import contextlib
import http.client
import secrets
import time
import xmlrpc.client
from pathlib import Path

from .api import TrackerClient, probe
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
from .daemon import Aria2, Aria2Error, connect, ensure_daemon
from .errors import AuthError, CheckError, ConfigError, JobError, TrackerError
from .outcome import finalize, record_error
from .selection import atlas_version, find_file, select_atlas
from .store import ACTIVE, CANCELLED, DONE, DOWNLOADING, INTERRUPTED, QUEUED, VERIFYING, Job, JobStore

_RPC_ERRORS = (Aria2Error, OSError, http.client.HTTPException, xmlrpc.client.ProtocolError)


def _safe_name(filename: str) -> str:
    """Reject a tracker file name that would escape its folder."""
    if not filename or Path(filename).name != filename or filename in (".", ".."):
        raise TrackerError(f"The tracker returned an unusable file name: {filename!r}")
    return filename


def _allocated(path: Path) -> int:
    """Bytes a (possibly sparse) file occupies on disk; 0 if it does not exist."""
    try:
        return path.stat().st_blocks * 512
    except (FileNotFoundError, AttributeError):
        return 0


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
        self.cache_dir = config.cache_dir
        self.store = JobStore(config.cache_dir)
        self._tracker = tracker

    @property
    def tracker(self) -> TrackerClient:
        if self._tracker is None:
            self._tracker = TrackerClient(*self.config.require_tracker())
        return self._tracker

    def _daemon(self) -> Aria2:
        aria2c, _ = find_aria2c()
        return ensure_daemon(self.cache_dir, aria2c, self.config.max_concurrent)

    def _daemon_if_needed(self) -> Aria2 | None:
        """The running daemon; restarted (from its session) if jobs are active but it is not running."""
        aria2 = connect(self.cache_dir)
        if aria2 is not None or not any(job.state in ACTIVE for job in self.store.all()):
            return aria2
        try:
            return self._daemon()
        except TrackerError:
            return None

    # -- state ---------------------------------------------------------------

    def _refresh(self, job: Job, aria2: Aria2 | None) -> tuple[Job, dict]:
        """Bring an active job's state up to date from aria2; returns (job, live status)."""
        if job.state not in ACTIVE or aria2 is None:
            return job, {}
        try:
            live = aria2.tell_status(job.job_id)
        except Aria2Error as error:
            if not error.not_found:
                return job, {}
            return self._lost(job), {}
        except _RPC_ERRORS:
            return job, {}

        status = live.get("status")
        if status == "complete":
            return finalize(job, self.store), {}
        if status == "error":
            return record_error(job, self.store, live, aria2), {}
        if status == "removed":
            new_state = CANCELLED
        elif status == "active":
            verifying = "verifiedLength" in live or live.get("verifyIntegrityPending") == "true"
            new_state = VERIFYING if verifying else DOWNLOADING
        else:  # waiting, paused
            new_state = QUEUED
        if new_state != job.state:
            job.state = new_state
            self.store.save(job)
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
        fresh.state = INTERRUPTED
        fresh.message = "aria2 lost track of this download (e.g. a crash before its session was saved). " + (
            "Run start_download again to resume it"
        )
        fresh.finished_at = time.time()
        self.store.save(fresh)
        return fresh

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
            "verification": "sha256" if job.sha256 else "size only (no checksum available)",
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

    def _estimate(self, remaining: int) -> str | None:
        """Time for ``remaining`` bytes at the average rate of recent downloads in this cache."""
        recent = [j for j in self.store.all() if j.state == DONE and j.finished_at and j.finished_at > j.created_at]
        recent = recent[-5:]
        seconds = sum(j.finished_at - j.created_at for j in recent if j.finished_at)
        if not recent or seconds <= 0:
            return None
        rate = sum(j.size for j in recent) / seconds
        return human_duration(remaining / rate)

    # -- operations ----------------------------------------------------------

    def start(
        self,
        network: str,
        atlas: str,
        file: str,
        generation: int | None = None,
        published: bool = False,
        dest_dir: str | None = None,
        confirm: bool = False,
        restart: bool = False,
    ) -> dict:
        """Check, then start downloading one file in the background.

        Returns at once with the job id and the path the file will have. Every
        check runs before anything is downloaded.
        """
        tracker = self.tracker
        version_record = select_atlas(tracker.list_atlases(), network, atlas, generation, published)
        version = atlas_version(version_record)
        label = f"{network}/{atlas} {version}"
        atlas_id = version_record["id"]
        entry = find_file(tracker.component_atlases(atlas_id) + tracker.source_datasets(atlas_id), file, label)

        warnings = []
        integrity = entry.get("integrityStatus")
        if integrity != "valid":
            warnings.append(f"The tracker's integrity status for this file is {integrity!r}, not 'valid'")

        presigned = tracker.presigned_url(atlas_id, entry["fileId"])
        filename = _safe_name(presigned.filename)
        default_dir = self.cache_dir / network / f"{atlas}_{version}"
        directory = (Path(dest_dir).expanduser() if dest_dir else default_dir).absolute()
        final = directory / filename

        probed = probe(presigned)
        listed = int(entry.get("sizeBytes") or 0)
        if probed.size is not None and listed and probed.size != listed:
            raise CheckError(
                f"The tracker lists {filename} as {listed} bytes, but the stored file is {probed.size} bytes"
            )
        size = probed.size or listed
        if not size:
            raise CheckError(f"The size of {filename} is unknown, so it cannot be checked after download")

        summary = {"network": network, "atlas": atlas, "version": version, "file": filename, "path": str(final)}
        summary |= {"size_bytes": size, "size": human_size(size), "warnings": warnings}

        aria2 = connect(self.cache_dir)
        previous = [self._refresh(job, aria2)[0] for job in self.store.for_path(final)]
        active = [job for job in previous if job.state in ACTIVE]
        if active:
            return {**self._describe(active[-1]), "message": "Already downloading", "warnings": warnings}

        if final.exists():
            done = [job for job in previous if job.state == DONE]
            if done and final.stat().st_size == size and done[-1].sha256 == probed.sha256:
                return {**summary, "state": DONE, "cached": True, "verified": done[-1].verified}
            raise CheckError(
                f"{final} already exists but is not a verified download of this file revision; "
                "delete it with delete_download (or move it) first"
            )

        part = Path(f"{final}.part")
        control = Path(f"{final}.part.aria2")
        last = previous[-1] if previous else None
        if restart:
            for stale in (part, control):
                with contextlib.suppress(FileNotFoundError):
                    stale.unlink()
        elif last is not None and last.checksum_failed:
            raise CheckError(
                f"The last download of {filename} failed its checksum and is kept at {part}; "
                "run delete_download, or pass restart=true to download it again from scratch"
            )
        elif part.exists() and not control.exists():
            raise CheckError(
                f"A partial file {part} exists without aria2's control file, so it cannot be resumed safely; "
                "pass restart=true to download from scratch"
            )

        find_aria2c()
        check_writable(directory)
        already = min(_allocated(part), size)
        remaining = size - already
        reserved = self._reserved(directory, aria2, exclude=final)
        free = check_space(directory, remaining, size, reserved)
        if size > self.config.confirm_bytes and not confirm:
            estimate = self._estimate(remaining)
            return {
                **summary,
                "needs_confirmation": True,
                "free_bytes": free,
                "free": human_size(free),
                "estimated_time": estimate,
                "message": (
                    f"{filename} is {human_size(size)} ({human_size(free)} free"
                    + (f", about {estimate} at recent speeds" if estimate else "")
                    + "). Call start_download again with confirm=true to download it"
                ),
            }

        aria2 = self._daemon()
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
        self.store.save(job)
        options = {"gid": job.job_id, "dir": str(directory), "out": part.name}
        if probed.sha256:
            options["checksum"] = f"sha-256={probed.sha256}"
        try:
            aria2.call("addUri", [presigned.url], options)
        except _RPC_ERRORS as error:
            self.store.delete(job.job_id)
            raise TrackerError(f"aria2 did not accept the download: {error}") from None

        result = {**self._describe(job), "warnings": warnings}
        if already:
            result["message"] = f"Resuming from {human_size(already)} already downloaded"
        return result

    def status(self, job_id: str | None = None) -> dict:
        """One job's state and progress, or every job's when no id is given."""
        aria2 = self._daemon_if_needed()
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
        aria2 = connect(self.cache_dir)
        job, _ = self._refresh(job, aria2)
        if job.state not in ACTIVE:
            raise JobError(f"Job {job_id} is {job.state}; there is nothing to cancel")
        if aria2 is not None:
            with contextlib.suppress(*_RPC_ERRORS):
                aria2.call("forceRemove", job_id)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    if aria2.tell_status(job_id).get("status") == "removed":
                        break
                except _RPC_ERRORS:
                    break
                time.sleep(0.1)
            with contextlib.suppress(*_RPC_ERRORS):
                aria2.call("removeDownloadResult", job_id)
        job.state = CANCELLED
        job.finished_at = time.time()
        job.message = (
            f"Cancelled. The partial file is kept at {job.part}: start_download resumes it, delete_download removes it"
        )
        self.store.save(job)
        return self._describe(job)

    def list_files(self) -> dict:
        """Downloaded and partial files: those this cache has jobs for, and any others under the cache folder."""
        aria2 = connect(self.cache_dir)
        latest: dict[str, Job] = {}
        for job in self.store.all():
            latest[job.path] = self._refresh(job, aria2)[0]

        entries = []
        for path, job in latest.items():
            final, part = Path(path), Path(path + ".part")
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
            internal = {self.cache_dir / "aria2", self.cache_dir / "jobs"}
            for path in sorted(self.cache_dir.rglob("*")):
                if not path.is_file() or path.name.startswith(".") or path.name.endswith(".aria2"):
                    continue
                if any(path.is_relative_to(folder) for folder in internal):
                    continue
                final = str(path)[: -len(".part")] if path.name.endswith(".part") else str(path)
                if final in latest:
                    continue
                entries.append({"path": str(path), "state": "untracked", "on_disk_bytes": path.stat().st_size})
        return {"cache_dir": str(self.cache_dir), "files": entries}

    def delete(self, path: str) -> dict:
        """Delete a downloaded or partial file (with aria2's control file) and its job records.

        Only files inside the cache folder, or in a folder a job downloaded
        to, can be deleted.
        """
        given = Path(path).expanduser().absolute()
        text = str(given)
        for suffix in (".part.aria2", ".part"):
            if text.endswith(suffix):
                text = text[: -len(suffix)]
                break
        final = Path(text)

        jobs = self.store.for_path(final)
        roots = {self.cache_dir.resolve()} | {Path(job.path).parent.resolve() for job in self.store.all()}
        internal = {(self.cache_dir / "aria2").resolve(), (self.cache_dir / "jobs").resolve()}
        resolved = final.resolve()
        if not any(resolved.is_relative_to(root) for root in roots) or any(
            resolved.is_relative_to(folder) for folder in internal
        ):
            raise JobError(f"{path} is not in the download cache or a folder a download was saved to")

        aria2 = connect(self.cache_dir)
        if any(self._refresh(job, aria2)[0].state in ACTIVE for job in jobs):
            raise JobError(f"{final.name} is still downloading; cancel it with cancel_download first")

        targets = [p for p in (final, Path(f"{final}.part"), Path(f"{final}.part.aria2")) if p.is_file()]
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
        with contextlib.suppress(*_RPC_ERRORS):
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
    report["confirm_above"] = human_size(config.confirm_bytes)

    tracker: dict = {"url": config.tracker_url}
    try:
        client = TrackerClient(*config.require_tracker())
        client.list_atlases()
        tracker |= {"reachable": True, "token_valid": True}
    except AuthError as error:
        tracker |= {"reachable": True, "token_valid": False, "error": str(error)}
    except TrackerError as error:
        tracker |= {"reachable": None if isinstance(error, ConfigError) else False, "token_valid": None}
        tracker["error"] = str(error)
    report["tracker"] = tracker
    return report
