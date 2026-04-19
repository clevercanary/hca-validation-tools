"""Introspection helpers for extracting uns field metadata from Pydantic models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .core import AdiposeDataset, Dataset, GutDataset, MusculoskeletalDataset

_BIONETWORK_CLASSES = [AdiposeDataset, GutDataset, MusculoskeletalDataset]

# Fields that LinkML's Dataset model claims live in uns but that are not
# actually uns fields per HCA Tier 1 / CELLxGENE. See issue #343. Dropping
# them from the registry means list_uns_fields treats them as unrecognized:
# they don't appear in `fields` or `missing_required`, and set_uns rejects
# them as unknown. They *will* appear in `extra_uns_keys` if an existing
# file happens to carry one — that's intentional, since flagging an
# unexpected key is better than silently blessing it. Remove an entry here
# once the LinkML source is corrected upstream.
_SKIP_UNS_FIELDS: set[str] = {"description"}


@dataclass(frozen=True)
class UnsFieldInfo:
    """Metadata about a single HCA uns field."""

    name: str
    annotation: Any
    required: bool
    title: str
    description: str
    bionetwork_only: bool
    examples: list[dict] = field(default_factory=list)


def _get_linkml_meta(field_info) -> dict | None:
    """Extract the linkml_meta dict from a Pydantic FieldInfo's json_schema_extra."""
    extra = getattr(field_info, "json_schema_extra", None)
    if not extra or not isinstance(extra, dict):
        return None
    meta = extra.get("linkml_meta")
    if not meta or not isinstance(meta, dict):
        return None
    return meta


def _get_ann_data_location(field_info) -> str | None:
    """Extract annDataLocation from a Pydantic FieldInfo."""
    meta = _get_linkml_meta(field_info)
    if meta is None:
        return None
    annotations = meta.get("annotations")
    if not annotations or not isinstance(annotations, dict):
        return None
    location = annotations.get("annDataLocation")
    if not location or not isinstance(location, dict):
        return None
    return location.get("value")


def _get_examples(field_info) -> list[dict]:
    """Extract examples from linkml_meta if present."""
    meta = _get_linkml_meta(field_info)
    if meta is None:
        return []
    return meta.get("examples", [])


def get_uns_field_registry() -> dict[str, UnsFieldInfo]:
    """Build a registry of all HCA uns fields from the schema models.

    Collects from base Dataset and all bionetwork subclasses.
    Fields only present on subclasses are marked bionetwork_only=True.
    """
    registry: dict[str, UnsFieldInfo] = {}

    # Base Dataset fields
    for name, fi in Dataset.model_fields.items():
        if name in _SKIP_UNS_FIELDS:
            continue
        if _get_ann_data_location(fi) == "uns":
            registry[name] = UnsFieldInfo(
                name=name,
                annotation=fi.annotation,
                required=fi.is_required(),
                title=fi.title or name,
                description=fi.description or "",
                bionetwork_only=False,
                examples=_get_examples(fi),
            )

    # Bionetwork subclass fields (only add new ones not in base)
    for cls in _BIONETWORK_CLASSES:
        for name, fi in cls.model_fields.items():
            if name in registry or name in _SKIP_UNS_FIELDS:
                continue
            if _get_ann_data_location(fi) == "uns":
                registry[name] = UnsFieldInfo(
                    name=name,
                    annotation=fi.annotation,
                    required=fi.is_required(),
                    title=fi.title or name,
                    description=fi.description or "",
                    bionetwork_only=True,
                    examples=_get_examples(fi),
                )

    return registry


# Cached at module level — schema is static
_UNS_REGISTRY: dict[str, UnsFieldInfo] | None = None


def uns_field_registry() -> dict[str, UnsFieldInfo]:
    """Return the cached uns field registry."""
    global _UNS_REGISTRY
    if _UNS_REGISTRY is None:
        _UNS_REGISTRY = get_uns_field_registry()
    return _UNS_REGISTRY
