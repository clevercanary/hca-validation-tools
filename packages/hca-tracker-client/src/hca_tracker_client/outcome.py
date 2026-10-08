"""Recording how a download ended.

aria2 runs the hook for this as soon as a download completes or fails, even
with no MCP server running. ``download_status`` calls the same functions if it
finds a download aria2 has finished but the hook has not recorded (the hook can
fail, e.g. if the Python environment it points at was removed), so either path
can get there first and both are idempotent.
"""

import contextlib

from .daemon import Aria2, Aria2Error
from .errors import redact
from .store import CHECKSUM_MISMATCH, DONE, FAILED, Job, JobStore

# aria2 error 22: the server answered with an HTTP error status.
HTTP_ERROR = 22


def finalize(job: Job, store: JobStore) -> Job:
    """Rename a completed ``.part`` file to its final name and mark the job done.

    aria2 only reports a download complete once the size matches and, when
    the job carries a SHA-256, once the whole file has been hashed and matches
    it. The size is checked again here before the rename.
    """
    if job.state == DONE:
        return job
    part, final = job.part, job.final
    try:
        size = part.stat().st_size
        if size != job.size:
            message = f"Size mismatch: expected {job.size} bytes, got {size}; the .part file is kept at {part}"
            return store.end(job, FAILED, message)
        part.replace(final)
    except FileNotFoundError:  # the hook and download_status can both get here; one renames first
        if not (final.exists() and final.stat().st_size == job.size):
            return store.end(job, FAILED, f"The downloaded file is missing: {part}")
    if job.sha256:
        job.verified = "sha256"
        return store.end(job, DONE, "Size and SHA-256 verified")
    job.verified = "size"
    return store.end(job, DONE, "Size verified, no checksum available (file not uploaded with hca-smart-sync)")


def record_error(job: Job, store: JobStore, status: dict, aria2: Aria2 | None) -> Job:
    """Record a failed download, then have aria2 forget it.

    A failed download stays in aria2's session file otherwise, and every
    daemon restart would retry it — for a checksum mismatch, re-hashing the
    whole file each time.
    """
    code = int(status.get("errorCode") or 0) or None
    detail = redact(status.get("errorMessage") or "")
    if code == CHECKSUM_MISMATCH:
        message = (
            f"Checksum mismatch: the downloaded file does not match the source SHA-256 {job.sha256}. "
            f"The file is kept at {job.part}; run delete_download, or start_download with restart=true "
            "to download it again from scratch"
        )
    elif code == HTTP_ERROR and "403" in detail:
        message = (
            "The download link was refused (it expires after 48 hours, or was revoked). "
            "Run start_download again to resume with a fresh link"
        )
    else:
        message = f"aria2 error {code}: {detail or 'no detail'}. Run start_download again to resume"
    job = store.end(job, FAILED, message, code)
    if aria2 is not None:
        with contextlib.suppress(Aria2Error):
            aria2.call("removeDownloadResult", job.job_id)
    return job
