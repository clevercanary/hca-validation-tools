"""Introspection helpers for extracting uns and obs field metadata from Pydantic models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .core import (
    AdiposeDataset,
    AdiposeSample,
    Cell,
    Dataset,
    Donor,
    GutDataset,
    GutSample,
    MusculoskeletalDataset,
    Sample,
)

_BIONETWORK_CLASSES = [AdiposeDataset, GutDataset, MusculoskeletalDataset]

# Every class contributing obs-located fields. Unlike uns — which lives
# entirely on Dataset — obs fields are spread across the entity classes:
# Dataset carries the per-library sequencing fields, Donor and Sample the
# per-donor and per-sample ones. Bionetwork subclasses are included because
# a field one of them marks required is still required for files in that
# bionetwork.
_OBS_CLASSES = [Dataset, Donor, Sample, Cell, AdiposeSample, GutSample, *_BIONETWORK_CLASSES]

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


def build_obs_column_tiers() -> tuple[frozenset[str], frozenset[str]]:
    """Collect obs column names the HCA schema names, split by requiredness.

    Returns ``(required, optional)`` as a union across every class in
    ``_OBS_CLASSES``. Consumers get the two tiers separately rather than one
    combined set so they can say *which* tier a column offended — see
    :func:`~hca_anndata_tools.drop.drop_obs_columns`, whose guard refuses both
    but reports them apart.

    Deliberately does not track which entity owns a column. The question these
    sets answer is "does the schema name this?", and for that the union across
    entities is the right granularity.

    Note this is not the same question the coverage machinery in
    ``shared/schema_utils`` answers: ``iter_coverage_slots`` excludes identifier
    and foreign-key slots, which would drop ``donor_id`` and ``sample_id`` —
    exactly the columns a delete guard most needs to protect.
    """
    required: set[str] = set()
    optional: set[str] = set()
    for cls in _OBS_CLASSES:
        for name, fi in cls.model_fields.items():
            if _get_ann_data_location(fi) != "obs":
                continue
            (required if fi.is_required() else optional).add(name)
    # A column required by any entity is required, even if another class
    # declares it optional — the stricter tier wins.
    return frozenset(required), frozenset(optional - required)


# Cached at module level — schema is static
_OBS_TIERS: tuple[frozenset[str], frozenset[str]] | None = None


def obs_column_tiers() -> tuple[frozenset[str], frozenset[str]]:
    """Return the cached ``(required, optional)`` obs column tiers."""
    global _OBS_TIERS
    if _OBS_TIERS is None:
        _OBS_TIERS = build_obs_column_tiers()
    return _OBS_TIERS
