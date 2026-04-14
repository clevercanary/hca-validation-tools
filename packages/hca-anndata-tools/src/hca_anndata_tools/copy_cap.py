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
import scipy.sparse as sp

from ._io import open_h5ad, read_obs_column_names, read_obs_index, _decode_bytes
from ._serialize import make_serializable
from .cap import _REQUIRED_SUFFIXES, _OPTIONAL_SUFFIXES
from .marker_genes import validate_marker_genes
from .write import (
    EDIT_LOG_KEY,
    build_edit_log,
    cleanup_previous_version,
    generate_output_path,
    resolve_latest,
    _compute_sha256,
)
from . import __version__

# CAP uns keys copied top-level (already namespaced)
_UNS_COPY_TOPLEVEL = [
    "cellannotation_schema_version",
    "cellannotation_metadata",
    "cap_dataset_url",
    "cap_publication_title",
    "cap_publication_description",
    "cap_publication_url",
]

# CAP uns keys collected into uns["cap_metadata"] container
# (generic names that could collide with HCA/CXG fields)
_UNS_CAP_METADATA = [
    "authors_list",
    "hierarchy",
    "description",
    "publication_timestamp",
    "publication_version",
]

# Demographic annotation sets — not real CAP annotations, just renamed CXG columns
_SKIP_SETS = {"sex", "development_stage", "self_reported_ethnicity"}

# cell_type enrichment columns to copy (but NOT cell_type--cell_ontology_term_id)
_CELL_TYPE_ENRICHMENT = [
    "cell_type--cell_fullname",
    "cell_type--cell_ontology_exists",
    "cell_type--cell_ontology_term",
]

# CAP uns keys to remove on overwrite
_CAP_UNS_KEYS = set(_UNS_COPY_TOPLEVEL) | {"cap_metadata"}


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

    # cell_type enrichment columns (but not cell_type--cell_ontology_term_id)
    for col in _CELL_TYPE_ENRICHMENT:
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
            all_uns_keys = _UNS_COPY_TOPLEVEL + _UNS_CAP_METADATA
            source_uns = {k: make_serializable(source.uns[k]) for k in all_uns_keys if k in source.uns}

        # Read source obs via h5py (avoids slow backed-mode column access)
        source_obs_columns = read_obs_column_names(source_path)
        obs_cols_to_copy = _get_obs_columns_to_copy(annotation_sets, source_obs_columns)
        if not obs_cols_to_copy:
            return {"error": "No CAP obs columns found to copy"}

        source_index_list = read_obs_index(source_path)
        source_n_obs = len(source_index_list)
        source_index = set(source_index_list)
        if len(source_index) != source_n_obs:
            seen, dupes = set(), []
            for x in source_index_list:
                if x in seen and x not in dupes:
                    dupes.append(x)
                    if len(dupes) >= 5:
                        break
                seen.add(x)
            return {"error": f"Source has duplicate cell IDs (first 5): {dupes}"}

        # Read obs columns via h5py and reconstruct as pandas DataFrame
        source_obs_data = {}
        with h5py.File(source_path, "r") as f:
            obs_group = f["obs"]
            for col in obs_cols_to_copy:
                item = obs_group[col]
                if isinstance(item, h5py.Group) and "categories" in item:
                    categories = [_decode_bytes(v) for v in item["categories"][:]]
                    codes = item["codes"][:]
                    source_obs_data[col] = pd.Categorical.from_codes(codes, categories=categories)
                else:
                    source_obs_data[col] = [_decode_bytes(v) for v in item[:]]

        source_obs_subset = pd.DataFrame(source_obs_data, index=source_index_list)

        # --- Step 2: Validate target via h5py (no AnnData load) ---
        target_obs_columns = read_obs_column_names(target_path)
        existing_cap_cols = [c for c in target_obs_columns if "--" in c]

        if existing_cap_cols and not overwrite:
            return {
                "error": (
                    f"Target already has {len(existing_cap_cols)} CAP columns "
                    f"(e.g., {existing_cap_cols[0]}). Use overwrite=True to replace."
                )
            }

        target_index = read_obs_index(target_path)
        target_n_obs = len(target_index)

        if target_n_obs != source_n_obs:
            return {
                "error": (
                    f"Cell count mismatch: source has {source_n_obs}, "
                    f"target has {target_n_obs}"
                )
            }

        target_index_set = set(target_index)
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

        temp_uns = {}
        uns_keys_added = []
        for key in _UNS_COPY_TOPLEVEL:
            if key in source_uns:
                temp_uns[key] = source_uns[key]
                uns_keys_added.append(key)

        cap_metadata = {k: source_uns[k] for k in _UNS_CAP_METADATA if k in source_uns}
        if cap_metadata:
            temp_uns["cap_metadata"] = cap_metadata
            uns_keys_added.append("cap_metadata")

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

        with h5py.File(target_path, "r") as f:
            uns = f.get("uns")
            if uns and EDIT_LOG_KEY in uns:
                raw_log = _decode_bytes(uns[EDIT_LOG_KEY][()])
            else:
                raw_log = "[]"

        log_result = build_edit_log(raw_log, [entry], target_path, target_sha256)
        if "error" in log_result:
            return log_result

        temp_uns[EDIT_LOG_KEY] = log_result["json"]

        n_obs = len(target_index)
        temp_adata = ad.AnnData(
            X=sp.csr_matrix((n_obs, 0), dtype=np.float32),
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

                # Overwrite: delete existing CAP columns and uns keys
                deleted_cols = set()
                if existing_cap_cols and overwrite:
                    for col in existing_cap_cols:
                        if col in f_out["obs"]:
                            del f_out["obs"][col]
                            deleted_cols.add(col)
                    for key in list(f_out["uns"].keys()):
                        if key in _CAP_UNS_KEYS:
                            del f_out["uns"][key]

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
                    if key in f_temp["uns"]:
                        if key in f_out["uns"]:
                            del f_out["uns"][key]
                        f_temp.copy(f"uns/{key}", f_out["uns"])

                if EDIT_LOG_KEY in f_out["uns"]:
                    del f_out["uns"][EDIT_LOG_KEY]
                if EDIT_LOG_KEY in f_temp["uns"]:
                    f_temp.copy(f"uns/{EDIT_LOG_KEY}", f_out["uns"])

        # --- Step 5: Verify transplant correctness ---
        # Spot-check a few cells to catch alignment or encoding errors.
        check_positions = [0, len(target_index) // 2, len(target_index) - 1]
        check_cell_ids = [target_index[i] for i in check_positions]

        with h5py.File(output_path, "r") as f_out:
            for col in obs_cols_to_copy:
                item = f_out["obs"][col]
                if isinstance(item, h5py.Group) and "categories" in item:
                    cats = [_decode_bytes(v) for v in item["categories"][:]]
                    codes = item["codes"]
                    for pos, cell_id in zip(check_positions, check_cell_ids):
                        output_val = cats[codes[pos]] if codes[pos] >= 0 else None
                        expected = source_obs_subset.at[cell_id, col]
                        expected_str = str(expected) if not pd.isna(expected) else None
                        if str(output_val) != str(expected_str):
                            os.remove(output_path)
                            return {
                                "error": (
                                    f"Verification failed: column '{col}', "
                                    f"cell '{cell_id}' (pos {pos}): "
                                    f"expected '{expected_str}', got '{output_val}'"
                                )
                            }
                else:
                    for pos, cell_id in zip(check_positions, check_cell_ids):
                        output_val = str(_decode_bytes(item[pos]))
                        expected = str(source_obs_subset.at[cell_id, col])
                        if output_val != expected:
                            os.remove(output_path)
                            return {
                                "error": (
                                    f"Verification failed: column '{col}', "
                                    f"cell '{cell_id}' (pos {pos}): "
                                    f"expected '{expected}', got '{output_val}'"
                                )
                            }

        del source_obs_subset

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
        return {"error": str(e)}
