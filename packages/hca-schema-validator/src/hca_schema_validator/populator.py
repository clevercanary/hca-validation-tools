"""Per-column fill/verify for HCA-tracker-imported h5ad files.

The :class:`HCALabeler` ``label()`` flow has a hardline preflight that
refuses if any controlled column is pre-populated — the right behavior
for files freshly converted from CellxGENE (where add-labels already
populated everything upstream, so labeling again would just generate a
new random ``observation_joinid``). But it blocks the HCA-tracker-
imported workflow, where the producer populated *some* cosmetic obs
labels but left others empty and ``var['feature_name']`` missing.

:func:`populate_in_memory` is the tracker-source counterpart:

* Per-column logic — for each of the 5 var ``feature_*`` columns and 7
  obs ontology label columns:

  * Missing OR all-NaN → fill from canonical (term_id → ontology label
    for obs; Ensembl ID → GENCODE for var).
  * Present, every value matches canonical → skip (no-op).
  * Present, any value mismatches → refuse with row-level evidence.

* Never writes ``obs['observation_joinid']``. HCA reserved-but-optional;
  fresh random IDs on every call would pollute the audit trail.

* Refuses outright (no per-column fallback) when:

  * ``obs['self_reported_ethnicity']`` / ``self_reported_ethnicity_ontology_term_id``
    present (caller should run
    ``hca_anndata_tools.strip_forbidden_obs_columns`` first).
  * Any non-human ``obs['organism_ontology_term_id']`` value.
  * ``uns['schema_version']`` present (CellxGENE-layout — caller should
    run ``hca_anndata_tools.convert_cellxgene_to_hca`` instead).

  The check for ``import_cellxgene`` in the edit log is intentionally
  *not* done here — that's an origin-level refusal owned by the
  caller (typically the MCP wrapper) using
  ``hca_anndata_tools.has_edit_log_operation``. Keeps this module free
  of any dependency on ``hca-anndata-tools``.

See issue #421.
"""

from __future__ import annotations

from typing import Any

import anndata as ad
import pandas as pd

from .labeler import HCA_DERIVED_OBS_LABELS, HCALabeler
from .validator import _collect_curie_exceptions, _lookup_canonical_label

_FORBIDDEN_OBS_COLS = (
    "self_reported_ethnicity_ontology_term_id",
    "self_reported_ethnicity",
)
_HUMAN_TAXON = "NCBITaxon:9606"
_ORGANISM_COL = "organism_ontology_term_id"

# Var derived columns, in the order declared by the HCA schema's
# `add_labels` block for the var index. Maps to the
# ``HCALabeler._get_mapping_dict_*`` methods that compute the canonical
# value per Ensembl ID via vendored GENCODE.
_VAR_DERIVED_COLS: tuple[tuple[str, str], ...] = (
    ("feature_name", "_get_mapping_dict_feature_id"),
    ("feature_reference", "_get_mapping_dict_feature_reference"),
    ("feature_biotype", "_get_mapping_dict_feature_biotype"),
    ("feature_length", "_get_mapping_dict_feature_length"),
    ("feature_type", "_get_mapping_dict_feature_type"),
)


def _is_all_nan(series: Any) -> bool:
    """True if every value in the Series is NaN/None. Accepts Any to
    swallow pandas' DataFrame-or-Series return type ambiguity on
    ``df[col]`` indexing — both Series and DataFrame support
    ``.isna().all()`` returning a truthy scalar."""
    return bool(series.isna().all())


def _classify_obs_column(
    obs: pd.DataFrame,
    cosmetic_col: str,
    source_col: str,
    exceptions: set,
) -> tuple[str, list[str], pd.Series | None]:
    """Classify one obs label column as fill / matched / errored / skip-no-source.

    Returns ``(status, errors, canonical_series)``. ``canonical_series``
    is the per-row canonical values, returned when ``status == "fill"``
    so the caller can write it without recomputing. ``errors`` is the
    per-row mismatch messages when ``status == "errored"``.
    """
    cosmetic_present = cosmetic_col in obs.columns
    source_present = source_col in obs.columns

    if not source_present:
        if cosmetic_present:
            return (
                "errored",
                [
                    f"obs['{cosmetic_col}'] is present but '{source_col}' is "
                    f"missing — cannot verify or fill without the source "
                    f"ontology term ID column."
                ],
                None,
            )
        return "skip-no-source", [], None

    term_id_series = pd.Series(obs[source_col]).astype(object)
    canonical: pd.Series = term_id_series.map(
        lambda t: pd.NA if pd.isna(t) else _lookup_canonical_label(str(t), exceptions)
    )

    if not cosmetic_present or _is_all_nan(obs[cosmetic_col]):
        return "fill", [], canonical

    existing = obs[cosmetic_col].astype(object)
    errors: list[str] = []
    # Group by (term_id, file_label) for concise "N rows" message shape
    # instead of per-row spam.
    pair_counts = (
        pd.DataFrame({source_col: term_id_series, cosmetic_col: existing})
        .groupby([source_col, cosmetic_col], dropna=False)
        .size()
    )
    for (term_id, file_label), n in pair_counts.items():
        file_label_str = None if pd.isna(file_label) else str(file_label)
        if pd.isna(term_id):
            if file_label_str is not None:
                errors.append(
                    f"obs['{cosmetic_col}']: {n} rows labeled '{file_label_str}' "
                    f"have NaN in {source_col}. Either add the term ID, or fix "
                    f"the label to NaN."
                )
            continue
        if file_label_str is None:
            # Source has term_id, cosmetic is NaN on this row — treat as
            # fillable downstream (populate will replace NaN with canonical).
            # Don't emit an error.
            continue
        canonical_label = _lookup_canonical_label(str(term_id), exceptions)
        if canonical_label is None or canonical_label == file_label_str:
            continue
        errors.append(
            f"obs['{cosmetic_col}']: {n} rows labeled '{file_label_str}' but "
            f"{source_col} is '{term_id}' (canonical label: '{canonical_label}'). "
            f"Either fix {source_col} to match the label, or fix the label to "
            f"match {source_col}."
        )

    if errors:
        return "errored", errors, None
    return "matched", [], None


def _classify_var_column(
    var: pd.DataFrame,
    col: str,
    canonical_dict: dict[str, Any],
) -> tuple[str, list[str], pd.Series | None]:
    """Classify one var feature_* column. Same shape as _classify_obs_column.

    ``canonical_dict`` is the result of ``HCALabeler._get_mapping_dict_*``
    for this column — maps Ensembl ID → expected value.
    """
    canonical_series = pd.Series(
        [canonical_dict.get(eid, pd.NA) for eid in var.index],
        index=var.index,
        dtype=object,
    )

    if col not in var.columns or _is_all_nan(var[col]):
        return "fill", [], canonical_series

    existing = var[col].astype(object)
    # Both-NaN counts as match (GENCODE didn't know this ID and producer
    # also didn't claim a value).
    both_nan = existing.isna() & canonical_series.isna()
    equal = (existing == canonical_series) | both_nan
    if equal.all():
        return "matched", [], None

    mismatch_mask = ~equal
    pair_counts = (
        pd.DataFrame(
            {"existing": existing[mismatch_mask], "canonical": canonical_series[mismatch_mask]}
        )
        .groupby(["existing", "canonical"], dropna=False)
        .size()
    )
    errors = [
        (
            f"var['{col}']: {n} rows have '{existing_v}' but GENCODE "
            f"canonical is '{canonical_v}'. Either drop var['{col}'] (the "
            f"populator will fill it from var.index) or fix the source "
            f"Ensembl IDs."
        )
        for (existing_v, canonical_v), n in pair_counts.items()
    ]
    return "errored", errors, None


def populate_in_memory(adata: ad.AnnData) -> dict:
    """Per-column fill/verify on an in-memory AnnData.

    Mutates ``adata`` when fills are needed. See module docstring for
    the full per-column logic and refusal rules. Origin-level refusals
    (e.g. CellxGENE-imported via edit log) are the caller's job — this
    function only refuses on data-level signals (SRE present, non-human
    organism, CellxGENE layout via ``uns['schema_version']``).

    Args:
        adata: An :class:`anndata.AnnData` in memory.

    Returns:
        On success-with-write: ``{"filled": [...], "matched": [...]}``.
        On no-op (every present column matched, nothing to fill):
        ``{"skipped": True, "reason": ..., "matched": [...]}``.
        On refusal or mismatch: ``{"error": ..., "details": {...}}``.
    """
    # ---- Data-level preflight refusals ----

    sre_present = [c for c in _FORBIDDEN_OBS_COLS if c in adata.obs.columns]
    if sre_present:
        return {
            "error": (
                f"obs has HCA-forbidden columns {sre_present} (privacy). "
                f"Run hca_anndata_tools.strip_forbidden_obs_columns first; "
                f"populator refuses while SRE columns are present."
            )
        }

    if _ORGANISM_COL in adata.obs.columns:
        non_human = sorted(
            v
            for v in adata.obs[_ORGANISM_COL].dropna().unique()
            if v != _HUMAN_TAXON
        )
        if non_human:
            return {
                "error": (
                    f"obs['{_ORGANISM_COL}'] contains non-human values "
                    f"{non_human}; populator supports only {_HUMAN_TAXON}."
                )
            }

    if "schema_version" in adata.uns:
        return {
            "error": (
                "Input is CellxGENE-layout (uns['schema_version'] is "
                "present). Use hca_anndata_tools.convert_cellxgene_to_hca "
                "instead — it produces an HCA-layout file with labels "
                "already populated by cellxgene-schema add-labels."
            )
        }

    # ---- Compute canonical + classify every column ----

    # HCALabeler instance for its ``_get_mapping_dict_feature_*`` helpers
    # (we never call ``label()`` — that triggers the hardline preflight).
    labeler = HCALabeler(adata)
    obs_components = (
        labeler.schema_def.get("components", {}).get("obs", {}).get("columns", {})
    )

    filled: list[str] = []
    matched: list[str] = []
    errors: list[str] = []
    fill_obs: dict[str, pd.Series] = {}
    fill_var: dict[str, pd.Series] = {}

    # Obs classification
    for cosmetic_col in HCA_DERIVED_OBS_LABELS:
        source_col = f"{cosmetic_col}_ontology_term_id"
        exceptions = _collect_curie_exceptions(obs_components.get(source_col, {}))
        status, col_errors, canonical = _classify_obs_column(
            adata.obs, cosmetic_col, source_col, exceptions
        )
        if status == "errored":
            errors.extend(col_errors)
        elif status == "matched":
            matched.append(cosmetic_col)
        elif status == "fill":
            fill_obs[cosmetic_col] = canonical  # type: ignore[assignment]
        # status == "skip-no-source": neither column present, no action

    # Var classification
    var_ids = adata.var.index.tolist()
    for col, getter_name in _VAR_DERIVED_COLS:
        getter = getattr(labeler, getter_name)
        canonical_dict = getter(var_ids)
        status, col_errors, canonical_series = _classify_var_column(
            adata.var, col, canonical_dict
        )
        if status == "errored":
            errors.extend(col_errors)
        elif status == "matched":
            matched.append(f"var/{col}")
        elif status == "fill":
            fill_var[col] = canonical_series  # type: ignore[assignment]

    # ---- Mismatch refusal: write nothing, surface all errors ----

    if errors:
        return {
            "error": (
                f"{len(errors)} column mismatch error(s) — refusing to "
                f"write. See 'details.errors' for per-column row-level "
                f"evidence; fix the source ontology term IDs or the "
                f"existing column values, then retry."
            ),
            "details": {
                "errors": errors,
                "matched": matched,
                "would_fill": sorted(
                    list(fill_obs) + [f"var/{c}" for c in fill_var]
                ),
            },
        }

    # ---- No-op: every present column matched, nothing to fill ----

    if not fill_obs and not fill_var:
        return {
            "skipped": True,
            "reason": (
                f"Every controlled column was either already-canonical "
                f"({len(matched)} matched) or absent with no source — "
                f"nothing to populate."
            ),
            "matched": matched,
        }

    # ---- Write phase: mutate adata in place ----

    for col, canonical in fill_obs.items():
        adata.obs[col] = pd.Categorical(canonical)
        filled.append(col)

    for col, canonical in fill_var.items():
        adata.var[col] = pd.Categorical(canonical)
        filled.append(f"var/{col}")
        # Mirror to raw.var when present, same as HCALabeler does.
        if adata.raw is not None:
            raw_var = adata.raw.var
            if raw_var is not None and col not in raw_var.columns:
                getter_name = dict(_VAR_DERIVED_COLS)[col]
                raw_dict = getattr(labeler, getter_name)(raw_var.index.tolist())
                raw_canonical = pd.Series(
                    [raw_dict.get(eid, pd.NA) for eid in raw_var.index],
                    index=raw_var.index,
                    dtype=object,
                )
                raw_var[col] = pd.Categorical(raw_canonical)

    return {"filled": filled, "matched": matched}
