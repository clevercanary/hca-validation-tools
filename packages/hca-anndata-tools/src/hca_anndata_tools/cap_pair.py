"""The checks ``copy_cap_annotations`` makes before it writes, as readers and pure checks (#749).

Each check returns the copy's refusal message, or None. The copy runs them in
its order and refuses on the first failure; ``compare_cap_export`` runs them all.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import h5py
from anndata.io import read_elem

from ._io import obs_index_name, read_index, read_provenance, read_uns
from .cap import (
    _ALL_CAP_SUFFIXES,
    CAP_METADATA_KEY,
    LEGACY_LAYOUT_DESCRIPTION,
    LEGACY_LAYOUT_ERROR,
    cap_obs_columns,
    cap_palette_keys,
    is_legacy_cap_layout,
)
from .guards import require_obs_group
from .strip_cap import _LEGACY_TOP_LEVEL_PROVENANCE
from .write import MissingLineageRootError, generate_output_path, parse_edit_log

# Demographic annotation sets — not real CAP annotations, just renamed CXG columns
SKIP_SETS = frozenset({"sex", "development_stage", "self_reported_ethnicity"})

# Maximum percent (0-100) of cells on either side that may be absent from the
# other. Applied to both `missing_from_hca.pct` and `missing_from_cap.pct`.
MAX_MISSING_PCT = 5.0

SAME_FILE_ERROR = "Source and target are the same file"


@dataclass(frozen=True)
class SourceCap:
    """The export's CAP uns: deprecated top-level keys, and the nested block when it is a group."""

    legacy: bool
    present: bool
    block: dict[str, Any] | None


@dataclass(frozen=True)
class TargetCap:
    """The target's CAP material from any era, mirroring strip_cap_annotations' inventory."""

    legacy: bool
    obs_columns: tuple[str, ...]
    uns_keys: tuple[str, ...]


def same_file_failure(source_path: str, target_path: str) -> str | None:
    source, target = Path(source_path), Path(target_path)
    return SAME_FILE_ERROR if source.exists() and target.exists() and source.samefile(target) else None


def read_source_cap(f: h5py.File) -> SourceCap:
    uns = read_uns(f)
    present = uns is not None and CAP_METADATA_KEY in uns
    block = read_elem(uns[CAP_METADATA_KEY]) if uns is not None and present else None
    return SourceCap(is_legacy_cap_layout(uns), present, dict(block) if isinstance(block, Mapping) else None)


def read_target_cap(f: h5py.File, obs_columns: list[str]) -> TargetCap:
    uns = read_uns(f)
    uns_keys = set(uns.keys()) if uns is not None else set()
    keys = [k for k in (CAP_METADATA_KEY, *_LEGACY_TOP_LEVEL_PROVENANCE) if k in uns_keys]
    prov = read_provenance(uns)
    if prov is not None and "cap" in prov:
        keys.append("provenance/cap")
    keys += cap_palette_keys(uns_keys)
    return TargetCap(is_legacy_cap_layout(uns), tuple(cap_obs_columns(obs_columns)), tuple(keys))


def read_ids(f: h5py.File, side: str) -> tuple[list[str], list[str]]:
    """The obs and var indexes; ``side`` ("CAP" or "HCA") names them in a refusal.

    Raises:
        GuardRefusal: the file has no modern obs group.
        Refusal: an index holds a missing value.
    """
    obs_group = require_obs_group(f)
    cells = list(read_index(obs_group, obs_index_name(obs_group), f"{side} cells"))
    var_group = f["var"]
    genes = list(read_index(var_group, obs_index_name(var_group), f"{side} genes"))
    return cells, genes


def annotation_sets(block: Mapping[str, Any]) -> list[str]:
    meta = block.get("cellannotation_metadata", {})
    if isinstance(meta, dict):
        return [s for s in meta if s not in SKIP_SETS]
    return []


def columns_to_copy(sets: list[str], source_obs_columns: list[str]) -> list[str]:
    return [f"{s}{x}" for s in sets for x in _ALL_CAP_SUFFIXES if f"{s}{x}" in source_obs_columns]


def source_layout_failure(cap: SourceCap) -> str | None:
    return LEGACY_LAYOUT_ERROR if cap.legacy else None


def source_block_failure(cap: SourceCap) -> str | None:
    if cap.block is not None:
        return None
    if cap.present:
        return "Source uns['cap_metadata'] is malformed (not a dict/group)."
    return "Source has no CAP metadata: uns['cap_metadata'] is missing."


def source_metadata_failure(block: Mapping[str, Any]) -> str | None:
    if "cellannotation_metadata" in block:
        return None
    return "Source has no cellannotation_metadata in uns['cap_metadata']"


def source_schema_version_failure(block: Mapping[str, Any]) -> str | None:
    if "cellannotation_schema_version" in block:
        return None
    return "Source has no cellannotation_schema_version in uns['cap_metadata']"


def annotation_sets_failure(sets: list[str]) -> str | None:
    return None if sets else "Source has no annotation sets in cellannotation_metadata"


def non_categorical_failure(obs_group: h5py.Group, columns: list[str]) -> str | None:
    for col in columns:
        item = obs_group[col]
        # CAP serializes all annotation columns as categorical. Enforce
        # that contract — non-categorical columns would either force a
        # dtype coercion on copy (schema drift) or break the writer on
        # the NaN rows that partial-overlap introduces.
        if not (isinstance(item, h5py.Group) and "categories" in item):
            return (
                f"CAP source column '{col}' is not categorical. "
                "CAP is expected to serialize all annotation columns "
                "as categorical; please report upstream."
            )
    return None


def columns_failure(columns: list[str]) -> str | None:
    return None if columns else "No CAP obs columns found to copy"


def target_layout_failure(target: TargetCap) -> str | None:
    # Refuse a target carrying deprecated top-level CAP (from older tooling)
    # rather than silently overwriting it into a mixed-layout file (issue #452).
    # Remediation is an explicit strip_cap_annotations run.
    if not target.legacy:
        return None
    return (
        f"Target uses {LEGACY_LAYOUT_DESCRIPTION}. Only the nested "
        "uns['cap_metadata'] layout is accepted; run "
        "strip_cap_annotations on the target before copying CAP into it."
    )


def existing_cap_failure(target: TargetCap) -> str | None:
    if not (target.obs_columns or target.uns_keys):
        return None
    return (
        f"Target already has CAP data ({len(target.obs_columns)} obs columns, {len(target.uns_keys)} uns keys). "
        "Use overwrite=True to replace."
    )


def edit_log_failure(raw_log: str) -> str | None:
    return parse_edit_log(raw_log).get("error")


def lineage_failure(target_path: str) -> str | None:
    """The refusal the copy's snapshot meets when ``target_path`` is an edit snapshot without its original."""
    try:
        generate_output_path(target_path)
    except MissingLineageRootError as e:
        return str(e)
    return None


def compute_axis_overlap(cap_ids: set[str], hca_ids: set[str]) -> dict:
    """Compare CAP and HCA ID sets along one axis (cells or genes).

    Percentages are 0-100, computed as a share of the side the missing IDs
    came from: `missing_from_hca.pct = 100 * missing_from_hca.n / n_cap`,
    and symmetrically for `missing_from_cap`. Rounded to one decimal place
    for readability — exact ratios can be recomputed from the integer
    counts if a consumer needs them.
    """
    n_cap = len(cap_ids)
    n_hca = len(hca_ids)
    n_matched = len(cap_ids & hca_ids)
    n_missing_from_hca = n_cap - n_matched
    n_missing_from_cap = n_hca - n_matched
    return {
        "n_cap": n_cap,
        "n_hca": n_hca,
        "n_matched": n_matched,
        "missing_from_hca": {
            "n": n_missing_from_hca,
            "pct": round(100.0 * n_missing_from_hca / n_cap, 1) if n_cap else 0.0,
        },
        "missing_from_cap": {
            "n": n_missing_from_cap,
            "pct": round(100.0 * n_missing_from_cap / n_hca, 1) if n_hca else 0.0,
        },
    }


def cell_overlap_failure(stats: dict) -> str | None:
    """The refusal when more than :data:`MAX_MISSING_PCT` of either side's cells are missing from the other."""
    # Compare on raw fractions, not the 1-dp-rounded `pct` in the stats —
    # otherwise 5.04% rounds to 5.0 and slips past the gate.
    n_cap, n_hca = stats["n_cap"], stats["n_hca"]
    from_hca = 100.0 * stats["missing_from_hca"]["n"] / n_cap if n_cap else 0.0
    from_cap = 100.0 * stats["missing_from_cap"]["n"] / n_hca if n_hca else 0.0
    if from_hca <= MAX_MISSING_PCT and from_cap <= MAX_MISSING_PCT:
        return None
    return (
        f"Cell ID mismatch over {MAX_MISSING_PCT:.0f}%: "
        f"CAP has {n_cap}, HCA has {n_hca}, "
        f"matched {stats['n_matched']} "
        f"({stats['missing_from_hca']['n']} missing from HCA "
        f"= {from_hca:.1f}% of CAP; "
        f"{stats['missing_from_cap']['n']} missing from CAP "
        f"= {from_cap:.1f}% of HCA)"
    )
