"""Choosing an atlas version, and a file within it.

Every atlas-scoped call names both the network and the atlas slug. Nothing is
inferred: a slug can exist in several networks (``adipose`` is in both
``adipose`` and ``lung`` on dev), and a call that works today must not become
ambiguous when another network adds the same slug.
"""

from .errors import SelectionError

INTEGRATED = "integrated"
SOURCE = "source"
# How each kind of file is named in messages and results.
KIND_LABELS = {INTEGRATED: "integrated object", SOURCE: "source dataset"}


def atlas_version(atlas: dict) -> str:
    """The display version of an atlas, e.g. ``v1.2``."""
    return f"v{atlas['generation']}.{atlas['revision']}"


def atlas_label(network: str, atlas: str, version: str) -> str:
    """How messages name an atlas version, e.g. ``lung/adipose v1.2``."""
    return f"{network}/{atlas} {version}"


def _pairs(atlases: list[dict]) -> list[str]:
    return sorted({f"{a.get('bioNetwork')}/{a.get('shortNameSlug')}" for a in atlases if a.get("shortNameSlug")})


def select_atlas(
    atlases: list[dict],
    network: str | None,
    atlas: str | None,
    generation: int | None = None,
    published: bool = False,
) -> dict:
    """Pick one atlas version.

    The tracker's ``isLatest`` marks the newest revision within each
    generation, so selection uses ``(generation, revision)`` directly: with
    ``generation`` it is that generation's newest revision, without it the
    newest revision of the highest generation. ``published`` first narrows to
    versions with ``publishedAt`` set.
    """
    if not network or not atlas:
        missing = " and ".join(name for name, value in (("network", network), ("atlas", atlas)) if not value)
        raise SelectionError(f"{missing} must be given; use list_atlases to find the network/atlas pair")

    versions = [a for a in atlases if a.get("bioNetwork") == network and a.get("shortNameSlug") == atlas]
    if not versions:
        raise SelectionError(f"No atlas {network}/{atlas}. Valid network/atlas pairs: {', '.join(_pairs(atlases))}")

    if generation is not None:
        generations = sorted({a["generation"] for a in versions})
        versions = [a for a in versions if a["generation"] == generation]
        if not versions:
            raise SelectionError(
                f"Atlas {network}/{atlas} has no generation {generation} "
                f"(generations: {', '.join(str(g) for g in generations)})"
            )

    if published:
        versions = [a for a in versions if a.get("publishedAt")]
        if not versions:
            scope = f" in generation {generation}" if generation is not None else ""
            raise SelectionError(f"Atlas {network}/{atlas} has no published version{scope}")

    return max(versions, key=lambda a: (a["generation"], a["revision"]))


def _kind_label(entry: dict) -> str:
    kind = entry.get("kind") or "file"
    return KIND_LABELS.get(kind, kind)


def find_file(files: list[dict], file: str, label: str) -> dict:
    """Find a file by its exact ``fileName`` or its ``fileId``.

    ``label`` names the atlas version in error messages.
    """
    if not file:
        raise SelectionError("file must be given; use list_integrated_objects or list_source_datasets")
    matches = [f for f in files if f.get("fileId") and file in (f.get("fileName"), f.get("fileId"))]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        options = ", ".join(f"{f['fileId']} ({_kind_label(f)})" for f in matches)
        raise SelectionError(f"Several files in {label} match {file!r}: {options}. Pass one of these file_ids instead")
    names = sorted(str(f.get("fileName") or f["fileId"]) for f in files if f.get("fileId"))
    raise SelectionError(f"No file {file!r} in {label}. Files: {', '.join(names) or '(none)'}")
