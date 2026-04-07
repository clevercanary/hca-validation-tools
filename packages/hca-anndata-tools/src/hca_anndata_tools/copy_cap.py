"""Copy CAP cell annotations from a source h5ad into an HCA target h5ad."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from ._io import open_h5ad
from ._serialize import make_serializable
from .cap import _REQUIRED_SUFFIXES, _OPTIONAL_SUFFIXES
from .marker_genes import validate_marker_genes
from .write import write_h5ad, resolve_latest, _compute_sha256
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


def _get_real_annotation_sets(source_uns: dict) -> list[str]:
    """Get annotation sets defined in cellannotation_metadata (the real CAP sets)."""
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

    Validates prerequisites, copies annotation obs columns and uns metadata,
    then writes the target with an edit log entry.

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

        # --- Validation 1: Source has CAP ---
        with open_h5ad(source_path) as source:
            source_uns_keys = list(source.uns.keys())
            if "cellannotation_metadata" not in source_uns_keys:
                return {"error": "Source has no cellannotation_metadata in uns"}
            if "cellannotation_schema_version" not in source_uns_keys:
                return {"error": "Source has no cellannotation_schema_version in uns"}

            source_obs_columns = list(source.obs.columns)
            annotation_sets = _get_real_annotation_sets(source.uns)
            if not annotation_sets:
                return {"error": "Source has no annotation sets in cellannotation_metadata"}

            # Snapshot source data we need (before closing backed file)
            cap_schema_version = str(source.uns["cellannotation_schema_version"])
            all_uns_keys = _UNS_COPY_TOPLEVEL + _UNS_CAP_METADATA
            source_uns = {k: make_serializable(source.uns[k]) for k in all_uns_keys if k in source.uns}

            obs_cols_to_copy = _get_obs_columns_to_copy(annotation_sets, source_obs_columns)
            if not obs_cols_to_copy:
                return {"error": "No CAP obs columns found to copy"}

            source_obs_subset = source.obs[obs_cols_to_copy].copy()
            source_n_obs = source.n_obs
            source_index = set(source.obs.index)

        # --- Validation 2: Target clean ---
        with open_h5ad(target_path, backed=None) as target:
            target_obs_columns = list(target.obs.columns)
            existing_cap_cols = [c for c in target_obs_columns if "--" in c]

            if existing_cap_cols and not overwrite:
                return {
                    "error": (
                        f"Target already has {len(existing_cap_cols)} CAP columns "
                        f"(e.g., {existing_cap_cols[0]}). Use overwrite=True to replace."
                    )
                }

            if existing_cap_cols and overwrite:
                target.obs.drop(columns=existing_cap_cols, inplace=True)
                for key in list(target.uns.keys()):
                    if key in _CAP_UNS_KEYS:
                        del target.uns[key]

            # --- Validation 3: Cell identity match ---
            if target.n_obs != source_n_obs:
                return {
                    "error": (
                        f"Cell count mismatch: source has {source_n_obs}, "
                        f"target has {target.n_obs}"
                    )
                }

            target_index = set(target.obs.index)
            if source_index != target_index:
                missing_in_target = source_index - target_index
                missing_in_source = target_index - source_index
                return {
                    "error": (
                        f"Cell ID mismatch: {len(missing_in_target)} IDs in source "
                        f"not in target, {len(missing_in_source)} IDs in target not "
                        f"in source"
                    )
                }

            # --- Copy obs columns (aligned by index) ---
            aligned = source_obs_subset.loc[target.obs.index]
            for col in obs_cols_to_copy:
                target.obs[col] = aligned[col]

            # --- Copy uns metadata ---
            uns_keys_added = []
            for key in _UNS_COPY_TOPLEVEL:
                if key in source_uns:
                    target.uns[key] = source_uns[key]
                    uns_keys_added.append(key)

            # Collect generic CAP keys into a container
            cap_metadata = {k: source_uns[k] for k in _UNS_CAP_METADATA if k in source_uns}
            if cap_metadata:
                target.uns["cap_metadata"] = cap_metadata
                uns_keys_added.append("cap_metadata")

            # --- Edit log ---
            source_basename = os.path.basename(source_path)
            source_sha256 = _compute_sha256(source_path)
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

            # --- Write ---
            result = write_h5ad(target, target_path, [entry])

        if "error" in result:
            return result

        # --- Post-copy: validate marker genes ---
        marker_validation = validate_marker_genes(result["output_path"])

        return {
            **result,
            "source": source_basename,
            "annotation_sets": annotation_sets,
            "obs_columns_added": obs_cols_to_copy,
            "uns_keys_added": uns_keys_added,
            "marker_gene_validation": marker_validation,
        }

    except Exception as e:
        return {"error": str(e)}
