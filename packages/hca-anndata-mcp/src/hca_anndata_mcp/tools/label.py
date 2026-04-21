"""MCP wrapper for hca_schema_validator.HCALabeler."""

import os

from hca_anndata_tools._io import open_h5ad
from hca_anndata_tools.write import make_edit_entry, resolve_latest, write_h5ad
from hca_schema_validator import HCA_DERIVED_OBS_LABELS, HCALabeler

_FEATURE_NAME_COL = "feature_name"


def label_h5ad(path: str) -> dict:
    """Populate derived HCA labels in var (feature_*) and obs from `_ontology_term_id` columns.

    Wraps :class:`hca_schema_validator.HCALabeler`. Writes a new timestamped
    edit snapshot and appends to ``uns['provenance']['edit_history']``.

    Should run **before** :func:`copy_cap_annotations`: that tool calls
    :func:`validate_marker_genes`, which reads ``var['feature_name']``.
    Running the labeler first means marker-gene validation has the HCA
    canonical gene symbols to match against.

    The labeler unconditionally overwrites the controlled columns it writes:

    * ``var['feature_name', 'feature_reference', 'feature_biotype',
      'feature_length', 'feature_type']`` (and the ``raw.var`` mirror when
      ``raw`` is present)
    * ``obs`` ontology labels listed in
      :data:`hca_schema_validator.HCA_DERIVED_OBS_LABELS`
      (populated from each ``<field>_ontology_term_id``; ``cell_type`` only
      when its term_id column is present — optional per schema)
    * ``obs['observation_joinid']``

    Refuses to run (preflight ``ValueError`` surfaced as ``{"error": ...}``)
    if the file carries ``uns['schema_version']`` / ``uns['schema_reference']``
    (signals a CellxGENE-labeled file), is missing a required
    ``<field>_ontology_term_id`` column, or contains any
    ``obs['organism_ontology_term_id']`` other than ``NCBITaxon:9606``.
    Unknown Ensembl IDs are not an error — they yield ``NaN`` across the
    five ``feature_*`` columns for that row.

    Args:
        path: Path to an .h5ad file. Auto-resolved to the latest
            timestamped edit snapshot before labeling.

    Returns:
        On success: dict with ``output_path``, ``n_obs``, ``n_vars``,
        ``feature_name_labeled``, ``feature_name_nan``, ``obs_labels_written``,
        ``obs_label_cols_overwritten``, ``var_feature_name_overwritten``.
        On failure: ``{"error": ...}``.
    """
    try:
        path = resolve_latest(path)
        if not os.path.isfile(path):
            return {"error": f"File not found: {path}"}

        # backed="r": the labeler only mutates obs/var/raw.var (all in-memory
        # DataFrames even in backed mode); X stays on disk and is streamed
        # to the new file by adata.write_h5ad. Saves the full-X in-memory
        # footprint on multi-GB files.
        with open_h5ad(path, backed="r") as adata:
            n_obs = int(adata.n_obs)
            n_vars = int(adata.n_vars)

            pre_feature_name_set = _FEATURE_NAME_COL in adata.var.columns
            pre_obs_label_cols = {
                c for c in HCA_DERIVED_OBS_LABELS if c in adata.obs.columns
            }
            # cell_type_ontology_term_id is optional per schema — a producer
            # `cell_type` column without a source means the labeler skips the
            # write, so we track source presence to avoid reporting phantom
            # writes/overwrites.
            labels_with_source = {
                c for c in HCA_DERIVED_OBS_LABELS
                if f"{c}_ontology_term_id" in adata.obs.columns
            }
            raw_var_mirrored = adata.raw is not None

            labeler = HCALabeler(adata)
            try:
                labeler.preflight()
            except ValueError as ve:
                return {"error": f"label_h5ad preflight failed: {ve}"}
            try:
                labeler.label()
            except ValueError as ve:
                # Post-preflight ValueErrors (e.g. ontology term lookup misses
                # inside `_add_labels`) aren't recoverable by fixing inputs —
                # distinct from the preflight case above so the wrangler can
                # tell which one fired.
                return {"error": f"label_h5ad failed during labeling: {ve}"}

            feature_name_nan = int(adata.var[_FEATURE_NAME_COL].isna().sum())
            feature_name_labeled = n_vars - feature_name_nan
            obs_labels_written = sorted(labels_with_source)
            obs_label_cols_overwritten = sorted(pre_obs_label_cols & labels_with_source)

            entry = make_edit_entry(
                operation="label_h5ad",
                description=(
                    f"Populated var feature_* from Ensembl IDs "
                    f"({feature_name_labeled}/{n_vars} matched GENCODE) "
                    f"and {len(obs_labels_written)} obs ontology labels"
                ),
                details={
                    "n_obs": n_obs,
                    "n_vars": n_vars,
                    "feature_name_labeled": feature_name_labeled,
                    "feature_name_nan": feature_name_nan,
                    "raw_var_mirrored": raw_var_mirrored,
                    "obs_labels_written": obs_labels_written,
                    "obs_label_cols_overwritten": obs_label_cols_overwritten,
                    "var_feature_name_overwritten": pre_feature_name_set,
                    "observation_joinid_written": True,
                },
            )

            result = write_h5ad(adata, path, [entry])

        if "error" in result:
            return result

        return {
            "output_path": result["output_path"],
            "n_obs": n_obs,
            "n_vars": n_vars,
            "feature_name_labeled": feature_name_labeled,
            "feature_name_nan": feature_name_nan,
            "obs_labels_written": obs_labels_written,
            "obs_label_cols_overwritten": obs_label_cols_overwritten,
            "var_feature_name_overwritten": pre_feature_name_set,
        }
    except Exception as e:
        return {"error": str(e)}
