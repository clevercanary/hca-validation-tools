"""MCP wrappers over hca_tracker_client. Config is loaded per call, so a changed token applies at once."""

import contextlib
import functools
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

import anyio
from pydantic import Field

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


def _call(func: Callable[..., dict], *args: Any, **kwargs: Any) -> dict:
    try:
        return func(*args, **kwargs)
    except TrackerError as error:
        return {"error": str(error)}
    except Exception as error:  # an unexpected failure must not leak a URL or the token
        token = None
        with contextlib.suppress(Exception):
            token = load_config().api_token
        return {"error": redact(f"{type(error).__name__}: {error}", token)}


def _tool(func: Callable[..., dict]) -> Callable[..., Awaitable[dict]]:
    """Run a tool body in a worker thread (FastMCP runs a plain ``def`` on its event loop), errors as dicts."""

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> dict:
        return await anyio.to_thread.run_sync(functools.partial(_call, func, *args, **kwargs))

    return wrapper


def _tracker() -> TrackerClient:
    return load_config().tracker_client()


# Parameter descriptions are published in each tool's input schema.
Network = Annotated[str, Field(description="Bionetwork, e.g. 'lung'. Take it from list_atlases; never guess.")]
Atlas = Annotated[
    str, Field(description="Atlas slug (shortNameSlug), e.g. 'adipose'. The same slug can exist in several networks.")
]
Generation = Annotated[
    int | None,
    Field(description="Atlas generation (1 = v1.x). Its newest revision is used. Default: the highest generation."),
]
Published = Annotated[bool, Field(description="Only consider published atlas versions.")]
JobId = Annotated[str, Field(description="job_id returned by start_download.")]


@_tool
def list_atlases() -> dict:
    """List every atlas version (network, atlas slug, version, is_latest, published) to find a network/atlas pair."""
    return {"atlases": _list_atlases(_tracker())}


@_tool
def list_integrated_objects(
    network: Network, atlas: Atlas, generation: Generation = None, published: Published = False
) -> dict:
    """List an atlas version's integrated objects: name, size, file_id, integrity_status."""
    return _list_files(_tracker(), network, atlas, INTEGRATED, generation, published)


@_tool
def list_source_datasets(
    network: Network, atlas: Atlas, generation: Generation = None, published: Published = False
) -> dict:
    """List an atlas version's source datasets: name, size, file_id, integrity_status."""
    return _list_files(_tracker(), network, atlas, SOURCE, generation, published)


@_tool
def start_download(
    network: Network,
    atlas: Atlas,
    file: Annotated[str, Field(description="File name or file_id, from list_integrated_objects/list_source_datasets.")],
    generation: Generation = None,
    published: Published = False,
    dest_dir: Annotated[str | None, Field(description="Folder to save to instead of the cache.")] = None,
    restart: Annotated[
        bool, Field(description="Discard a partial or checksum-failed download of this file and start over.")
    ] = False,
) -> dict:
    """Check, then download one file in the background; returns job_id, path and size at once.

    Checks run first (aria2c, writable folder, free space, working link, source
    checksum: a file without one is refused). Every file is SHA-256 verified,
    and the download continues after this session ends. A verified copy returns ``cached: true``; calling
    again resumes a stopped download.
    """
    return Downloads(load_config()).start(network, atlas, file, generation, published, dest_dir, restart)


@_tool
def download_status(job_id: Annotated[str | None, Field(description="Omit to list every job.")] = None) -> dict:
    """State (queued, downloading, verifying, done, failed, cancelled, interrupted) and progress of one job, or all."""
    return Downloads(load_config()).status(job_id)


@_tool
def cancel_download(job_id: JobId) -> dict:
    """Cancel a queued or running download, keeping the partial file for start_download to resume."""
    return Downloads(load_config()).cancel(job_id)


@_tool
def list_downloads() -> dict:
    """List downloaded and partial files, with their state and size on disk."""
    return Downloads(load_config()).list_files()


@_tool
def delete_download(
    path: Annotated[str, Field(description="The file's final path or its .part path, as shown by list_downloads.")],
) -> dict:
    """Delete a downloaded or partial file and its job records: files in the cache, or exactly a job's own file."""
    return Downloads(load_config()).delete(path)


@_tool
def check_environment() -> dict:
    """Check aria2c, the aria2 daemon, the cache folder and free space, the tracker, and the token."""
    return environment_report(load_config())
