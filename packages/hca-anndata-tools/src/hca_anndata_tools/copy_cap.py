"""Copy CAP cell annotations from a source h5ad into an HCA target h5ad."""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timezone

import anndata as ad
import h5py
import numpy as np
import pandas as pd

from ._io import open_h5ad, ensure_provenance_group, verify_obs_transplant, _decode_bytes
from ._serialize import make_serializable
from .cap import _REQUIRED_SUFFIXES, _OPTIONAL_SUFFIXES
from .marker_genes import validate_marker_genes
from .write import (
    EDIT_LOG_KEY,
    _LEGACY_EDIT_LOG_KEY,
    build_edit_log,
    cleanup_previous_version,
    generate_output_path,
    resolve_latest,
    _compute_sha256,
)
from . import __version__

# Cell-annotation-schema uns keys — stay at top level (HCA schema)
_UNS_SCHEMA_TOPLEVEL = [
    "cellannotation_schema_version",
    "cellannotation_metadata",
]

# CAP provenance keys — collected into uns["provenance"]["cap"]
_UNS_CAP_PROVENANCE = [
    "cap_dataset_url",
    "cap_publication_title",
    "cap_publication_description",
    "cap_publication_url",
    "authors_list",
    "hierarchy",
    "description",
    "publication_timestamp",
    "publication_version",
]

# Demographic annotation sets — not real CAP annotations, just renamed CXG columns
_SKIP_SETS = {"sex", "development_stage", "self_reported_ethnicity"}

# Keys to detect/remove existing CAP data on overwrite
# Top-level uns keys written by copy_cap, replaced on overwrite.
# provenance/cap is handled separately via merge logic.
_OVERWRITE_UNS_KEYS = set(_UNS_SCHEMA_TOPLEVEL)


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
    return f"{label} has duplicate cell IDs (first 5): {dupes}"


def _get_annotation_sets(source_uns: dict) -> list[str]:
    """Get annotation sets defined in cellannotation_metadata."""
    meta = source_uns.get("cellannotation_metadata", {})
    if isinstance(meta, dict):
        return [s for s in meta.keys() if s not in _SKIP_SETS]
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
            if "cellannotation_metadata" not in source.uns:
                return {"error": "Source has no cellannotation_metadata in uns"}
            if "cellannotation_schema_version" not in source.uns:
                return {"error": "Source has no cellannotation_schema_version in uns"}

            annotation_sets = _get_annotation_sets(source.uns)
            if not annotation_sets:
                return {"error": "Source has no annotation sets in cellannotation_metadata"}

            cap_schema_version = str(source.uns["cellannotation_schema_version"])
            all_uns_keys = _UNS_SCHEMA_TOPLEVEL + _UNS_CAP_PROVENANCE
            source_uns = {k: make_serializable(source.uns[k]) for k in all_uns_keys if k in source.uns}

        # Read source obs via h5py (avoids slow backed-mode column access)
        with h5py.File(source_path, "r") as f:
            obs_group = f["obs"]
            source_obs_columns = [_decode_bytes(c) for c in obs_group.attrs["column-order"]]
            obs_cols_to_copy = _get_obs_columns_to_copy(annotation_sets, source_obs_columns)

            idx_key = _decode_bytes(obs_group.attrs.get("_index", "_index"))
            source_index_list = [_decode_bytes(v) for v in obs_group[idx_key][:]]

            source_obs_data = {}
            for col in obs_cols_to_copy:
                item = obs_group[col]
                if isinstance(item, h5py.Group) and "categories" in item:
                    categories = [_decode_bytes(v) for v in item["categories"][:]]
                    codes = item["codes"][:]
                    source_obs_data[col] = pd.Categorical.from_codes(codes, categories=categories)
                else:
                    source_obs_data[col] = [_decode_bytes(v) for v in item[:]]

        if not obs_cols_to_copy:
            return {"error": "No CAP obs columns found to copy"}

        source_n_obs = len(source_index_list)
        source_index = set(source_index_list)
        dupe_err = _check_duplicate_ids(source_index_list, "Source")
        if dupe_err:
            return {"error": dupe_err}

        source_obs_subset = pd.DataFrame(source_obs_data, index=source_index_list)

        # --- Step 2: Validate target via h5py (no AnnData load) ---
        with h5py.File(target_path, "r") as f:
            obs_group = f["obs"]
            target_obs_columns = [_decode_bytes(c) for c in obs_group.attrs["column-order"]]
            idx_key = _decode_bytes(obs_group.attrs.get("_index", "_index"))
            target_index = [_decode_bytes(v) for v in obs_group[idx_key][:]]

            uns = f.get("uns")
            target_uns_keys = set(uns.keys()) if uns else set()
            has_provenance_cap = (
                uns is not None
                and "provenance" in uns
                and isinstance(uns["provenance"], h5py.Group)
                and "cap" in uns["provenance"]
            )
            # Read edit log from provenance/edit_history, fall back to legacy
            raw_log = "[]"
            if uns:
                prov = uns.get("provenance")
                if prov and isinstance(prov, h5py.Group) and EDIT_LOG_KEY in prov:
                    raw_log = _decode_bytes(prov[EDIT_LOG_KEY][()])
                elif _LEGACY_EDIT_LOG_KEY in uns:
                    raw_log = _decode_bytes(uns[_LEGACY_EDIT_LOG_KEY][()])

        target_n_obs = len(target_index)
        target_index_set = set(target_index)
        dupe_err = _check_duplicate_ids(target_index, "Target")
        if dupe_err:
            return {"error": dupe_err}

        # Detect existing CAP obs columns: any column with "--" separator
        existing_cap_cols = [c for c in target_obs_columns if "--" in c]

        existing_cap_uns = [k for k in _OVERWRITE_UNS_KEYS if k in target_uns_keys]
        if has_provenance_cap:
            existing_cap_uns.append("provenance/cap")

        if (existing_cap_cols or existing_cap_uns) and not overwrite:
            return {
                "error": (
                    f"Target already has CAP data "
                    f"({len(existing_cap_cols)} obs columns, "
                    f"{len(existing_cap_uns)} uns keys). "
                    f"Use overwrite=True to replace."
                )
            }

        if target_n_obs != source_n_obs:
            return {
                "error": (
                    f"Cell count mismatch: source has {source_n_obs}, "
                    f"target has {target_n_obs}"
                )
            }

        if source_index != target_index_set:
            missing_in_target = source_index - target_index_set
            missing_in_source = target_index_set - source_index
            return {
                "error": (
                    f"Cell ID mismatch: {len(missing_in_target)} IDs in source "
                    f"not in target, {len(missing_in_source)} IDs in target not "
                    f"in source"
                )
            }

        # --- Step 3: Build aligned temp AnnData ---
        aligned_obs = source_obs_subset.loc[target_index]
        del source_obs_subset

        temp_uns = {}
        uns_keys_added = []
        for key in _UNS_SCHEMA_TOPLEVEL:
            if key in source_uns:
                temp_uns[key] = source_uns[key]
                uns_keys_added.append(key)

        cap_provenance = {k: source_uns[k] for k in _UNS_CAP_PROVENANCE if k in source_uns}
        if cap_provenance:
            temp_uns["provenance"] = {"cap": cap_provenance}
            uns_keys_added.append("provenance")

        source_basename = os.path.basename(source_path)
        source_sha256 = _compute_sha256(source_path)
        target_sha256 = _compute_sha256(target_path)

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool": "hca-anndata-tools",
            "tool_version": __version__,
            "operation": "import_cap_annotations",
            "description": f"Copied CAP annotations from {source_basename}",
            "details": {
                "cap_source_file": source_basename,
                "cap_source_sha256": source_sha256,
                "cap_schema_version": cap_schema_version,
                "annotation_sets": annotation_sets,
                "obs_columns_added": obs_cols_to_copy,
                "uns_keys_added": uns_keys_added,
            },
        }

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
            temp_path = os.path.join(tmpdir, "cap_temp.h5ad")
            temp_adata.write_h5ad(temp_path)
            del temp_adata

            shutil.copy2(target_path, output_path)

            # Transplant from temp into output
            with h5py.File(temp_path, "r") as f_temp, \
                 h5py.File(output_path, "a") as f_out:

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
                    # Delete provenance/cap but preserve provenance/cellxgene
                    if "provenance" in f_out["uns"] and "cap" in f_out["uns"]["provenance"]:
                        del f_out["uns"]["provenance"]["cap"]

                for col in obs_cols_to_copy:
                    if col in f_temp["obs"]:
                        f_temp.copy(f"obs/{col}", f_out["obs"])

                # Update column-order (remove deleted, add new)
                current_order = [
                    _decode_bytes(c) for c in f_out["obs"].attrs["column-order"]
                    if _decode_bytes(c) not in deleted_cols
                ]
                new_cols = [c for c in obs_cols_to_copy if c not in current_order]
                f_out["obs"].attrs["column-order"] = current_order + new_cols

                for key in uns_keys_added:
                    if key == "provenance":
                        # Merge into existing provenance group, don't replace it
                        prov_out = ensure_provenance_group(f_out)
                        if "cap" in prov_out:
                            del prov_out["cap"]
                        f_temp.copy("uns/provenance/cap", prov_out, "cap")
                    elif key in f_temp["uns"]:
                        if key in f_out["uns"]:
                            del f_out["uns"][key]
                        f_temp.copy(f"uns/{key}", f_out["uns"])

                # Transplant edit_history into provenance
                prov_out = f_out.require_group("uns/provenance")
                prov_out.attrs.setdefault("encoding-type", "dict")
                prov_out.attrs.setdefault("encoding-version", "0.1.0")
                if EDIT_LOG_KEY in prov_out:
                    del prov_out[EDIT_LOG_KEY]
                if "provenance" in f_temp["uns"] and EDIT_LOG_KEY in f_temp["uns"]["provenance"]:
                    f_temp.copy(f"uns/provenance/{EDIT_LOG_KEY}", prov_out, EDIT_LOG_KEY)
                # Remove legacy key if present
                if _LEGACY_EDIT_LOG_KEY in f_out["uns"]:
                    del f_out["uns"][_LEGACY_EDIT_LOG_KEY]

            # --- Step 5: Verify transplant — full column comparison ---
            verify_err = verify_obs_transplant(temp_path, output_path, obs_cols_to_copy)
            if verify_err:
                os.remove(output_path)
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
        }

    except Exception as e:
        if output_path and os.path.isfile(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
        return {"error": str(e)}
