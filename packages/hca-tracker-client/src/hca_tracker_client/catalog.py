"""Listing atlases and the files linked to an atlas version."""

from .api import TrackerClient
from .checks import human_size
from .selection import atlas_version, select_atlas

INTEGRATED = "integrated"
SOURCE = "source"


def list_atlases(tracker: TrackerClient) -> list[dict]:
    """Every atlas version, sorted by network, atlas and version."""
    rows = [
        {
            "network": a.get("bioNetwork"),
            "atlas": a.get("shortNameSlug"),
            "version": atlas_version(a),
            "generation": a["generation"],
            "revision": a["revision"],
            "is_latest": bool(a.get("isLatest")),
            "published": bool(a.get("publishedAt")),
        }
        for a in tracker.list_atlases()
        if a.get("shortNameSlug")
    ]
    return sorted(rows, key=lambda r: (r["network"] or "", r["atlas"], r["generation"], r["revision"]))


def list_files(
    tracker: TrackerClient,
    network: str,
    atlas: str,
    kind: str,
    generation: int | None = None,
    published: bool = False,
) -> dict:
    """The integrated objects (``kind="integrated"``) or source datasets of one atlas version."""
    version = select_atlas(tracker.list_atlases(), network, atlas, generation, published)
    entries = tracker.component_atlases(version["id"]) if kind == INTEGRATED else tracker.source_datasets(version["id"])
    files = [
        {
            "name": f.get("fileName"),
            "size_bytes": int(f.get("sizeBytes") or 0),
            "size": human_size(int(f.get("sizeBytes") or 0)),
            "file_id": f["fileId"],
            "integrity_status": f.get("integrityStatus"),
        }
        for f in entries
        if f.get("fileId")
    ]
    return {
        "network": network,
        "atlas": atlas,
        "version": atlas_version(version),
        "published": bool(version.get("publishedAt")),
        "files": files,
    }
