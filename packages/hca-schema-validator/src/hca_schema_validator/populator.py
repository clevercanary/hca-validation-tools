"""Per-column fill/verify for HCA-tracker-imported h5ad files.

The :class:`HCALabeler` ``label()`` flow has a hardline preflight that
refuses if any controlled column is pre-populated. For files freshly
converted from CellxGENE that's effectively a "skip" gate (the convert
step preserves all label columns from upstream add-labels, so the
labeler always refuses on them — the right answer is to not call it).
But the same gate blocks the HCA-tracker-imported workflow, where the
producer populated *some* cosmetic obs labels but left others empty
and ``var['feature_name']`` missing — there's real per-column work to
do, and the all-or-nothing refusal is wrong here.

:func:`populate_in_memory` is the tracker-source counterpart:

* Per-column logic — for each of the 5 var ``feature_*`` columns and 7
  obs ontology label columns:

  * Missing OR all-NaN → fill from canonical (term_id → ontology label
    for obs; Ensembl ID → GENCODE for var).
  * Present, every value matches canonical → skip (no-op).
  * Present, any value mismatches → refuse with row-level evidence.

* Never writes ``obs['observation_joinid']``. The column is HCA-
  reserved-but-not-required (the HCA validator doesn't error on its
  absence; CellxGENE downstream consumers do require it). The value
  ``HCALabeler`` writes for it via ``get_hash_digest_column(obs)`` is
  deterministic per cell index (xxhash → base85) — not random — so
  the avoidance here isn't about reproducibility. It's scope: a per-
  column-fill tool shouldn't quietly start writing reserved columns
  that aren't in its declared contract. If a file genuinely needs
  ``observation_joinid`` populated, that's ``label_h5ad``'s
  responsibility (and ``label_h5ad`` only runs cleanly on files with
  all controlled columns absent — currently a niche case).

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

from typing import Any, cast

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


def _classify_obs_column(
    obs: pd.DataFrame,
    cosmetic_col: str,
    source_col: str,
    exceptions: set,
) -> tuple[str, list[str], pd.Series | None]:
    """Classify one obs label column as fill / matched / errored / skip-no-source.

    Returns ``(status, errors, series)``:

    * ``"fill"`` — column missing entirely. ``series`` is the per-row
      canonical for the caller to write.
    * ``"matched"`` — column present, every non-NaN row agrees with
      canonical, no NaN rows have a known canonical to fill. ``series``
      is ``None``.
    * ``"errored"`` — at least one non-NaN row disagrees with canonical
      (or a labeled row has a NaN source term ID). ``series`` is
      ``None``. ``errors`` is populated.
    * ``"skip-no-source"`` — neither cosmetic nor source column present;
      nothing to do.

    Note: returning ``"matched"`` with NaN rows present and a non-NaN
    canonical for those rows would be a partial-fill case — those are
    routed through ``"fill"`` with a *merged* series (existing values
    preserved, NaN rows replaced with canonical) when no mismatches are
    found. The merge happens only after every populated row has been
    verified against canonical.
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
    # Cache canonical lookups per unique term_id. With a tracker file of
    # ~50k cells and ~5 unique tissue terms, this collapses ~50k ontology
    # lookups to ~5 — significant on large files. Mirrors the cache shape
    # in :func:`validator._compare_cosmetic_to_term_ids`.
    canonical_cache: dict[str, Any] = {
        str(t): _lookup_canonical_label(str(t), exceptions)
        for t in term_id_series.dropna().unique()
    }
    canonical: pd.Series = term_id_series.map(
        lambda t: pd.NA if pd.isna(t) else canonical_cache.get(str(t))
    )

    if not cosmetic_present:
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
            # term_id present, cosmetic NaN — partial-fill candidate.
            # Verified by the merge step below; no error here.
            continue
        canonical_label = canonical_cache[str(term_id)]
        if canonical_label is None or canonical_label == file_label_str:
            continue
        errors.append(
            f"obs['{cosmetic_col}']: {n} rows labeled '{file_label_str}' but "
            f"{source_col} is '{term_id}' (canonical label: '{canonical_label}'). "
            f"Either fix {source_col} to match the label, or fix the label to "
            f"match {source_col}."
        )

    # If any non-NaN row mismatches canonical, refuse — no partial fill
    # on a column where the producer's filled rows don't match canonical.
    if errors:
        return "errored", errors, None

    # Every populated row agrees with canonical. Now check whether any
    # NaN rows could be filled from canonical. If so, return a merged
    # series (existing values preserved, NaN rows replaced with canonical
    # where canonical is itself non-NaN).
    needs_fill_mask = existing.isna() & canonical.notna()
    if needs_fill_mask.any():
        merged = cast(pd.Series, existing.where(~needs_fill_mask, canonical))
        return "fill", [], merged

    return "matched", [], None


def _classify_var_column(
    var: pd.DataFrame,
    col: str,
    canonical_dict: dict[str, Any],
) -> tuple[str, list[str], pd.Series | None]:
    """Classify one var feature_* column. Same shape as _classify_obs_column.

    ``canonical_dict`` is the result of ``HCALabeler._get_mapping_dict_*``
    for this column — maps Ensembl ID → expected value.

    Partial-fill semantics match the obs side: any populated row that
    disagrees with canonical refuses the column outright; only when
    every populated row matches do NaN rows get filled from canonical
    (and only where canonical itself is non-NaN).
    """
    canonical_series = pd.Series(
        [canonical_dict.get(eid, pd.NA) for eid in var.index],
        index=var.index,
        dtype=object,
    )

    if col not in var.columns:
        return "fill", [], canonical_series

    existing = var[col].astype(object)
    existing_nan = existing.isna()
    canonical_nan = canonical_series.isna()

    # A row is in a "real disagreement" state when both sides have a
    # value and they differ. Rows where the producer has a value and
    # canonical is NaN ALSO count as mismatch — producer claimed a
    # symbol for an Ensembl ID GENCODE doesn't know, and the populator
    # can't verify it. NaN-existing rows are never mismatch (they're
    # either fillable or both-NaN no-ops).
    populated_disagreement = (
        ~existing_nan & (~canonical_nan & (existing != canonical_series))
        | (~existing_nan & canonical_nan)
    )
    if populated_disagreement.any():
        pair_counts = (
            pd.DataFrame(
                {
                    "existing": existing[populated_disagreement],
                    "canonical": canonical_series[populated_disagreement],
                }
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

    # Every populated row matches canonical. Check whether NaN rows have
    # a non-NaN canonical to fill.
    needs_fill_mask = existing_nan & ~canonical_nan
    if needs_fill_mask.any():
        merged = cast(pd.Series, existing.where(~needs_fill_mask, canonical_series))
        return "fill", [], merged

    return "matched", [], None


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

    # CellxGENE-derived detection: file isn't currently in CellxGENE
    # layout (we passed the schema_version check above) but has markers
    # from a prior CellxGENE conversion or add-labels pass. Multiple
    # signals are checked because different conversion paths leave
    # different markers — combining them guards against any single
    # marker being lost or wiped downstream.
    cellxgene_signals: list[str] = []
    provenance = adata.uns.get("provenance")
    if isinstance(provenance, dict) and "cellxgene" in provenance:
        cellxgene_signals.append("uns['provenance']['cellxgene']")
    if "observation_joinid" in adata.obs.columns:
        cellxgene_signals.append("obs['observation_joinid']")

    if cellxgene_signals:
        return {
            "error": (
                f"File is CellxGENE-derived (signals: "
                f"{', '.join(cellxgene_signals)}). cellxgene-schema "
                f"add-labels has already populated every controlled "
                f"column upstream; running populate_labels would be a "
                f"redundant pass. If you need to repopulate, drop the "
                f"label columns and use label_h5ad instead."
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
    # raw.var fills, keyed by column name. raw.var.index can differ from
    # var.index (different gene set), so the canonical is recomputed per
    # raw.var.index before classification — never reuse the var-side
    # canonical for raw.var.
    fill_raw_var: dict[str, pd.Series] = {}

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

    # Var + raw.var classification — symmetric, same three-way contract
    # (fill / match / error) applied to both. raw.var gets its own
    # canonical computed against its own index, since gene sets can differ.
    var_ids = adata.var.index.tolist()
    raw_var = adata.raw.var if adata.raw is not None else None
    raw_var_ids = raw_var.index.tolist() if raw_var is not None else None

    for col, getter_name in _VAR_DERIVED_COLS:
        getter = getattr(labeler, getter_name)

        # adata.var
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

        # adata.raw.var — same logic, separate canonical
        if raw_var is not None and raw_var_ids is not None:
            raw_canonical_dict = getter(raw_var_ids)
            raw_status, raw_col_errors, raw_canonical_series = _classify_var_column(
                raw_var, col, raw_canonical_dict
            )
            if raw_status == "errored":
                # Re-tag the error messages so the caller sees which side
                # produced them (the underlying messages say "var['col']";
                # rewrite to "raw.var['col']" for clarity).
                errors.extend(
                    e.replace(f"var['{col}']", f"raw.var['{col}']")
                    for e in raw_col_errors
                )
            elif raw_status == "matched":
                matched.append(f"raw.var/{col}")
            elif raw_status == "fill":
                fill_raw_var[col] = raw_canonical_series  # type: ignore[assignment]

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
                    list(fill_obs)
                    + [f"var/{c}" for c in fill_var]
                    + [f"raw.var/{c}" for c in fill_raw_var]
                ),
            },
        }

    # ---- No-op: every present column matched, nothing to fill ----

    if not fill_obs and not fill_var and not fill_raw_var:
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

    if fill_raw_var and adata.raw is not None:
        # adata.raw.var assignment goes through anndata's Raw object —
        # mutate it in place, same shape as the var-side write above.
        raw_var_df = adata.raw.var
        for col, canonical in fill_raw_var.items():
            raw_var_df[col] = pd.Categorical(canonical)
            filled.append(f"raw.var/{col}")

    return {"filled": filled, "matched": matched}
