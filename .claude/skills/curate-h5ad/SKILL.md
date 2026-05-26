---
name: curate-h5ad
description: Interactively curate an h5ad file toward HCA readiness — runs the mechanical fixes the validator and evaluator agree on, and enumerates everything still requiring wrangler input or upstream data. Sibling to /evaluate-h5ad.
argument-hint: <absolute-path-to-h5ad-file>
---

# Curate H5AD File

Curate the h5ad file at absolute path: `$ARGUMENTS`

Pass an absolute path to the `.h5ad` file. Relative paths are resolved against the MCP server's working directory, which may not match the user's.

`/evaluate-h5ad` identifies problems. `/curate-h5ad` applies the safe, mechanical fixes and hands back a punch list of everything still needing a curator's decision or upstream data.

The target schemas are:
- **HCA Tier 1 metadata** — https://data.humancellatlas.org/metadata/tier-1 (dataset / donor / sample / cell metadata; drives the validator's error list)
- **HCA Cell Annotation schema** — https://data.humancellatlas.org/metadata/cell-annotation (CAP annotation sets, `cellannotation_schema_version`, `cellannotation_metadata`)

## Rules (do not break)

1. **Never invent metadata values.** If a required value isn't already in the file or derivable from it, emit a todo asking the wrangler for it. Do NOT guess a default. Examples of fields that always need wrangler input: `description`, `ambient_count_correction`, `doublet_detection`, `default_embedding`.
2. **Ground every fix in validator + evaluator output.** Run both before proposing anything — don't assume what's wrong.
3. **`replace_placeholder_values` is restricted to `library_preparation_batch` and `library_sequencing_run`.** Never run it on other columns. Other placeholder-looking values (e.g. "unknown" in `author_cell_type`) need curator-reviewed mappings, not a blanket NaN conversion.

## Step 1 — Gather findings

Start with the evaluator, then gate the HCA validator on the schema it reports:

- Run `/evaluate-h5ad $ARGUMENTS` — produces the structured overview report (schema type, X verdict, metadata, storage, embeddings, CAP, edit history, summary). This already calls `check_schema_type` and `check_x_normalization`, so their verdicts are available for Step 2 gating without a separate tool call.
- If the evaluator reports `schema: "hca"`, run `validate_schema $ARGUMENTS` — the HCA schema validator (`is_valid`, full `errors` and `warnings` lists). These are the authoritative blocking/advisory signals for Bucket A decisions. Feature-ID warnings are ordered last; summarize repeated shapes in the punch list rather than pasting thousands of lines verbatim.
- If the evaluator reports `schema: "cellxgene"`, **do not** run `validate_schema` yet — the HCA validator would report a large, mostly irrelevant error list. `convert_cellxgene_to_hca` moves into Bucket A; after it runs, re-enter Step 1 on the converted file to get the accurate HCA findings.

## Step 2 — Classify every finding into one bucket

### Bucket A — Mechanical (safe to run after approval)

Only these are in Bucket A. Nothing else. A row belongs in A only when its preconditions are **already satisfied** at punch-list time — don't pre-list rows whose inputs depend on an unanswered B question (e.g. `set_uns('default_embedding', …)` belongs in B2 until the wrangler picks a value, then gets promoted to A per Step 3).

- **`convert_cellxgene_to_hca`** — when `check_schema_type` reports `schema: "cellxgene"`. Must run **first**: it reshapes the file into HCA layout before any other fix makes sense, and the other tools (including `validate_schema`) assume HCA layout. Strips the HCA-forbidden SRE columns (`self_reported_ethnicity_ontology_term_id`, `self_reported_ethnicity`) as a side-effect — so for CellxGENE-layout inputs, the SRE problem is handled here. After conversion, re-enter Step 1 on the converted file to get an accurate Bucket A/B/C list.
- **`strip_forbidden_obs_columns`** — when the file is **HCA-layout** AND either `obs['self_reported_ethnicity']` or `obs['self_reported_ethnicity_ontology_term_id']` is present. Mechanically removes the privacy-forbidden columns and updates `obs[column-order]`. Required prerequisite for `label_h5ad` (whose preflight refuses while SRE is present), so this should run early in the Bucket A sequence on HCA-layout inputs. On CellxGENE-layout inputs the tool refuses — `convert_cellxgene_to_hca` is the correct entry point there.
- **`normalize_raw`** — when `check_x_normalization` reports `verdict: "raw_counts"` and `has_raw_x: false`. Deterministic: moves X→raw.X, normalizes X with `normalize_total(target_sum=10000) + log1p`.
- **`replace_placeholder_values` on `library_preparation_batch`** — only if the column actually contains placeholder values flagged by the validator.
- **`replace_placeholder_values` on `library_sequencing_run`** — same condition.
- **`label_h5ad`** — eligible once the file is in HCA layout and prior Bucket A items have run. Populates `var['feature_name']` + `feature_reference` / `feature_biotype` / `feature_length` / `feature_type` from Ensembl IDs via vendored GENCODE (mirrored to `raw.var` when present), writes the seven obs ontology labels (`tissue`, `cell_type`, `assay`, `disease`, `sex`, `organism`, `development_stage`) from their `_ontology_term_id` counterparts, and writes `obs['observation_joinid']`. Unknown Ensembl IDs yield NaN across the five `feature_*` columns for that row (not an error). Preflight refuses to run if any controlled label column is pre-populated, if either `obs['self_reported_ethnicity']` / `obs['self_reported_ethnicity_ontology_term_id']` is present (HCA forbids these — privacy; run `strip_forbidden_obs_columns` first on HCA-layout files, or rely on `convert_cellxgene_to_hca`'s auto-strip on CellxGENE-layout files), if `uns['schema_version']` / `uns['schema_reference']` are present, or if any non-human `obs['organism_ontology_term_id']` is present — all of the other preflight failures go to Bucket C below.
- **`copy_cap_annotations`** — only if the wrangler provided a CAP source file in Step 3. Copies annotation sets + `cellannotation_schema_version` + `cellannotation_metadata` from the source into the target. Partial overlap is allowed: ≤5% of cells may be missing on either side (i.e. `cells.missing_from_hca.pct` and `cells.missing_from_cap.pct` must both be ≤5); HCA rows absent from CAP get NaN in the new CAP columns. If either side exceeds 5% missing the tool aborts — treat that as a Bucket B item and bring it back to the wrangler (usually the CAP source is stale or wrong). Gene-axis overlap is recorded but does not gate the copy: a CAP source with extra genes is fine.
- **`compress_h5ad`** — when `get_storage_info` shows no HDF5 filter on X's underlying dataset (`X.data.compression` for sparse X, `X.compression` for dense X). If the file is already compressed, the tool safely returns `{skipped: true, reason: ...}` rather than rewriting. Pure compression, no data change.

### Bucket B — Needs wrangler input (todo — stop and ask)

Split these into two classes so the wrangler sees which items actually block validation vs. which are recommended-but-optional. The primary blocking signal is `validate_schema` — any error it reports (on `obs`, `var`, or `uns`) blocks. Use `list_uns_fields` as a secondary signal for missing `uns` fields specifically: `required: true` fields that are unset are blocking; `required: false` fields that are unset are recommended at most.

For each item, write a concrete question. For **B1** items, do not include a suggested answer — ask only for the missing required value. For **B2** items, if there's an obvious single valid option (e.g. only one 2D embedding exists), you may phrase it as a confirmation question ("`X_umap` — confirm?") rather than silently deciding.

**B1 — Blocking (validator errors or unset `required: true` fields)**

- Missing required `uns` fields (e.g. `study_pi`) — ask for the value(s).
- **No CAP annotation set present** — the file must ship with at least one CAP annotation set (see the [HCA Cell Annotation schema](https://data.humancellatlas.org/metadata/cell-annotation)). Ask the wrangler to provide a local path to a CAP-exported version of this file (same cells, with CAP annotation sets populated) — `copy_cap_annotations` reads the source via AnnData/h5py so a URL must be downloaded locally first. If supplied, `copy_cap_annotations` becomes a mechanical fix for Step 4.
- Any other `uns` field the validator flags as missing.

**B2 — Recommended (optional fields the wrangler may want to set)**

Only the fields explicitly named below belong in B2. Do **not** scan `list_uns_fields` for other unset optional fields and invent questions about them — a field being optional-and-unset is not itself a reason to ask. The skill's scope is the explicit tool list (`convert_cellxgene_to_hca`, `normalize_raw`, `replace_placeholder_values`, `label_h5ad`, `copy_cap_annotations`, `set_uns` on the named fields here, `compress_h5ad`); everything else is the wrangler's call, unprompted.

- `default_embedding` — list the obsm keys and ask which one. Optional per schema, but a file shipped without it will display in CELLxGENE Explorer with no default scatter. Must name a 2D embedding to actually plot; 30D latents (e.g. `X_scVI`) are valid per schema but won't display. If only one 2D embedding exists, surface that — the wrangler will almost certainly pick it.

If the wrangler answers a B2 item during the session, that answer becomes a `set_uns` mechanical fix (promoted to Bucket A) for Step 4.

### Bucket C — Upstream / curator judgment (out of scope for this skill)

Report these but don't attempt to fix:

- High NaN rates on non-allowed columns (e.g. `library_id`) — needs real values from source.
- Sparse or missing `ambient_count_correction` / `doublet_detection` obs columns — per-cell values must come from the upstream source (each source dataset's processing record). Do not broadcast a single value. Report fill rate and move on.
- Delimited-list values in single-identifier columns (e.g. `library_preparation_batch` containing `"lib1; lib2; lib3"`) — needs per-cell resolution, not placeholder replacement.
- Gene IDs missing from the current GENCODE — needs annotation-version decision.
- Inconsistent `author_cell_type` variants — needs a curator mapping.
- (CAP annotations are handled in Bucket B above — the wrangler provides a CAP source file and `copy_cap_annotations` runs mechanically.)
- Cells whose labels don't match the atlas focus (e.g. non-myeloid labels in a myeloid atlas) — needs a curator decision on keep/drop.
- File carries `uns['schema_version']` or `uns['schema_reference']` — signals it has already been through `cellxgene-schema add-labels`. `label_h5ad` refuses to run; upstream needs to re-emit without those keys. Do not strip them here.
- Any `obs['organism_ontology_term_id']` value other than `NCBITaxon:9606` — `label_h5ad` is human-only. Supporting another organism is a code change, not a curation fix.
- Any controlled output column is pre-populated: in `obs` (`tissue`, `cell_type`, `assay`, `disease`, `sex`, `organism`, `development_stage`, `observation_joinid`), in `var` (`feature_name`, `feature_reference`, `feature_biotype`, `feature_length`, `feature_type`), or in `raw.var` when present (the same five `feature_*` columns). `label_h5ad` refuses to run rather than silently overwrite producer values that may disagree with the ontology IDs, GENCODE, or the labeler's hash digest. Upstream needs to drop the column(s) so the labeler can populate from `*_ontology_term_id` and `var.index` cleanly. Do not strip them here — list every offender from the preflight error so the curator can fix them in one pass.
- File carries `uns['cellannotation_metadata']` or other CAP-related uns keys that aren't structurally a dict (e.g. legacy non-dict serializations) — the cell-annotation validator catches these; report verbatim and bring to the CAP curator. (Note: the previous-generation issue here — SRE columns on HCA-layout inputs — now has a Bucket A path via `strip_forbidden_obs_columns`. CellxGENE-layout inputs are still handled by `convert_cellxgene_to_hca` as a side-effect.)
- Any `validate_cell_annotation` error other than `NO_SETS_ERROR` (e.g. missing required `--<suffix>` obs columns on an annotation set, malformed `cellannotation_schema_version`, per-set metadata not a dict). These are CAP-side structural defects — `copy_cap_annotations` faithfully copies what the CAP source provides, so the fix has to land in the CAP export. Surface the validator's verbatim error so the curator can ask the CAP team for a corrected export. (The `NO_SETS_ERROR` case is the B1 "no CAP source provided yet" workflow above.)

## Step 3 — Present the punch list

Show these sections: **A (will run)**, **B1 (blocking — needs your answer)**, **B2 (recommended — optional)**, **C (still to do, out of scope)**. Then stop and wait for explicit approval before running anything.

If the wrangler answers any Bucket B items (B1 or B2), promote those to Bucket A as the appropriate mechanical action: `set_uns` for answered `uns` values (e.g. `default_embedding`, `study_pi`), `copy_cap_annotations` when the answer is a CAP source file path.

## Step 4 — Run the mechanical fixes

Order:

1. `convert_cellxgene_to_hca` first if applicable — then stop, re-run Steps 1–3 on the converted file before continuing (conversion changes the layout enough that the prior punch list is stale).
2. Content edits, in this order: `normalize_raw`, each `replace_placeholder_values`, `label_h5ad`, `copy_cap_annotations` (if a source was supplied), and any `set_uns` approved in Step 3. `label_h5ad` must run **before** `copy_cap_annotations` — `copy_cap_annotations` calls `validate_marker_genes`, which reads `var['feature_name']`; running the labeler first gives marker-gene validation canonical gene symbols to match against.
3. `compress_h5ad` last.

Each tool writes a new timestamped file. For most subsequent calls, passing either the original path or the latest works — `resolve_latest` picks up the newest variant automatically. Two exceptions: `convert_cellxgene_to_hca` does not auto-resolve (call it with the exact path you want to convert), and `copy_cap_annotations` only auto-resolves its `target_path` (the `source_path` is used verbatim).

## Step 5 — Report

Re-run `view_edit_log` on the final file, then produce a structured report with these sections in order. Also re-run `validate_schema` — but only if `check_schema_type` reports `hca` on the final file. If the file is still CellxGENE (e.g. conversion wasn't approved), skip the validator rerun and note why under "Validator delta" instead of pasting a misleading error list. Use markdown tables; skip any section with no content.

Also re-run `get_cap_annotations` on the final file, and if it reports `has_cap_annotations: true`, run `validate_cell_annotation` on the final file too. This is the structural validator the dataset-validator service runs at upload time under the `hcaCellAnnotation` key — running it here catches issues during curation instead of post-upload. Gate on `has_cap_annotations` directly (not on the edit log) so the validator runs on any file that ships with CAP, including files where the producer pre-attached CAP without going through `copy_cap_annotations`. Its output feeds the **Validator delta** section's cell-annotation rows.

For the Provenance line below, re-run `get_summary` on the final file to fetch its obs columns, then run `get_descriptive_stats` with `columns` set to the intersection of `["donor_id", "sample_id", "library_id"]` and the final file's obs column names (extract `name` from each `{name, dtype}` object in `get_summary.obs_columns`).

### Summary

Two or three sentences distilling the session: which Bucket A operations actually ran, the validator delta in one phrase (e.g. "errors went 4 → 2; remaining errors are Bucket C upstream-data issues"), and a one-clause hand-off (e.g. "Bucket B1 awaiting wrangler input on `study_pi`"). Tight prose paragraph, no nested headings.

Then add an **Outstanding issues** bullet list pulled from Buckets B1, B2, and C — one line per item, no bucket-label prefixes (the reader doesn't need our internal taxonomy). Order: validator errors first, then warnings, then non-validator items. The full detail with action questions lives in the *Still to do* section near the bottom — keep this list tight: one line per item, no inline tables. If all three buckets are empty, replace the bullet list with a single line: "Outstanding issues: none."

### Header
One short paragraph or bullet block with: final file path, shape (`n_obs × n_vars`), `title` from `uns`, schema type (include version only when schema is CellxGENE — HCA is unversioned), X verdict + `raw.X` presence, compression status, `obsm` keys present. Add a **Provenance** line: `N donors · M samples · K libraries` from `get_descriptive_stats.columns[<col>].unique` for each column. Skip any metric whose column wasn't returned or whose `unique` is 0.

### Mechanical fixes applied

| # | Operation | Effect |
|---|---|---|
| 1 | `normalize_raw` | e.g. "Moved raw counts → raw.X; normalized X with `normalize_total(target_sum=10000)` + log1p" |
| 2 | `replace_placeholder_values` (`library_preparation_batch`) | e.g. "N cells: `'unknown'` → NaN" |
| 3 | `label_h5ad` | e.g. "Populated `var['feature_name']` for 34,505/35,574 rows (1,069 NaN); wrote 8 obs ontology labels". Preflight rejects pre-populated controlled label columns, so this step never overwrites producer text — if the tool returned a preflight error, the file goes back to upstream (Bucket C). |
| 4 | `copy_cap_annotations` | name the CAP source file |
| 5 | `compress_h5ad` | e.g. "Skipped — already gzipped" or "Rewrote X with gzip level 4" |

Only include the rows for tools that actually ran this session.

### Validator delta

|  | Before | After |
|---|---|---|
| `hcaSchema` errors | N | M |
| `hcaSchema` non-feature-ID warnings | N | M |
| `hcaSchema` CAP zero-observation warnings | N | M |
| `hcaCellAnnotation` errors | N | M |
| `hcaCellAnnotation` warnings | N | M |
| Named issues resolved | — | e.g. "raw.X absent", "`unknown` placeholder in `library_preparation_batch`" |

Counts mirror the two validators the dataset-validator service runs at upload time: `hcaSchema` (Tier 1 + cosmetic checks, from `validate_schema`) and `hcaCellAnnotation` (CAP structural checks, from `validate_cell_annotation`). Each validator's rows (all of its `hcaSchema:*` rows, or all of its `hcaCellAnnotation:*` rows) omit cleanly together when that validator wasn't run this session — e.g. the cell-annotation rows are skipped wholesale on files without CAP.

Count **CAP "zero observations" warnings** (text: `contains a category '...' with zero observations`) separately from other `hcaSchema` warnings. These are *expected* after `copy_cap_annotations`: CAP declares a closed vocabulary per annotation set that spans all lineages, and a per-lineage file only realizes a subset — unused vocabulary terms are intentional schema information, not a defect. Report the count and move on; don't prune them. The validator's `--add-labels` remediation note comes from vendored CellxGENE code and does not apply to HCA.

Also list the specific error/warning kinds that disappeared or newly appeared, one line each, prefixed with their validator (`hcaSchema:` or `hcaCellAnnotation:`).

### CAP overlap (only if `copy_cap_annotations` ran this session, or a prior `import_cap_annotations` entry is in the edit log)

Pull from the latest `import_cap_annotations` entry's `details`:

| Metric | Value |
|---|---|
| CAP source file | `cap_source_file` |
| `cells.n_cap` | … |
| `cells.n_hca` | … |
| `cells.n_matched` | … |
| `cells.missing_from_hca` | `n` (`pct`% of CAP) |
| `cells.missing_from_cap` | `n` (`pct`% of HCA) |
| `genes.n_cap` | … |
| `genes.n_hca` | … |
| `genes.n_matched` | … |
| `genes.missing_from_hca` | `n` (`pct`% of CAP) |
| `genes.missing_from_cap` | `n` (`pct`% of HCA) |

### CAP marker validation (only if `copy_cap_annotations` ran this session, or a prior `import_cap_annotations` entry is in the edit log)

Source the numbers from the `copy_cap_annotations` tool result's `marker_gene_validation` field if it ran this session. If only a prior `import_cap_annotations` entry exists, call `validate_marker_genes` on the final file to get fresh numbers — a marker list that matched against `var.index` before `label_h5ad` populated `var['feature_name']` will look very different now.

Marker symbols are resolved against the target's var gene-name source: `var['feature_name']` is preferred, else `var['gene_name']`, else `var.index` (the Ensembl IDs) as a last resort. Post-`label_h5ad` files always have `feature_name`; files that skipped labeling fall back to whatever the producer shipped.

| Metric | Value |
|---|---|
| Total unique markers | … |
| Found in var gene-name source | … |
| Missing | … |

For each missing marker, list it with its classification exactly as returned by the tool — `not_in_gencode` (marker symbol doesn't resolve to any GENCODE entry — typo, glob pattern, or deprecated rename), `missing_from_var` (valid symbol but not present in this file's gene set), or `known_rename` (submitted marker is a deprecated symbol; the tool provides the current target in `var_name`, plus `ensembl_id` when available):

| Marker | Classification | Var name | Ensembl ID |
|---|---|---|---|
| … | … | … | … |

Leave `Var name` / `Ensembl ID` blank for `not_in_gencode` and `missing_from_var` rows — those fields are only populated on `known_rename`. If all markers hit, say so in one line instead of an empty table.

Report each missing marker by **symbol and classification only**. Do not speculate about why a symbol is `not_in_gencode` (e.g. "looks like a glob", "looks like a truncated `STMN1`", "probably a typo") — the classification name is the answer the tool gave; cause is the curator's call. Pointer for follow-up: `not_in_gencode` and `missing_from_var` go to the CAP curator (CAP-side fix), `known_rename` rows surface the new symbol via `var_name`.

### Still to do

**Bucket B1 — blocking (validator errors or unset `required: true` fields)**

| Field | Question |
|---|---|
| `study_pi` | who are the PI(s)? e.g. `["Teichmann,Sarah,A."]` |

**Bucket B2 — recommended (optional)**

| Field | Question |
|---|---|
| `default_embedding` | `X_umap` (only 2D option) — confirm? |

**Bucket C — upstream / curator**

| Issue | Detail |
|---|---|
| `library_id` NaN (validator error) | Needs real values from source |

Only surface items that are still open — don't re-list anything resolved this session. Omit any of the three sub-tables that have no entries.

### Edit history

Render every entry returned by the `view_edit_log` call from the top of Step 5 as a table, oldest first:

| # | Timestamp (UTC) | Operation | Description |
|---|---|---|---|
| 1 | 2026-04-21 04:19:10 | `normalize_raw` | Moved raw counts to raw.X and normalized X with normalize_total(target_sum=10000) + log1p |

Format the timestamp as `YYYY-MM-DD HH:MM:SS` (drop the `T` and the fractional seconds and timezone — entries are always UTC). Use the entry's `description` field verbatim. If the file has no edit log (no `uns/provenance/edit_history`), say "No edit history — file hasn't been edited through `hca-anndata-tools`."

## Save the report

After rendering the full session report on screen, use the Write tool to save the same markdown to a file alongside the h5ad. Path: same directory as the input file, basename of the input minus the `.h5ad` extension, then `-curation-report-<YYYY-MM-DD>.md` (use today's date). Example: `/foo/bar/myeloid.h5ad` → `/foo/bar/myeloid-curation-report-2026-05-07.md`. Overwrite if it already exists. After saving, confirm the path back to the user as a single line.
