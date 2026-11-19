"""Copy CAP cell annotations from a source h5ad into an HCA target h5ad."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, cast

import anndata as ad
import h5py
import numpy as np
import pandas as pd

from . import cap_pair as checks
from ._errors import failure_result
from ._io import (
    check_duplicate_ids,
    ensure_provenance_group,
    gate_h5ad_paths,
    read_categorical_data,
    read_column_order,
    read_edit_log_h5py,
    update_column_order,
    verify_obs_transplant,
)
from ._serialize import make_serializable
from .cap import CAP_METADATA_KEY
from .guards import require_obs_group
from .marker_genes import validate_marker_genes
from .strip_cap import strip_cap_annotations
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


@gate_h5ad_paths
def copy_cap_annotations(
    source_path: str,
    target_path: str,
    overwrite: bool = False,
) -> dict:
    """Copy CAP cell annotations from source to target h5ad file.

    Refuses on the first failed check in :mod:`cap_pair`, reading the source's
    CAP uns and obs columns via h5py, then writes a temp file via anndata for
    correct encoding, copies the target and transplants the new data via
    h5py.copy(). Avoids loading either file's expression matrix into memory.

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
        validation results. On failure, 'error' — plus 'traceback' when the
        failure was an exception rather than a refusal we authored, since
        that is the only case where there are frames worth carrying
        (contract principle 15).
    """
    try:
        target_path = resolve_latest(target_path)
        # Same-file guard (parity with backfill.py): with overwrite=True the
        # pre-strip would otherwise mutate — and via snapshot cleanup delete —
        # the very file it is about to read CAP annotations from.
        if failure := checks.same_file_failure(source_path, target_path):
            return {"error": failure}

        # --- Step 1: Read and check the source via h5py (no full AnnData load) ---
        with h5py.File(source_path, "r") as f:
            # Only the nested uns['cap_metadata'] layout is accepted; the
            # deprecated top-level layout is refused, not normalized — including
            # a mixed file that also carries a nested block. The full block
            # travels into the target unchanged.
            cap = checks.read_source_cap(f)
            if failure := checks.source_layout_failure(cap) or checks.source_block_failure(cap):
                return {"error": failure}
            cap_block = cast(dict[str, Any], cap.block)
            if failure := checks.source_metadata_failure(cap_block) or checks.source_schema_version_failure(cap_block):
                return {"error": failure}
            annotation_sets = checks.annotation_sets(cap_block)
            if failure := checks.annotation_sets_failure(annotation_sets):
                return {"error": failure}
            cap_schema_version = str(cap_block["cellannotation_schema_version"])
            source_cap_block = make_serializable(cap_block)

            obs_group = require_obs_group(f)
            obs_cols_to_copy = checks.columns_to_copy(annotation_sets, read_column_order(obs_group))
            source_index_list, source_var_list = checks.read_ids(f, "CAP")
            if failure := checks.non_categorical_failure(obs_group, obs_cols_to_copy):
                return {"error": failure}
            source_obs_data = {}
            for col in obs_cols_to_copy:
                categories, codes = read_categorical_data(cast(h5py.Group, obs_group[col]))
                source_obs_data[col] = pd.Categorical.from_codes(codes, categories=categories)

        if failure := checks.columns_failure(obs_cols_to_copy):
            return {"error": failure}
        if failure := check_duplicate_ids(source_index_list, "CAP cells") or check_duplicate_ids(
            source_var_list, "CAP genes"
        ):
            return {"error": failure}
        source_obs_subset = pd.DataFrame(source_obs_data, index=source_index_list)  # pyright: ignore[reportArgumentType]

        # --- Step 2: Validate target via h5py (no AnnData load) ---
        with h5py.File(target_path, "r") as f:
            target_index, target_var_list = checks.read_ids(f, "HCA")
            target_cap = checks.read_target_cap(f, read_column_order(require_obs_group(f)))
            raw_log = read_edit_log_h5py(f)

        if failure := check_duplicate_ids(target_index, "HCA cells") or check_duplicate_ids(
            target_var_list, "HCA genes"
        ):
            return {"error": failure}
        if failure := checks.target_layout_failure(target_cap):
            return {"error": failure}
        # The checks below are non-mutating and unaffected by a strip (the obs
        # index and var never change), so they run BEFORE the overwrite
        # pre-strip — a run that is going to fail validation must not have
        # already replaced the target's snapshot.
        if not overwrite and (failure := checks.existing_cap_failure(target_cap)):
            return {"error": failure}

        cell_stats = checks.compute_axis_overlap(set(source_index_list), set(target_index))
        gene_stats = checks.compute_axis_overlap(set(source_var_list), set(target_var_list))
        if failure := checks.cell_overlap_failure(cell_stats):
            return {"error": failure, "cells": cell_stats}

        overwrite_strip = None
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
                # Cells and genes are untouched by a strip; only the edit log
                # needs re-reading.
                with h5py.File(target_path, "r") as f:
                    raw_log = read_edit_log_h5py(f)

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
            snapshot_copy_hashed(target_path) as (output_path, target_sha256),
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
        # failure_result decides whether this is ours (a Refusal, reported
        # verbatim) or something that happened to us (reported with frames).
        return failure_result(e)
