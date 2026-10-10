"""Listing atlases and the files linked to an atlas version; an atlas's record; a file's validation report."""

import re
from datetime import datetime, timedelta, timezone

from .api import TrackerClient
from .checks import human_size
from .errors import SelectionError, TrackerError
from .selection import INTEGRATED, KIND_LABELS, SOURCE, atlas_label, atlas_version, select_atlas
from .status import VALIDATORS, cap_status, tier1_status

MAX_MESSAGES = 200
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

# Per kind, the TrackerClient methods for an atlas version's list and for one entry's detail.
_ROUTES = {
    INTEGRATED: ("component_atlases", "component_atlas"),
    SOURCE: ("source_datasets", "source_dataset"),
}


def _scope(version: dict, network: str | None, atlas: str) -> dict:
    """The keys every atlas-scoped result starts with."""
    return {
        "network": network,
        "atlas": atlas,
        "version": atlas_version(version),
        "published": bool(version.get("publishedAt")),
    }


def _version_row(version: dict, network: str | None, atlas: str) -> dict:
    return {
        **_scope(version, network, atlas),
        "generation": version["generation"],
        "revision": version["revision"],
        "is_latest": bool(version.get("isLatest")),
    }


def list_atlases(tracker: TrackerClient) -> list[dict]:
    """Every atlas version, sorted by network, atlas and version."""
    rows = [
        _version_row(a, a.get("bioNetwork"), a["shortNameSlug"])
        for a in tracker.list_atlases()
        if a.get("shortNameSlug")
    ]
    return sorted(rows, key=lambda r: (r["network"] or "", r["atlas"], r["generation"], r["revision"]))


def validation_summary(raw: dict | None) -> dict | None:
    """The tracker's ``validationSummary`` with the client's names: counts per validator, None for a validator
    that produced no result, and None altogether when validation never produced a summary."""
    if raw is None:
        return None
    validators = raw.get("validators") or {}
    summary = {}
    for key, name in VALIDATORS.items():
        result = validators.get(key)
        summary[name] = (
            None
            if result is None
            else {
                "valid": bool(result.get("valid")),
                "error_count": int(result.get("errorCount") or 0),
                "warning_count": int(result.get("warningCount") or 0),
            }
        )
    return {"overall_valid": bool(raw.get("overallValid")), "validators": summary}


def file_row(entry: dict, kind: str) -> dict:
    """One list row for an integrated object or source dataset, from the tracker's list entry.

    The first five keys are the original listing and stay as they are;
    ``start_download`` callers depend on them. ``entry_id`` and ``kind`` are
    what ``validation_report`` takes.
    """
    size = int(entry.get("sizeBytes") or 0)
    summary = entry.get("validationSummary")
    reprocessed = entry.get("reprocessedStatus")  # source datasets only
    row = {
        "name": entry.get("fileName"),
        "size_bytes": size,
        "size": human_size(size),
        "file_id": entry["fileId"],
        "integrity_status": entry.get("integrityStatus"),
        "entry_id": entry.get("id"),
        "kind": kind,
        "title": entry.get("title"),
        "cell_count": entry.get("cellCount"),
        "revision": entry.get("revision"),
        "wip_number": entry.get("wipNumber"),
        "uploaded_at": entry.get("fileEventTime"),
        "is_archived": bool(entry.get("isArchived")),
        "cap_url": entry.get("capUrl"),
        "validation_status": entry.get("validationStatus"),
        "validation_error_message": entry.get("validationErrorMessage"),
        "validation": validation_summary(summary),
        "tier1_status": tier1_status(summary),
        "cap_status": cap_status(summary, entry.get("capUrl"), reprocessed),
    }
    if kind == SOURCE:
        row.update(
            {
                "reprocessed_status": reprocessed,
                "publication_status": entry.get("publicationStatus"),
                "source_study_title": entry.get("sourceStudyTitle"),
                "integrated_objects": [c.get("name") for c in entry.get("componentAtlases") or []],
            }
        )
    return row


def list_files(
    tracker: TrackerClient,
    network: str,
    atlas: str,
    kind: str,
    generation: int | None = None,
    published: bool = False,
) -> dict:
    """The integrated objects (``kind="integrated"``) or source datasets of one atlas version."""
    if kind not in _ROUTES:
        raise ValueError(f"kind must be {INTEGRATED!r} or {SOURCE!r}, got {kind!r}")
    version = select_atlas(tracker.list_atlases(), network, atlas, generation, published)
    entries = getattr(tracker, _ROUTES[kind][0])(version["id"])
    files = [file_row(f, kind) for f in entries if f.get("fileId")]
    return {**_scope(version, network, atlas), "files": files}


def atlas_files(tracker: TrackerClient, atlas_id: str) -> list[dict]:
    """Both lists of an atlas version as the tracker serves them, each entry tagged with its ``kind``.

    The input ``find_file`` expects when the caller may not know which kind a
    file is.
    """
    return [
        {**f, "kind": kind} for kind, (list_route, _) in _ROUTES.items() for f in getattr(tracker, list_route)(atlas_id)
    ]


def _last_login(user: dict) -> str | None:
    """A user's ``lastLogin``, or None for the tracker's never-logged-in value.

    The tracker stores epoch 0 in a timestamp without time zone and serialises
    it in its server's zone, so the value can land a few hours either side of
    the epoch. Anything within a day of it means never: no real login
    predates the tracker.
    """
    value = user.get("lastLogin")
    if not value:
        return None
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        never = abs(instant - _EPOCH) < timedelta(days=1)
    except ValueError:
        never = False
    return None if never else value


def _lead(lead: dict, users: dict[str, dict]) -> dict:
    """A lead with their tracker account: ``active``, ``disabled``, or ``unknown`` when no user has the
    lead's email. Unknown is not evidence of a missing account: people log in with a Google address that
    can differ from the contact address the atlas lists. ``last_login`` is None when unknown or never."""
    user = users.get((lead.get("email") or "").lower())
    if user is None:
        account, last_login = "unknown", None
    else:
        account, last_login = ("disabled" if user.get("disabled") else "active"), _last_login(user)
    return {"name": lead.get("name"), "email": lead.get("email"), "tracker_account": account, "last_login": last_login}


def get_atlas(
    tracker: TrackerClient,
    network: str,
    atlas: str,
    generation: int | None = None,
    published: bool = False,
) -> dict:
    """One atlas version's record: status, leads with their tracker account, counts, tasks, publications.

    Leads are joined to ``/api/users`` (one call) on email; see ``_lead`` for
    what the join can and cannot say.
    """
    version = select_atlas(tracker.list_atlases(), network, atlas, generation, published)
    leads = version.get("integrationLead") or []
    users = {}
    if any(lead.get("email") for lead in leads):
        users = {u["email"].lower(): u for u in tracker.users() if u.get("email")}
    integration_leads = [_lead(lead, users) for lead in leads]
    tasks = version.get("ingestionTaskCounts") or {}
    return {
        **_version_row(version, network, atlas),
        "title": version.get("title"),
        "short_name": version.get("shortName"),
        "status": version.get("status"),
        "published_at": version.get("publishedAt"),
        "wave": version.get("wave"),
        "target_completion": version.get("targetCompletion"),
        "cap_project_url": version.get("capId"),
        "integration_leads": integration_leads,
        "counts": {
            "source_studies": version.get("sourceStudyCount"),
            "source_datasets": version.get("sourceDatasetCount"),
            "integrated_objects": version.get("componentAtlasCount"),
        },
        "ingestion_tasks": {
            system.lower(): {"count": counts.get("count"), "completed": counts.get("completedCount")}
            for system, counts in tasks.items()
        },
        "publications": [
            {"doi": p.get("doi"), "title": (p.get("publication") or {}).get("title")}
            for p in version.get("publications") or []
        ],
    }


def _report(raw: dict, max_messages: int) -> dict:
    errors = raw.get("errors") or []
    warnings = raw.get("warnings") or []
    return {
        "valid": bool(raw.get("valid")),
        "started_at": raw.get("startedAt"),
        "finished_at": raw.get("finishedAt"),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors[:max_messages],
        "warnings": warnings[:max_messages],
        "truncated": len(errors) > max_messages or len(warnings) > max_messages,
    }


def validation_report(
    tracker: TrackerClient,
    network: str,
    atlas: str,
    entry_id: str,
    kind: str,
    generation: int | None = None,
    published: bool = False,
    validator: str | None = None,
    max_messages: int = MAX_MESSAGES,
) -> dict:
    """The validators' message lists for one file, by the ``entry_id`` and ``kind`` its list row carries.

    Each validator's ``errors`` and ``warnings`` hold at most ``max_messages``
    entries; ``error_count`` and ``warning_count`` are the full counts and
    ``truncated`` says whether a list was cut. ``validator`` keeps one
    validator's report only. ``reports`` is None when validation never ran to
    completion (a ``job_failed`` file has ``validation_error_message`` instead).
    """
    if kind not in _ROUTES:
        raise ValueError(f"kind must be {INTEGRATED!r} or {SOURCE!r}, got {kind!r}")
    if max_messages < 1:
        raise ValueError(f"max_messages must be at least 1, got {max_messages}")
    names = list(VALIDATORS.values())
    if validator is not None and validator not in names:
        raise SelectionError(f"No validator {validator!r}; validators: {', '.join(names)}")
    if not _UUID.match(entry_id or ""):
        # The tracker answers 500, not 404, to a non-UUID id; a file name or file_id pasted here is the usual cause.
        raise SelectionError(
            f"entry_id must be the entry_id from list_integrated_objects or list_source_datasets, got {entry_id!r}"
        )
    version = select_atlas(tracker.list_atlases(), network, atlas, generation, published)
    try:
        detail = getattr(tracker, _ROUTES[kind][1])(version["id"], entry_id)
    except TrackerError as error:
        if error.status != 404:
            raise
        label = atlas_label(network, atlas, atlas_version(version))
        raise SelectionError(
            f"No {KIND_LABELS[kind]} {entry_id!r} in {label}; take entry_id and kind from "
            f"list_{'integrated_objects' if kind == INTEGRATED else 'source_datasets'}"
        ) from None
    raw_reports = detail.get("validationReports")
    reports = None
    if raw_reports is not None:
        reports = {
            name: (None if raw_reports.get(key) is None else _report(raw_reports[key], max_messages))
            for key, name in VALIDATORS.items()
            if validator is None or name == validator
        }
    return {
        **_scope(version, network, atlas),
        "file": detail.get("fileName"),
        "file_id": detail.get("fileId"),
        "entry_id": entry_id,
        "kind": kind,
        "validation_status": detail.get("validationStatus"),
        "validation_error_message": detail.get("validationErrorMessage"),
        "max_messages": max_messages,
        "reports": reports,
    }
