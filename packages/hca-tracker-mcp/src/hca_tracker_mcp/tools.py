"""MCP wrappers over hca_tracker_client.

Each tool loads the config per call, so a changed .env or token takes effect
without restarting the server, and returns ``{"error": ...}`` instead of
raising. No tool returns the API token or a presigned URL.
"""

import contextlib
from collections.abc import Callable
from functools import wraps
from typing import Any

from hca_tracker_client import (
    INTEGRATED,
    SOURCE,
    Downloads,
    TrackerClient,
    TrackerError,
    environment_report,
    load_config,
    redact,
)
from hca_tracker_client import list_atlases as _list_atlases
from hca_tracker_client import list_files as _list_files


def _safe(func: Callable[..., dict]) -> Callable[..., dict]:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> dict:
        try:
            return func(*args, **kwargs)
        except TrackerError as error:
            return {"error": str(error)}
        except Exception as error:  # an unexpected failure must not leak a URL or the token
            token = None
            with contextlib.suppress(TrackerError):
                token = load_config().api_token
            return {"error": redact(f"{type(error).__name__}: {error}", token)}

    return wrapper


def _tracker() -> TrackerClient:
    return TrackerClient(*load_config().require_tracker())


@_safe
def list_atlases() -> dict:
    """List every atlas version in the HCA Atlas Tracker.

    Use this to find the ``network`` and ``atlas`` pair every other tool
    needs. The same atlas slug can exist in more than one network.

    Returns:
        Dict with ``atlases``: one entry per version, with ``network``,
        ``atlas`` (the slug), ``version`` (e.g. ``v2.1``), ``generation``,
        ``revision``, ``is_latest`` (newest revision of its generation) and
        ``published``.
    """
    return {"atlases": _list_atlases(_tracker())}


@_safe
def list_integrated_objects(network: str, atlas: str, generation: int | None = None, published: bool = False) -> dict:
    """List the integrated objects of an atlas version.

    Args:
        network: Bionetwork, e.g. ``lung`` (from list_atlases).
        atlas: Atlas slug, e.g. ``adipose`` (from list_atlases).
        generation: Atlas generation (1 for v1.x). Default: the highest.
            The newest revision of the generation is used.
        published: Only consider published versions.

    Returns:
        Dict with ``network``, ``atlas``, ``version``, ``published`` and
        ``files``: each with ``name``, ``size_bytes``, ``size``, ``file_id``
        and ``integrity_status``.
    """
    return _list_files(_tracker(), network, atlas, INTEGRATED, generation, published)


@_safe
def list_source_datasets(network: str, atlas: str, generation: int | None = None, published: bool = False) -> dict:
    """List the source datasets of an atlas version.

    Args:
        network: Bionetwork, e.g. ``lung`` (from list_atlases).
        atlas: Atlas slug, e.g. ``adipose`` (from list_atlases).
        generation: Atlas generation (1 for v1.x). Default: the highest.
            The newest revision of the generation is used.
        published: Only consider published versions.

    Returns:
        Dict with ``network``, ``atlas``, ``version``, ``published`` and
        ``files``: each with ``name``, ``size_bytes``, ``size``, ``file_id``
        and ``integrity_status``.
    """
    return _list_files(_tracker(), network, atlas, SOURCE, generation, published)


@_safe
def start_download(
    network: str,
    atlas: str,
    file: str,
    generation: int | None = None,
    published: bool = False,
    dest_dir: str | None = None,
    confirm: bool = False,
    restart: bool = False,
) -> dict:
    """Start downloading one file of an atlas version in the background.

    Runs every check first (aria2c installed, folder writable, enough free
    space, not already downloaded, download link works), then returns at once
    with ``job_id``, ``path`` and ``size``; follow it with download_status. The
    download continues if this server or the session ends. Files are verified
    against their SHA-256 when one is available, and only get their final
    name once verified. If the file is already downloaded and verified, returns
    ``cached: true`` and its path without downloading. Calling this again for a
    stopped, cancelled or expired-link download resumes it.

    Args:
        network: Bionetwork (from list_atlases).
        atlas: Atlas slug (from list_atlases).
        file: The file's name or file_id (from list_integrated_objects or
            list_source_datasets).
        generation: Atlas generation. Default: the highest.
        published: Only consider published versions.
        dest_dir: Folder to save to instead of the cache.
        confirm: Required for files above the size threshold (default 5 GB).
            Without it, a large file returns ``needs_confirmation`` with its
            size, the free space and an estimated time instead of starting.
        restart: Delete a partial or failed download of this file and start
            from scratch (needed after a checksum mismatch).

    Returns:
        Dict with ``job_id``, ``state``, ``path``, ``size``, ``verification``
        and ``warnings`` (e.g. the tracker's integrity status is not valid).
    """
    return Downloads(load_config()).start(network, atlas, file, generation, published, dest_dir, confirm, restart)


@_safe
def download_status(job_id: str | None = None) -> dict:
    """Report a download's state and progress, or every download's.

    States: queued, downloading, verifying, done, failed, cancelled,
    interrupted. Works across sessions: a new server reports downloads an
    earlier one started.

    Args:
        job_id: The job to report. Omit to list all jobs, newest first.

    Returns:
        Dict with ``job_id``, ``state``, ``path``, ``size`` and, while
        running, ``progress`` (bytes done and total, percent, rate and time
        left; while verifying, bytes verified). Failed jobs carry a
        ``message`` saying what to do next. Without ``job_id``, ``jobs``.
    """
    return Downloads(load_config()).status(job_id)


@_safe
def cancel_download(job_id: str) -> dict:
    """Cancel a queued or running download.

    The partial file is kept: start_download resumes it, delete_download
    removes it.
    """
    return Downloads(load_config()).cancel(job_id)


@_safe
def list_downloads() -> dict:
    """List downloaded and partial files, with their state and size on disk."""
    return Downloads(load_config()).list_files()


@_safe
def delete_download(path: str) -> dict:
    """Delete a downloaded or partial file, with aria2's control file and its job records.

    Only files in the download cache, or in a folder a download was saved to,
    can be deleted; a running download must be cancelled first.

    Args:
        path: The file's path (its final name or its ``.part`` name).
    """
    return Downloads(load_config()).delete(path)


@_safe
def check_environment() -> dict:
    """Check what downloads need: aria2c (path and version), the aria2 daemon,
    the cache folder (writable, free space), and whether the tracker is
    reachable and the API token valid."""
    return environment_report(load_config())
