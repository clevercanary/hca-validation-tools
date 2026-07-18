"""Copy CAP cell annotations from a source h5ad into an HCA target h5ad."""

from __future__ import annotations

import contextlib
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import anndata as ad
import h5py
import numpy as np
import pandas as pd

from ._io import (
    _decode_bytes,
    ensure_provenance_group,
    open_h5ad,
    read_categorical_data,
    read_edit_log_h5py,
    update_column_order,
    verify_obs_transplant,
)
from ._serialize import make_serializable
from .cap import (
    _OPTIONAL_SUFFIXES,
    _REQUIRED_SUFFIXES,
    CAP_METADATA_KEY,
    LEGACY_LAYOUT_ERROR,
    is_legacy_cap_layout,
    resolve_cap_block,
)
from .marker_genes import validate_marker_genes
from .write import (
    EDIT_LOG_KEY,
    _compute_sha256,
    build_edit_log,
    cleanup_previous_version,
    generate_output_path,
    make_edit_entry,
    resolve_latest,
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


def _check_duplicate_ids(index: list[str], label: str) -> str | None:
    """Return an error message if index has duplicates, else None."""
    if len(set(index)) == len(index):
        return None
    seen, dupes = set(), []
    for x in index:
        if x in seen and x not in dupes:
            dupes.append(x)
            if len(dupes) >= 5:
                break
        seen.add(x)
    return f"{label} have duplicate IDs (first 5): {dupes}"


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
        overwrite: If True, replace existing CAP data in target.

    Returns:
        Dict with output_path, copied columns/keys, and marker gene
        validation results, or 'error' on failure.
    """
    output_path = None
    try:
        target_path = resolve_latest(target_path)

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
            obs_group = f["obs"]
            source_obs_columns = [_decode_bytes(c) for c in obs_group.attrs["column-order"]]
            obs_cols_to_copy = _get_obs_columns_to_copy(annotation_sets, source_obs_columns)

            idx_key = _decode_bytes(obs_group.attrs.get("_index", "_index"))
            source_index_list = [_decode_bytes(v) for v in obs_group[idx_key][:]]

            var_group = f["var"]
            var_idx_key = _decode_bytes(var_group.attrs.get("_index", "_index"))
            source_var_list = [_decode_bytes(v) for v in var_group[var_idx_key][:]]

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
                categories, codes = read_categorical_data(item)
                source_obs_data[col] = pd.Categorical.from_codes(codes, categories=categories)

        if not obs_cols_to_copy:
            return {"error": "No CAP obs columns found to copy"}

        source_index = set(source_index_list)
        dupe_err = _check_duplicate_ids(source_index_list, "CAP cells") or _check_duplicate_ids(
            source_var_list, "CAP genes"
        )
        if dupe_err:
            return {"error": dupe_err}
        source_var_set = set(source_var_list)

        source_obs_subset = pd.DataFrame(source_obs_data, index=source_index_list)  # pyright: ignore[reportArgumentType]

        # --- Step 2: Validate target via h5py (no AnnData load) ---
        with h5py.File(target_path, "r") as f:
            obs_group = f["obs"]
            target_obs_columns = [_decode_bytes(c) for c in obs_group.attrs["column-order"]]
            idx_key = _decode_bytes(obs_group.attrs.get("_index", "_index"))
            target_index = [_decode_bytes(v) for v in obs_group[idx_key][:]]

            var_group = f["var"]
            var_idx_key = _decode_bytes(var_group.attrs.get("_index", "_index"))
            target_var_list = [_decode_bytes(v) for v in var_group[var_idx_key][:]]

            uns = f.get("uns")
            target_uns_keys = set(uns.keys()) if uns else set()
            raw_log = read_edit_log_h5py(f)

        target_index_set = set(target_index)
        dupe_err = _check_duplicate_ids(target_index, "HCA cells") or _check_duplicate_ids(target_var_list, "HCA genes")
        if dupe_err:
            return {"error": dupe_err}
        target_var_set = set(target_var_list)

        # Refuse a target carrying deprecated top-level CAP (from older tooling)
        # rather than silently overwriting it into a mixed-layout file. Symmetric
        # with the legacy-source refusal above (issue #452).
        if is_legacy_cap_layout(target_uns_keys):
            return {
                "error": (
                    "Target uses the deprecated top-level CAP layout "
                    "(uns['cellannotation_metadata'] / "
                    "uns['cellannotation_schema_version']). Only the nested "
                    "uns['cap_metadata'] layout is accepted; re-curate the target "
                    "into the nested layout before copying CAP into it."
                )
            }

        # Detect existing CAP obs columns: any column with "--" separator
        existing_cap_cols = [c for c in target_obs_columns if "--" in c]

        existing_cap_uns = [k for k in _OVERWRITE_UNS_KEYS if k in target_uns_keys]

        if (existing_cap_cols or existing_cap_uns) and not overwrite:
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
        target_sha256 = _compute_sha256(target_path)

        entry = make_edit_entry(
            operation="import_cap_annotations",
            description=f"Copied CAP annotations from {source_basename}",
            details={
                "cap_source_file": source_basename,
                "cap_source_sha256": source_sha256,
                "cap_schema_version": cap_schema_version,
                "annotation_sets": annotation_sets,
                "obs_columns_added": obs_cols_to_copy,
                "uns_keys_added": uns_keys_added,
                "cells": cell_stats,
                "genes": gene_stats,
            },
        )

        log_result = build_edit_log(raw_log, [entry], target_path, target_sha256)
        if "error" in log_result:
            return log_result

        temp_uns.setdefault("provenance", {})[EDIT_LOG_KEY] = log_result["json"]

        n_obs = len(target_index)
        temp_adata = ad.AnnData(
            X=np.empty((n_obs, 0), dtype=np.float32),
            obs=aligned_obs,
            uns=temp_uns,
        )
        del aligned_obs

        # --- Step 4: Write temp, copy target, transplant via h5py ---
        output_path = generate_output_path(target_path)

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = str(Path(tmpdir) / "cap_temp.h5ad")
            temp_adata.write_h5ad(temp_path)
            del temp_adata

            shutil.copy2(target_path, output_path)

            # Transplant from temp into output
            with h5py.File(temp_path, "r") as f_temp, h5py.File(output_path, "a") as f_out:
                f_out.require_group("uns")

                deleted_cols = set()
                if (existing_cap_cols or existing_cap_uns) and overwrite:
                    for col in existing_cap_cols:
                        if col in f_out["obs"]:
                            del f_out["obs"][col]
                            deleted_cols.add(col)
                    for key in list(f_out["uns"].keys()):
                        if key in _OVERWRITE_UNS_KEYS:
                            del f_out["uns"][key]

                # Transplant new obs columns from temp
                for col in obs_cols_to_copy:
                    if col in f_temp["obs"]:
                        f_temp.copy(f"obs/{col}", f_out["obs"])
                update_column_order(f_out, obs_cols_to_copy, deleted_cols)

                for key in uns_keys_added:
                    if key in f_temp["uns"]:
                        if key in f_out["uns"]:
                            del f_out["uns"][key]
                        f_temp.copy(f"uns/{key}", f_out["uns"])

                # Transplant edit_history into provenance
                prov_out = ensure_provenance_group(f_out)
                if EDIT_LOG_KEY in prov_out:
                    del prov_out[EDIT_LOG_KEY]
                if "provenance" in f_temp["uns"] and EDIT_LOG_KEY in f_temp["uns"]["provenance"]:
                    f_temp.copy(f"uns/provenance/{EDIT_LOG_KEY}", prov_out, EDIT_LOG_KEY)

            # --- Step 5: Verify transplant — full column comparison ---
            verify_err = verify_obs_transplant(temp_path, output_path, obs_cols_to_copy)
            if verify_err:
                Path(output_path).unlink()
                return {"error": verify_err}

        # --- Step 6: Cleanup + validate marker genes ---
        cleanup_previous_version(target_path, output_path)

        marker_validation = validate_marker_genes(output_path)

        return {
            "output_path": output_path,
            "source": source_basename,
            "annotation_sets": annotation_sets,
            "obs_columns_added": obs_cols_to_copy,
            "uns_keys_added": uns_keys_added,
            "marker_gene_validation": marker_validation,
            "cells": cell_stats,
            "genes": gene_stats,
        }

    except Exception as e:
        if output_path and Path(output_path).is_file():
            with contextlib.suppress(OSError):
                Path(output_path).unlink()
        return {"error": str(e)}
