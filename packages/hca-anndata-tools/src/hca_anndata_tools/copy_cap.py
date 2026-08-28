"""Copy CAP cell annotations from a source h5ad into an HCA target h5ad."""

from __future__ import annotations

import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import anndata as ad
import h5py
import numpy as np
import pandas as pd

from ._io import (
    check_duplicate_ids,
    ensure_provenance_group,
    masked_categories_error,
    obs_index_name,
    open_h5ad,
    read_categorical_data,
    read_column_order,
    read_edit_log_h5py,
    read_index,
    read_provenance,
    read_uns,
    update_column_order,
    verify_obs_transplant,
)
from ._serialize import make_serializable
from .cap import (
    _OPTIONAL_SUFFIXES,
    _REQUIRED_SUFFIXES,
    CAP_METADATA_KEY,
    LEGACY_LAYOUT_ERROR,
    cap_obs_columns,
    cap_palette_keys,
    is_legacy_cap_layout,
    resolve_cap_block,
)
from .guards import require_obs_group
from .marker_genes import validate_marker_genes
from .strip_cap import _LEGACY_TOP_LEVEL_PROVENANCE, strip_cap_annotations
from .write import (
    EDIT_LOG_KEY,
    _compute_sha256,
    build_edit_log,
    cleanup_previous_version,
    make_edit_entry,
    parse_edit_log,
    resolve_latest,
    snapshot_copy_hashed,
)

# Demographic annotation sets — not real CAP annotations, just renamed CXG columns
_SKIP_SETS = {"sex", "development_stage", "self_reported_ethnicity"}

# The entire CAP block is written into uns['cap_metadata'] (issue #452);
# replaced wholesale on overwrite.
_OVERWRITE_UNS_KEYS = {CAP_METADATA_KEY}

# Maximum percent (0-100) of cells on either side that may be absent from the
# other. Applied to both `missing_from_hca.pct` and `missing_from_cap.pct`.
_MAX_MISSING_PCT = 5.0


def _compute_axis_overlap(cap_ids: set[str], hca_ids: set[str]) -> dict:
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


def _get_annotation_sets(cap_block: Mapping[str, Any]) -> list[str]:
    """Get annotation sets defined in the CAP block's cellannotation_metadata."""
    meta = cap_block.get("cellannotation_metadata", {})
    if isinstance(meta, dict):
        return [s for s in meta if s not in _SKIP_SETS]
    return []


def _get_obs_columns_to_copy(
    annotation_sets: list[str],
    source_obs_columns: list[str],
) -> list[str]:
    """Build list of obs columns to copy from source."""
    columns = []
    all_suffixes = _REQUIRED_SUFFIXES + _OPTIONAL_SUFFIXES

    for setname in annotation_sets:
        for suffix in all_suffixes:
            if not suffix:
                continue
            col = f"{setname}{suffix}"
            if col in source_obs_columns:
                columns.append(col)

    return columns


def copy_cap_annotations(
    source_path: str,
    target_path: str,
    overwrite: bool = False,
) -> dict:
    """Copy CAP cell annotations from source to target h5ad file.

    Uses a hybrid anndata + h5py approach: reads source uns via AnnData
    (backed mode, fast for metadata), reads source obs columns via h5py
    (avoids slow backed-mode column access), writes a temp file via
    anndata for correct encoding, then copies the target and transplants
    new data via h5py.copy(). Avoids loading either file's expression
    matrix into memory.

    Args:
        source_path: Path to source h5ad with CAP annotations.
        target_path: Path to target HCA h5ad to receive annotations.
        overwrite: If True, existing CAP data in the target is first removed
            by strip_cap_annotations (its own edit-log entry, owned palettes
            included), then the import proceeds on the stripped snapshot.
            The strip is a complete, logged edit in its own right: if the
            import stage then fails, the target legitimately remains at the
            stripped snapshot (auditable via its edit log), and retrying the
            overwrite proceeds as a clean import.

    Returns:
        Dict with output_path, copied columns/keys, and marker gene
        validation results, or 'error' on failure.
    """
    try:
        target_path = resolve_latest(target_path)
        # Same-file guard (parity with backfill.py): with overwrite=True the
        # pre-strip would otherwise mutate — and via snapshot cleanup delete —
        # the very file it is about to read CAP annotations from.
        if Path(source_path).exists() and Path(target_path).exists() and Path(source_path).samefile(target_path):
            return {"error": "Source and target are the same file"}

        # --- Step 1: Read source data via h5py (no full AnnData load) ---

        # Read source uns via backed mode (fast — uns is small metadata).
        # We use anndata here because uns contains nested dicts with
        # anndata-specific encoding that's complex to parse via raw h5py.
        with open_h5ad(source_path) as source:
            # Only the nested uns['cap_metadata'] layout is accepted; the
            # deprecated top-level layout is refused, not normalized. Refuse it
            # first — including a mixed file that also carries a nested block —
            # so deprecated keys never slip through. The full block travels into
            # the target unchanged.
            if is_legacy_cap_layout(source.uns):
                return {"error": LEGACY_LAYOUT_ERROR}
            cap_block = resolve_cap_block(source.uns)
            if cap_block is None:
                if CAP_METADATA_KEY in source.uns:
                    return {"error": "Source uns['cap_metadata'] is malformed (not a dict/group)."}
                return {"error": "Source has no CAP metadata: uns['cap_metadata'] is missing."}
            if "cellannotation_metadata" not in cap_block:
                return {"error": "Source has no cellannotation_metadata in uns['cap_metadata']"}
            if "cellannotation_schema_version" not in cap_block:
                return {"error": "Source has no cellannotation_schema_version in uns['cap_metadata']"}

            annotation_sets = _get_annotation_sets(cap_block)
            if not annotation_sets:
                return {"error": "Source has no annotation sets in cellannotation_metadata"}

            cap_schema_version = str(cap_block["cellannotation_schema_version"])
            # resolve_cap_block already returns a fresh dict, so no extra copy.
            source_cap_block = make_serializable(cap_block)

        # Read source obs via h5py (avoids slow backed-mode column access)
        with h5py.File(source_path, "r") as f:
            obs_group = require_obs_group(f)
            source_obs_columns = read_column_order(obs_group)
            obs_cols_to_copy = _get_obs_columns_to_copy(annotation_sets, source_obs_columns)

            idx_key = obs_index_name(obs_group)
            source_index_list = list(read_index(obs_group, idx_key, "CAP cells"))

            var_group = f["var"]
            source_var_list = list(read_index(var_group, obs_index_name(var_group), "CAP genes"))

            source_obs_data = {}
            for col in obs_cols_to_copy:
                item = obs_group[col]
                # CAP serializes all annotation columns as categorical. Enforce
                # that contract — non-categorical columns would either force a
                # dtype coercion on copy (schema drift) or break the writer on
                # the NaN rows that partial-overlap introduces.
                if not (isinstance(item, h5py.Group) and "categories" in item):
                    return {
                        "error": (
                            f"CAP source column '{col}' is not categorical. "
                            "CAP is expected to serialize all annotation columns "
                            "as categorical; please report upstream."
                        )
                    }
                categories, codes = read_categorical_data(item, f"CAP source column '{col}'")
                source_obs_data[col] = pd.Categorical.from_codes(codes, categories=categories)

        if not obs_cols_to_copy:
            return {"error": "No CAP obs columns found to copy"}

        source_index = set(source_index_list)
        dupe_err = check_duplicate_ids(source_index_list, "CAP cells") or check_duplicate_ids(
            source_var_list, "CAP genes"
        )
        if dupe_err:
            return {"error": dupe_err}
        source_var_set = set(source_var_list)

        source_obs_subset = pd.DataFrame(source_obs_data, index=source_index_list)  # pyright: ignore[reportArgumentType]

        # --- Step 2: Validate target via h5py (no AnnData load) ---
        def read_target(path: str) -> tuple[list[str], list[str], list[str], set[str], bool, str, str | None]:
            with h5py.File(path, "r") as f:
                obs_group = require_obs_group(f)
                obs_columns = read_column_order(obs_group)
                idx_key = obs_index_name(obs_group)
                index = list(read_index(obs_group, idx_key, "HCA cells"))

                var_group = f["var"]
                var_list = list(read_index(var_group, obs_index_name(var_group), "HCA genes"))

                uns = read_uns(f)
                uns_keys = set(uns.keys()) if uns is not None else set()
                prov = read_provenance(uns)
                has_prov_cap = prov is not None and "cap" in prov
                log = read_edit_log_h5py(f)
                # Every write refuses a masked-categories target (#651) —
                # except the CAP columns this copy replaces wholesale: CAP
                # files are never repaired here, and a corrupt CAP column
                # being overwritten never reaches the output.
                masked_err = masked_categories_error(f, ignore_obs_columns=cap_obs_columns(obs_columns))
            return obs_columns, index, var_list, uns_keys, has_prov_cap, log, masked_err

        target_obs_columns, target_index, target_var_list, target_uns_keys, target_has_prov_cap, raw_log, masked_err = (
            read_target(target_path)
        )

        if masked_err:
            return {"error": f"Refusing to copy: {masked_err}"}
        dupe_err = check_duplicate_ids(target_index, "HCA cells") or check_duplicate_ids(target_var_list, "HCA genes")
        if dupe_err:
            return {"error": dupe_err}

        # Refuse a target carrying deprecated top-level CAP (from older tooling)
        # rather than silently overwriting it into a mixed-layout file. Symmetric
        # with the legacy-source refusal above (issue #452). Remediation is an
        # explicit strip_cap_annotations run, not a silent normalization.
        if is_legacy_cap_layout(target_uns_keys):
            return {
                "error": (
                    "Target uses the deprecated top-level CAP layout "
                    "(uns['cellannotation_metadata'] / "
                    "uns['cellannotation_schema_version']). Only the nested "
                    "uns['cap_metadata'] layout is accepted; run "
                    "strip_cap_annotations on the target before copying CAP into it."
                )
            }

        target_index_set = set(target_index)
        target_var_set = set(target_var_list)

        # The cell/gene overlap gate below is non-mutating and unaffected by
        # a strip (the obs index and var never change), so it runs BEFORE the
        # overwrite pre-strip — a run that is going to fail validation must
        # not have already replaced the target's snapshot.

        overwrite_strip = None
        if not overwrite:
            # Detect existing CAP data for the refusal: annotation columns
            # ('--' is CAP's separator) and CAP uns material from any era —
            # the nested block, older top-level cap_* keys, provenance/cap,
            # and CAP-shaped palettes (possibly orphaned by the old overwrite
            # era) — mirroring strip_cap_annotations' inventory.
            existing_cap_cols = cap_obs_columns(target_obs_columns)
            existing_cap_uns = [
                k for k in (*_OVERWRITE_UNS_KEYS, *_LEGACY_TOP_LEVEL_PROVENANCE) if k in target_uns_keys
            ]
            if target_has_prov_cap:
                existing_cap_uns.append("provenance/cap")
            existing_cap_uns += cap_palette_keys(target_uns_keys)
            if existing_cap_cols or existing_cap_uns:
                return {
                    "error": (
                        f"Target already has CAP data "
                        f"({len(existing_cap_cols)} obs columns, "
                        f"{len(existing_cap_uns)} uns keys). "
                        f"Use overwrite=True to replace."
                    )
                }

        cell_stats = _compute_axis_overlap(source_index, target_index_set)
        gene_stats = _compute_axis_overlap(source_var_set, target_var_set)
        # Compare on raw fractions, not the 1-dp-rounded `pct` in cell_stats —
        # otherwise 5.04% rounds to 5.0 and slips past the gate.
        n_cap = cell_stats["n_cap"]
        n_hca = cell_stats["n_hca"]
        raw_missing_from_hca_pct = 100.0 * cell_stats["missing_from_hca"]["n"] / n_cap if n_cap else 0.0
        raw_missing_from_cap_pct = 100.0 * cell_stats["missing_from_cap"]["n"] / n_hca if n_hca else 0.0
        if raw_missing_from_hca_pct > _MAX_MISSING_PCT or raw_missing_from_cap_pct > _MAX_MISSING_PCT:
            return {
                "error": (
                    f"Cell ID mismatch over {_MAX_MISSING_PCT:.0f}%: "
                    f"CAP has {n_cap}, HCA has {n_hca}, "
                    f"matched {cell_stats['n_matched']} "
                    f"({cell_stats['missing_from_hca']['n']} missing from HCA "
                    f"= {raw_missing_from_hca_pct:.1f}% of CAP; "
                    f"{cell_stats['missing_from_cap']['n']} missing from CAP "
                    f"= {raw_missing_from_cap_pct:.1f}% of HCA)"
                ),
                "cells": cell_stats,
            }

        if overwrite:
            # Overwrite = strip, then a clean import: one shared removal
            # implementation and two audit entries in the edit log instead of
            # an implicit deletion. The strip is attempted unconditionally —
            # its inventory is the complete definition of CAP material
            # (legacy keys, cap_metadata, provenance/cap, orphan palettes),
            # so no separate detection can drift from it; a clean target
            # reports nothing_to_strip and the import proceeds directly.
            strip_result = strip_cap_annotations(target_path)
            if "error" in strip_result:
                if not strip_result.get("nothing_to_strip"):
                    return {"error": f"Overwrite pre-strip failed: {strip_result['error']}"}
                # Clean target: keep the result shape consistent — overwrite
                # always reports its strip summary, here an empty one.
                overwrite_strip = {"uns_keys_removed": [], "obs_columns_removed": []}
            else:
                overwrite_strip = {
                    k: strip_result[k]
                    for k in ("uns_keys_removed", "obs_columns_removed", "unknown_cap_suffix_columns", "warning")
                    if k in strip_result
                }
                target_path = strip_result["output_path"]
                # Cells and genes are untouched by a strip; only the column
                # set, uns keys, and edit log need re-reading.
                target_obs_columns, _, _, target_uns_keys, _, raw_log, _ = read_target(target_path)

        # --- Step 3: Build aligned temp AnnData ---
        aligned_obs = source_obs_subset.reindex(target_index)
        del source_obs_subset

        # The entire CAP block lands in uns['cap_metadata'] (schema keys +
        # publication provenance together). The edit log stays in
        # uns['provenance']['edit_history'].
        temp_uns: dict[str, Any] = {CAP_METADATA_KEY: source_cap_block}
        uns_keys_added = [CAP_METADATA_KEY]

        source_basename = Path(source_path).name
        source_sha256 = _compute_sha256(source_path)
        if "error" in (parsed := parse_edit_log(raw_log)):
            return parsed

        entry_details = {
            "cap_source_file": source_basename,
            "cap_source_sha256": source_sha256,
            "cap_schema_version": cap_schema_version,
            "annotation_sets": annotation_sets,
            "obs_columns_added": obs_cols_to_copy,
            "uns_keys_added": uns_keys_added,
            "cells": cell_stats,
            "genes": gene_stats,
        }

        # --- Step 4: Write temp, copy target, transplant via h5py ---
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            snapshot_copy_hashed(target_path, ignore_masked_obs_columns=cap_obs_columns(target_obs_columns)) as (
                output_path,
                target_sha256,
            ),
        ):
            # The edit log is built here because the target digest comes from
            # the copy above, and it must reach temp_uns before the temp file
            # is written.
            entry = make_edit_entry(
                operation="import_cap_annotations",
                description=f"Copied CAP annotations from {source_basename}",
                details=entry_details,
            )
            log_result = build_edit_log(raw_log, [entry], target_path, target_sha256)
            if "error" in log_result:
                raise RuntimeError(log_result["error"])
            temp_uns.setdefault("provenance", {})[EDIT_LOG_KEY] = log_result["json"]

            temp_adata = ad.AnnData(
                X=np.empty((len(target_index), 0), dtype=np.float32),
                obs=aligned_obs,
                uns=temp_uns,
            )
            del aligned_obs
            temp_path = str(Path(tmpdir) / "cap_temp.h5ad")
            temp_adata.write_h5ad(temp_path)
            del temp_adata

            # Transplant from temp into output. Any pre-existing CAP data was
            # removed by the overwrite pre-strip above, so this is always a
            # clean addition.
            with h5py.File(temp_path, "r") as f_temp, h5py.File(output_path, "a") as f_out:
                # Creates and stamps uns (and uns/provenance) up front, so the
                # transplants below never meet a bare, unstamped group.
                prov_out = ensure_provenance_group(f_out)

                # Transplant new obs columns from temp
                for col in obs_cols_to_copy:
                    if col in f_temp["obs"]:
                        f_temp.copy(f"obs/{col}", f_out["obs"])
                update_column_order(f_out, obs_cols_to_copy)

                for key in uns_keys_added:
                    if key in f_temp["uns"]:
                        if key in f_out["uns"]:
                            del f_out["uns"][key]
                        f_temp.copy(f"uns/{key}", f_out["uns"])

                # Transplant edit_history into provenance
                if EDIT_LOG_KEY in prov_out:
                    del prov_out[EDIT_LOG_KEY]
                if "provenance" in f_temp["uns"] and EDIT_LOG_KEY in f_temp["uns"]["provenance"]:
                    f_temp.copy(f"uns/provenance/{EDIT_LOG_KEY}", prov_out, EDIT_LOG_KEY)

            # --- Step 5: Verify transplant — full column comparison ---
            verify_err = verify_obs_transplant(temp_path, output_path, obs_cols_to_copy)
            if verify_err:
                raise RuntimeError(verify_err)

        # --- Step 6: Cleanup + validate marker genes ---
        cleanup_previous_version(target_path, output_path)

        marker_validation = validate_marker_genes(output_path)

        result = {
            "output_path": output_path,
            "source": source_basename,
            "annotation_sets": annotation_sets,
            "obs_columns_added": obs_cols_to_copy,
            "uns_keys_added": uns_keys_added,
            "marker_gene_validation": marker_validation,
            "cells": cell_stats,
            "genes": gene_stats,
        }
        if overwrite_strip is not None:
            result["overwrite_strip"] = overwrite_strip
        return result

    except Exception as e:
        # No unlink here: snapshot_copy_hashed removes the snapshot itself.
        return {"error": str(e)}
