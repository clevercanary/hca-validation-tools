"""MCP wrappers over hca_tracker_client. Config is loaded per call, so a changed token applies at once."""

import contextlib
import functools
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

import anyio
from pydantic import Field

from hca_tracker_client import (
    INTEGRATED,
    MAX_MESSAGES,
    SOURCE,
    Downloads,
    TrackerClient,
    TrackerError,
    environment_report,
    load_config,
    redact,
)
from hca_tracker_client import get_atlas as _get_atlas
from hca_tracker_client import list_atlases as _list_atlases
from hca_tracker_client import list_files as _list_files
from hca_tracker_client import validation_report as _validation_report


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
File = Annotated[str, Field(description="File name or file_id, from list_integrated_objects/list_source_datasets.")]


@_tool
def list_atlases() -> dict:
    """List every atlas version (network, atlas slug, version, is_latest, published) to find a network/atlas pair."""
    return {"atlases": _list_atlases(_tracker())}


@_tool
def list_integrated_objects(
    network: Network, atlas: Atlas, generation: Generation = None, published: Published = False
) -> dict:
    """List an atlas version's integrated objects with their validation summary and CAP / Tier 1 status.

    Per file: name, size_bytes, size, file_id, integrity_status, entry_id and kind (what get_validation_report
    takes), title,
    cell_count, revision, wip_number, uploaded_at, is_archived, cap_url, validation_status,
    validation_error_message, validation (overall_valid and, per validator cap / cellxgene / hca_schema /
    hca_cell_annotation, valid, error_count, warning_count; null when validation produced no result),
    tier1_status (VALID, INVALID, UNKNOWN) and cap_status (PUBLISHED, CAP_READY, CAP_VALIDATION_FAILED,
    NEEDS_VALIDATION, INFO_REQUIRED, NOT_REQUIRED). Use get_validation_report for the messages behind the counts.
    """
    return _list_files(_tracker(), network, atlas, INTEGRATED, generation, published)


@_tool
def list_source_datasets(
    network: Network, atlas: Atlas, generation: Generation = None, published: Published = False
) -> dict:
    """List an atlas version's source datasets with their validation summary and CAP / Tier 1 status.

    Per file: the same fields as list_integrated_objects, plus reprocessed_status, publication_status,
    source_study_title and integrated_objects (the integrated objects using it). Use get_validation_report
    for the messages behind the counts.
    """
    return _list_files(_tracker(), network, atlas, SOURCE, generation, published)


@_tool
def get_atlas(network: Network, atlas: Atlas, generation: Generation = None, published: Published = False) -> dict:
    """An atlas version's record: title, status (IN_PROGRESS, OC_ENDORSED), wave, target_completion,
    cap_project_url, integration_leads (name, email, tracker_account, last_login), counts of source studies,
    source datasets and integrated objects, ingestion_tasks (cap, cellxgene, hca_data_repository: count,
    completed), publications (doi, title).

    tracker_account is active, disabled, or unknown when no tracker user has the lead's contact email; people
    log in with a Google address that can differ from it, so unknown does not mean no account. last_login is
    null when unknown or when the user has never logged in.
    """
    return _get_atlas(_tracker(), network, atlas, generation, published)


@_tool
def get_validation_report(
    network: Network,
    atlas: Atlas,
    entry_id: Annotated[str, Field(description="entry_id from list_integrated_objects/list_source_datasets.")],
    kind: Annotated[Literal["integrated", "source"], Field(description="kind from the same list row.")],
    generation: Generation = None,
    published: Published = False,
    validator: Annotated[
        Literal["cap", "cellxgene", "hca_schema", "hca_cell_annotation"] | None,
        Field(description="Keep one validator's report only."),
    ] = None,
    max_messages: Annotated[
        int, Field(ge=1, description="Most errors and most warnings returned per validator; the counts stay complete.")
    ] = MAX_MESSAGES,
) -> dict:
    """The validators' error and warning messages for one file, by the entry_id and kind of its list row.

    Returns file, file_id, entry_id, kind, validation_status, validation_error_message, max_messages and
    reports. reports holds, per validator, valid, started_at, finished_at, error_count, warning_count,
    errors, warnings and truncated (true when a list was cut to max_messages; a file can carry tens of
    thousands of warnings). reports is null when validation_status is not completed, e.g. job_failed, where
    validation_error_message says why.
    """
    return _validation_report(
        _tracker(), network, atlas, entry_id, kind, generation, published, validator, max_messages
    )


@_tool
def start_download(
    network: Network,
    atlas: Atlas,
    file: File,
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
