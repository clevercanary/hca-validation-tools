"""Compute the per-file `metadata_coverage` payload reported by the dataset validator.

Driven by the LinkML schema in `shared/src/hca_validation/schema/`. For each
LinkML class eligible for coverage reporting (currently Donor, Sample, Dataset),
the module enumerates non-identifier, non-FK, non-deprecated slots that carry
an `annDataLocation` annotation and buckets each entity instance into one of:

  - complete         — value present and self-consistent across the entity's rows
  - issues.missing   — at least one row missing the value (and not inconsistent)
  - issues.inconsistent — multiple distinct non-null values within the entity

Identifier slots (e.g. `donor_id`, `sample_id`) are reported at a synthetic
`obs` entity class with denominator equal to total cell rows, so cells missing
their parent identifier surface exactly once without inflating entity-grain
counts.

Invariant: for every emitted entry,
  complete + sum(issues.values()) == entities[entity_class].record_count.
"""

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from linkml_runtime import SchemaView

from hca_validation.schema_utils import (
    coverage_classes,
    get_class_entity_type,
    get_class_identifier_name,
    get_slot_anndata_location,
    iter_coverage_slots,
)


SCHEMA_NAME = "tier_1"


def compute_metadata_coverage(adata: Any, schemaview: SchemaView) -> Dict[str, Any]:
    """Build the `metadata_coverage` payload for one AnnData file.

    Parameters
    ----------
    adata
        AnnData object opened for read. Only `adata.obs` (in-memory DataFrame
        even in backed mode) and `adata.uns` (dict-like) are accessed.
    schemaview
        LinkML SchemaView for the HCA core schema.
    """
    # Normalize empty / whitespace-only strings to NA. h5ad uploaders sometimes
    # use "" as a missing-value sentinel — without this, "" would inflate
    # entity record_counts (every "" cell becomes a phantom donor) and inflate
    # `complete` counts on entity-property slots.
    obs: pd.DataFrame = adata.obs.replace(r"^\s*$", pd.NA, regex=True)
    uns = adata.uns

    entities: Dict[str, Dict[str, int]] = {"obs": {"record_count": int(len(obs))}}
    field_coverage: List[Dict[str, Any]] = []

    for class_name in coverage_classes(schemaview):
        entity_class = get_class_entity_type(class_name)
        identifier = _identifier_for_class(schemaview, class_name)
        identifier_name = identifier.name if identifier is not None else None
        record_count = _entity_record_count(entity_class, identifier, obs)
        entities[entity_class] = {"record_count": record_count}

        # Emit the obs-grain identifier entry for any identifier the schema places
        # in obs, regardless of whether the column is present. A missing column is
        # the canonical "identifier not populated anywhere" signal and must not be
        # silently dropped — otherwise downstream can't distinguish it from drift.
        if (
            identifier is not None
            and get_slot_anndata_location(identifier) == "obs"
            and identifier_name is not None
        ):
            field_coverage.append(_obs_identifier_entry(identifier_name, obs))

        # Bucket all obs-grain entity-property slots in one vectorized pass per class.
        if record_count and identifier_name is not None and identifier_name in obs.columns:
            grouped = obs.groupby(identifier_name, dropna=True, observed=True)
        else:
            grouped = None

        for slot_name, location in iter_coverage_slots(schemaview, class_name):
            if location == "uns":
                field_coverage.append(_uns_entry(entity_class, slot_name, uns))
            elif location == "obs":
                field_coverage.append(_obs_entry(
                    entity_class=entity_class,
                    slot_name=slot_name,
                    obs=obs,
                    grouped=grouped,
                    record_count=record_count,
                ))

    _assert_invariant(entities, field_coverage)

    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": schemaview.schema.version,
        "entities": entities,
        "field_coverage": field_coverage,
    }


def _entry(entity_class: str, field: str, complete: int, *, missing: int = 0, inconsistent: int = 0) -> Dict[str, Any]:
    issues: Dict[str, int] = {}
    if inconsistent:
        issues["inconsistent"] = inconsistent
    if missing:
        issues["missing"] = missing
    return {
        "entity_class": entity_class,
        "field": field,
        "complete": complete,
        "issues": issues,
    }


def _identifier_for_class(schemaview: SchemaView, class_name: str):
    try:
        ident_name = get_class_identifier_name(schemaview, class_name)
    except ValueError:
        return None
    return schemaview.induced_slot(ident_name, class_name)


def _entity_record_count(
    entity_class: str,
    identifier,
    obs: pd.DataFrame,
) -> int:
    if entity_class == "dataset":
        return 1
    if identifier is None or get_slot_anndata_location(identifier) != "obs":
        return 0
    if identifier.name not in obs.columns:
        return 0
    return int(obs[identifier.name].dropna().nunique())


def _obs_identifier_entry(slot_name: str, obs: pd.DataFrame) -> Dict[str, Any]:
    if slot_name not in obs.columns:
        return _entry("obs", slot_name, complete=0, missing=len(obs))
    complete = int(obs[slot_name].notna().sum())
    return _entry("obs", slot_name, complete, missing=len(obs) - complete)


def _uns_entry(entity_class: str, slot_name: str, uns: Any) -> Dict[str, Any]:
    value = uns.get(slot_name)
    complete = 1 if _is_value_populated(value) else 0
    return _entry(entity_class, slot_name, complete, missing=1 - complete)


def _obs_entry(
    *,
    entity_class: str,
    slot_name: str,
    obs: pd.DataFrame,
    grouped: Optional[Any],
    record_count: int,
) -> Dict[str, Any]:
    # Always emit an entry. Skipping any (entity_class, slot) looks like schema
    # drift to the tracker; emit `complete=0, missing=record_count` so the
    # invariant holds (when record_count is 0, both sides are 0).
    if slot_name not in obs.columns:
        return _entry(entity_class, slot_name, complete=0, missing=record_count)

    if entity_class == "dataset":
        complete, inconsistent, missing = _bucket_single_group(obs[slot_name])
    elif grouped is None:
        # Identifier column missing → record_count == 0; emit 0/0.
        return _entry(entity_class, slot_name, complete=0, missing=record_count)
    else:
        complete, inconsistent, missing = _bucket_groups(grouped, slot_name)

    return _entry(
        entity_class,
        slot_name,
        complete,
        missing=missing,
        inconsistent=inconsistent,
    )


def _bucket_single_group(series: pd.Series) -> Tuple[int, int, int]:
    """Bucket a Dataset-class obs slot. The whole obs table is one entity."""
    non_null = series.dropna()
    if non_null.empty:
        return 0, 0, 1
    distinct = non_null.nunique()
    if distinct > 1:
        return 0, 1, 0
    if non_null.size < series.size:
        return 0, 0, 1
    return 1, 0, 0


def _bucket_groups(grouped: Any, slot_name: str) -> Tuple[int, int, int]:
    """Bucket entity instances using a pre-built groupby on the identifier.

    Vectorized via `.agg(['size', 'count', 'nunique'])`:
      - size:    rows in the group
      - count:   non-null rows
      - nunique: distinct non-null values
    A group is `inconsistent` if nunique > 1, `missing` if it has any null rows
    and is not inconsistent, else `complete`.

    Precedence: inconsistent > missing > complete (consistent with the reserved
    full precedence `invalid_value > inconsistent > missing` once invalid_value
    lands).
    """
    agg = grouped[slot_name].agg(["size", "count", "nunique"])
    inconsistent_mask = agg["nunique"] > 1
    missing_mask = (~inconsistent_mask) & (agg["count"] < agg["size"])
    inconsistent = int(inconsistent_mask.sum())
    missing = int(missing_mask.sum())
    complete = int(len(agg) - inconsistent - missing)
    return complete, inconsistent, missing


def _is_value_populated(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and value.strip() == "":
        return False
    try:
        if hasattr(value, "__len__") and len(value) == 0:
            return False
    except TypeError:
        pass
    return True


def _assert_invariant(
    entities: Dict[str, Dict[str, int]],
    field_coverage: List[Dict[str, Any]],
) -> None:
    for entry in field_coverage:
        entity_class = entry["entity_class"]
        expected = entities[entity_class]["record_count"]
        actual = entry["complete"] + sum(entry["issues"].values())
        if actual != expected:
            # RuntimeError (not AssertionError) so `python -O` can't strip the check.
            raise RuntimeError(
                "metadata_coverage invariant violated for "
                f"({entity_class}, {entry['field']}): "
                f"complete + issues = {actual}, expected {expected}"
            )
