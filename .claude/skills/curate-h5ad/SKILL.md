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

### Privacy scan — ethnicity and race columns only

Neither validator finds privacy-sensitive columns under non-canonical names. The schema forbids exactly two obs columns by name — `self_reported_ethnicity` and `self_reported_ethnicity_ontology_term_id`, each carrying `requirement_level: forbidden` — and `strip_forbidden_obs_columns` removes those same two literal names. Anything carrying the same information under another name passes both untouched, so a file can reach `is_valid: true` still holding self-reported ethnicity, which HCA forbids for privacy.

No pattern finds these. Across the breast-v1 source datasets the same data appears as `ethnicity_verbatim`, `ethnicity_grouped`, `reported_ethnicity`, `race` and `self_reported_ethnicity_label` — names sharing no prefix, no suffix and no common substring. They are found by reading the column list and recognising what the words mean, which is your job here rather than a tool's.

So: read `obs_columns` from the evaluator's summary and identify any column that appears to carry **ethnicity or race tied to a subject**.

**Exclude the two canonical names.** `self_reported_ethnicity` and `self_reported_ethnicity_ontology_term_id` are handled by `strip_forbidden_obs_columns`, which is Bucket A and runs earlier. Do not list them here as well. They are not schema-named — `requirement_level: forbidden` keeps them out of the tiers `drop_obs_columns` checks — so the tool will accept them, then refuse the whole request on the absent-name check once strip has removed them. Because the tool is all-or-nothing, that refusal drops **nothing**, and the non-canonical columns this scan exists for would ship. This scan covers only the names strip cannot see.

For each remaining candidate, call `get_descriptive_stats` on it and build the case:

| | |
|---|---|
| column | the exact name |
| dtype and unique count | `dtype` and `unique` from the result |
| shape of the values | see the disclosure rule below |
| why | what about the name reads as ethnicity or race |

**Do not reproduce the data you are trying to remove.** Reading values is how you judge, but every value you write down survives in the curation report saved to disk beside the h5ad — a file `drop_obs_columns` never touches, and which outlives the column you dropped. So:

- **Low-cardinality categorical** (roughly ≤20 categories, none rare enough to single out a donor): call `get_descriptive_stats` with `value_counts=True` and list the category names. A closed vocabulary like `White, Asian, Black or African American` is aggregate and safe to show.
- **High-cardinality or free text**: do **not** pass `value_counts=True`, and do not quote values. Report the unique count and characterise the shape — "free-text ethnicity descriptions, most unique to one donor". `value_counts=True` there returns nearly the whole column, which would copy the data into the report wholesale. **The default response is not safe to paste either**: `top` and `freq` are always present for a non-numeric column, and `top` is a verbatim value — one real donor's ethnicity string. Quote neither.
- **Numeric dtype** (e.g. race stored as integer codes): the numeric branch returns quartiles and no `unique`, so the fields above are unavailable. Report that the column is numeric-coded and say you could not characterise it without reading values — do not read them to fill the table in.
- **A rare category that identifies one or two donors** is not aggregate. Say a rare category exists and give its count; do not name it.

If you are unsure which case applies, compare `unique` against the row count — `n_rows` in this tool's result, or `n_obs` from `get_summary` — and default to not quoting.

Candidates go to **B1** — they block, and each needs approve-or-strike from the wrangler individually. Never propose a glob or a name pattern; always enumerate.

**Scoped to ethnicity and race, and nothing else.** Do not extend it by analogy to other fields that feel sensitive — `donor_id`, `age_*`, `disease`, geography, clinical notes. Those are legitimate HCA metadata, several are required, and proposing them for deletion is out of scope for this skill. HCA forbids self-reported ethnicity specifically; that is the whole of what this scan is for. Note the tool will not save you here: it refuses columns the schema names, but a clinical field under a producer name — `dx_notes`, `donor_origin_country` — is not schema-named and would drop if you asked.

**Flag liberally within that scope.** A false positive costs one struck line; a false negative ships ethnicity data.

**And say what this does not establish.** A column you did not flag is **not** thereby cleared — this step reduces the risk, it does not eliminate it. An obscurely-named column produces a clean-looking report on a file that still carries the data. That sentence belongs in the saved report, not just this conversation — Step 5 requires it in the Summary, which ships whether or not anything was dropped.

## Step 2 — Classify every finding into one bucket

### Bucket A — Mechanical (safe to run after approval)

Only these are in Bucket A. Nothing else. A row belongs in A only when its preconditions are **already satisfied** at punch-list time — don't pre-list rows whose inputs depend on an unanswered B question (e.g. `set_uns('default_embedding', …)` belongs in B2 until the wrangler picks a value, then gets promoted to A per Step 3).

- **`convert_cellxgene_to_hca`** — when `check_schema_type` reports `schema: "cellxgene"`. Must run **first**: it reshapes the file into HCA layout before any other fix makes sense, and the other tools (including `validate_schema`) assume HCA layout. Strips the HCA-forbidden SRE columns (`self_reported_ethnicity_ontology_term_id`, `self_reported_ethnicity`) as a side-effect — so for CellxGENE-layout inputs, the SRE problem is handled here. After conversion, re-enter Step 1 on the converted file to get an accurate Bucket A/B/C list.
- **`strip_forbidden_obs_columns`** — when the file is **HCA-layout** AND either `obs['self_reported_ethnicity']` or `obs['self_reported_ethnicity_ontology_term_id']` is present. Mechanically removes the privacy-forbidden columns and updates `obs[column-order]`. Required prerequisite for `populate_labels` (which refuses while SRE is present), so this should run early in the Bucket A sequence on HCA-layout inputs. On CellxGENE-layout inputs the tool refuses — `convert_cellxgene_to_hca` is the correct entry point there.
- **`drop_obs_columns`** — for columns the wrangler approved individually in Step 3, and only those. In this skill that means the privacy candidates from the Step 1 scan; the free-text-label case in Bucket C also points here, but it is a Bucket C decision that reaches Bucket A the same way, by the wrangler naming the column. This tool never acts on a column the skill chose by itself. Takes an **enumerated list of column names** — never a glob, never a pattern. The tool is all-or-nothing: the whole request is validated before anything is written, so if any name fails a check the file is untouched and every problem is reported together. It refuses any column the HCA schema names (required or optional) and the obs index, refuses a name that isn't present, and refuses when anything else references the column — so an approved list cannot quietly break the file. It deletes `uns['<column>_colors']` alongside each dropped column, since an orphaned palette is a validator error. Note it does **not** shrink the file: HDF5 doesn't reclaim freed space in place, which is one reason `compress_h5ad` runs last.
- **`normalize_raw`** — when `check_x_normalization` reports `verdict: "raw_counts"`, whether or not `has_raw_x` is true. Deterministic, and which of two things it does depends on `raw.X`. With **no `raw.X`**, it moves X→raw.X and normalizes X with `normalize_total(target_sum=10000) + log1p`. With a **`raw.X` that is the same matrix as X** — normalization never ran, so both hold the raw counts — it leaves `raw.X` untouched and normalizes X alone. A `raw.X` that *differs* from X is a genuinely different file and the tool refuses. It also refuses when `raw.X` does not itself hold counts, and reports a no-op (writing nothing) when `raw.X` holds counts and X is already normalized, which is the target layout.
- **`replace_placeholder_values` on `library_preparation_batch`** — only if the column actually contains placeholder values flagged by the validator.
- **`replace_placeholder_values` on `library_sequencing_run`** — same condition.
- **`populate_labels`** — the labeling tool for HCA-layout files, whatever state their controlled columns are in. Per-column fill/verify for the 5 var `feature_*` columns + 7 obs ontology labels. Missing or all-NaN columns get filled from canonical (term_id → ontology label for obs; Ensembl ID → GENCODE for var); when columns are partially populated, every populated row is verified against canonical, and only NaN rows get filled (the whole column refuses with row-level evidence if any populated row mismatches). Does NOT write `observation_joinid` (HCA reserved-but-not-required; the value is deterministic per cell index but writing it is `label_h5ad`'s scope, not the populator's). Refuses on `obs['self_reported_ethnicity']` or `obs['self_reported_ethnicity_ontology_term_id']` present — those two exact names, not a prefix match (run `strip_forbidden_obs_columns` first) — plus non-human organism, CellxGENE layout (`uns['schema_version']` present), or any CellxGENE-derived markers — `uns['provenance']['cellxgene']`, `obs['observation_joinid']`, or an `import_cellxgene` edit-log entry — since add-labels already wrote everything canonically upstream.

  `label_h5ad` is **not** part of this flow — it writes `observation_joinid`, which makes `populate_labels` refuse the file from then on. See the labeling decision tree in Step 4 for why.
- **`copy_cap_annotations`** — only if the wrangler provided a CAP source file in Step 3. Copies annotation sets + `cellannotation_schema_version` + `cellannotation_metadata` from the source into the target. Partial overlap is allowed: ≤5% of cells may be missing on either side (i.e. `cells.missing_from_hca.pct` and `cells.missing_from_cap.pct` must both be ≤5); HCA rows absent from CAP get NaN in the new CAP columns. If either side exceeds 5% missing the tool aborts — treat that as a Bucket B item and bring it back to the wrangler (usually the CAP source is stale or wrong). Gene-axis overlap is recorded but does not gate the copy: a CAP source with extra genes is fine.
- **`compress_h5ad`** — when `get_storage_info` shows no HDF5 filter on X's underlying dataset (`X.data.compression` for sparse X, `X.compression` for dense X). If the file is already compressed, the tool safely returns `{skipped: true, reason: ...}` rather than rewriting. Pure compression, no data change.

### Bucket B — Needs wrangler input (todo — stop and ask)

Split these into two classes so the wrangler sees which items actually block validation vs. which are recommended-but-optional. The primary blocking signal is `validate_schema` — any error it reports (on `obs`, `var`, or `uns`) blocks. Use `list_uns_fields` as a secondary signal for missing `uns` fields specifically: `required: true` fields that are unset are blocking; `required: false` fields that are unset are recommended at most.

For each item, write a concrete question. For **B1** items, do not include a suggested answer — ask only for the missing required value. For **B2** items, if there's an obvious single valid option (e.g. only one 2D embedding exists), you may phrase it as a confirmation question ("`X_umap` — confirm?") rather than silently deciding.

**B1 — Blocking (validator errors or unset `required: true` fields)**

- Missing required `uns` fields (e.g. `study_pi`) — ask for the value(s).
- **Privacy-sensitive obs columns found by the Step 1 scan.** One row per column, each awaiting approve-or-strike on its own — approving one is not approving the rest. Give the case, not just the name: dtype, unique count, the value shape **as the disclosure rule in Step 1 permits it**, and what reads as ethnicity or race. That rule governs here too, and it matters more than it looks: declined and unresolved B1 items are re-rendered in the saved report's *Still to do* table, so anything quoted here lands on disk even for a column the wrangler chose to keep. Ask plainly whether to drop each; approved columns become a single `drop_obs_columns` call in Step 4 with those names enumerated. **Before that call, restate the exact column list and require an explicit yes to that list.** A general "drop the ones you flagged" is not naming — echo the names back and wait. Silence is never approval. If the wrangler declines a column, record that in the report — a deliberate keep and an unnoticed column should not look the same to the next reader.
- **No CAP annotation set present** — the file must ship with at least one CAP annotation set (see the [HCA Cell Annotation schema](https://data.humancellatlas.org/metadata/cell-annotation)). Ask the wrangler to provide a local path to a CAP-exported version of this file (same cells, with CAP annotation sets populated) — `copy_cap_annotations` reads the source via AnnData/h5py so a URL must be downloaded locally first. If supplied, `copy_cap_annotations` becomes a mechanical fix for Step 4.
- Any other `uns` field the validator flags as missing.

**B2 — Recommended (optional fields the wrangler may want to set)**

Only the fields explicitly named below belong in B2. Do **not** scan `list_uns_fields` for other unset optional fields and invent questions about them — a field being optional-and-unset is not itself a reason to ask. The skill's scope is the explicit tool list (`convert_cellxgene_to_hca`, `strip_forbidden_obs_columns`, `drop_obs_columns`, `normalize_raw`, `replace_placeholder_values`, `populate_labels`, `copy_cap_annotations`, `set_uns` on the named fields here, `compress_h5ad`); everything else is the wrangler's call, unprompted.

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
- File carries `uns['schema_version']` — signals CellxGENE layout, i.e. it has already been through `cellxgene-schema add-labels`. `populate_labels` refuses to run (it checks that key specifically, not `schema_reference`). The path is `convert_cellxgene_to_hca` (Bucket A, runs first), not a request to upstream. Do not strip the key by hand.
- Any `obs['organism_ontology_term_id']` value other than `NCBITaxon:9606` — `populate_labels` is human-only. Supporting another organism is a code change, not a curation fix.
- A populated label **disagrees** with its `*_ontology_term_id` (or with GENCODE, for the var `feature_*` columns). A pre-populated column is *not* by itself a blocker, but a conflicting one blocks **the whole run**: `populate_labels` classifies every column first and writes nothing at all if any of them mismatches, so one bad column also withholds the fills that would have succeeded. Its report groups each disagreement by (term ID, file label) with row counts, e.g.:

  > `obs['tissue']: 4812 rows labeled 'lung' but tissue_ontology_term_id is 'UBERON:0002097' (canonical label: 'skin of body'). Either fix tissue_ontology_term_id to match the label, or fix the label to match tissue_ontology_term_id.`

  It deliberately does not choose a side. A mismatch means the label and the term ID disagree, and only someone who knows the dataset can say whether the producer mislabeled the cells or picked the wrong ontology term — guessing wrong corrupts real biological metadata. Bring the tool's verbatim message to the curator; every conflicting column has to be resolved before any labeling lands.

- A label column is present but its `*_ontology_term_id` source column is **absent** — e.g. free-text `obs['cell_type']` with no `cell_type_ontology_term_id`, which the schema permits since that term-id column is optional. `populate_labels` refuses that column (it can neither verify nor fill without the source), and per the item above that blocks the whole run. No mismatch is involved, so this reads differently from a disagreement: upstream needs to supply the term IDs, or the free-text column has to go (`drop_obs_columns` removes producer columns the schema doesn't name). The same applies to the `raw.var` `feature_*` mirrors, which are classified independently and can refuse on their own.
- File carries `uns['cellannotation_metadata']` or other CAP-related uns keys that aren't structurally a dict (e.g. legacy non-dict serializations) — the cell-annotation validator catches these; report verbatim and bring to the CAP curator. (Note: the previous-generation issue here — SRE columns on HCA-layout inputs — now has a Bucket A path via `strip_forbidden_obs_columns`. CellxGENE-layout inputs are still handled by `convert_cellxgene_to_hca` as a side-effect.)
- Any `validate_cell_annotation` error other than `NO_SETS_ERROR` (e.g. missing required `--<suffix>` obs columns on an annotation set, malformed `cellannotation_schema_version`, per-set metadata not a dict). These are CAP-side structural defects — `copy_cap_annotations` faithfully copies what the CAP source provides, so the fix has to land in the CAP export. Surface the validator's verbatim error so the curator can ask the CAP team for a corrected export. (The `NO_SETS_ERROR` case is the B1 "no CAP source provided yet" workflow above.)

## Step 3 — Present the punch list

Show these sections: **A (will run)**, **B1 (blocking — needs your answer)**, **B2 (recommended — optional)**, **C (still to do, out of scope)**. Then stop and wait for explicit approval before running anything.

If the wrangler answers any Bucket B items (B1 or B2), promote those to Bucket A as the appropriate mechanical action: `set_uns` for answered `uns` values (e.g. `default_embedding`, `study_pi`), `copy_cap_annotations` when the answer is a CAP source file path, `drop_obs_columns` for privacy columns approved by name.

## Step 4 — Run the mechanical fixes

Order:

1. `convert_cellxgene_to_hca` first if applicable — then stop, re-run Steps 1–3 on the converted file before continuing (conversion changes the layout enough that the prior punch list is stale).
2. `strip_forbidden_obs_columns` next if applicable (HCA-layout input with SRE columns present) — must run before `populate_labels`, which refuses while SRE is present. On CellxGENE-layout inputs this is unnecessary; the convert step above already stripped them.
3. `drop_obs_columns` if the wrangler approved any privacy columns in Step 3 — one call, approved names enumerated. **This step is independent of step 2**: a file with no canonical SRE columns skips that step and still reaches this one, which is the normal shape for the producer-named columns this targets. Removal belongs ahead of the content edits so labeling and CAP see the column set the file actually ships. It does not shrink the file; `compress_h5ad` at the end repacks.

   All three of its refusals leave the file untouched — that is the tool working, not a failure to route around:
   - `uns['batch_condition']` names one of the columns → resolving that is a Bucket C decision for the wrangler, not a reason to drop fewer columns.
   - The file uses the deprecated legacy CAP layout → refused wholesale regardless of which columns were named (see Bucket C). Report it as a CAP-layout problem, not a column problem.
   - A requested name contains `--` while `uns['cap_metadata']` is present → that is a CAP annotation-set column; bring it to the CAP curator.

   Report the refusal verbatim and re-plan; never retry with a trimmed list to get past it.
4. Content edits, in this order: `normalize_raw`, each `replace_placeholder_values`, **labeling step** (decision tree below), `copy_cap_annotations` (if a source was supplied), and any `set_uns` approved in Step 3. Whichever labeling tool ran (if any) must precede `copy_cap_annotations` — `copy_cap_annotations` calls `validate_marker_genes`, which reads `var['feature_name']`; populating it first gives marker-gene validation canonical gene symbols to match against.

   **Labeling decision tree** — exactly one branch fires (or zero, when no labeling is needed):

   * **CellxGENE-derived file** (any of: `uns['schema_version']` present, `uns['provenance']['cellxgene']` present, `obs['observation_joinid']` present, `import_cellxgene` in edit log) → **skip labeling**. The file's controlled label columns were already populated canonically by `cellxgene-schema add-labels` upstream and preserved through any conversion, and `populate_labels` correctly refuses on these files.
   * **Any other HCA-layout file** → run **`populate_labels`**, whether the controlled columns are partly filled or absent entirely. You do not need to classify the file first — the tool decides per column: it fills from canonical wherever the `*_ontology_term_id` source carries values, verifies a partly-filled column row by row before filling only its NaN rows, and no-ops on a column it can neither verify nor fill.

   If neither branch fits cleanly (e.g. file has SRE present), `populate_labels` surfaces a refusal pointing at the prerequisite (`strip_forbidden_obs_columns` etc.) — handle that first and re-classify.

   `label_h5ad` is deliberately absent from this tree. It fills the same labels, but also writes `obs['observation_joinid']` — a column HCA has no use for, and whose presence makes `populate_labels` refuse the file from then on. Labeling with it is therefore a one-way door: the labels can never be refreshed after an ontology update. It also refuses outright if any controlled column is already populated, where `populate_labels` verifies those rows and fills the rest.

   Note it is *not* a route to a CellxGENE-ready file either: `HCALabeler` applies the HCA schema and deliberately skips the CellxGENE `uns` writes (`schema_version`, `schema_reference`, `organism`), and its preflight refuses a file that already carries them. Do not reach for it on the assumption that it serves a CellxGENE handoff.
5. `compress_h5ad` last.

Each tool writes a new timestamped file. For most subsequent calls, passing either the original path or the latest works — `resolve_latest` picks up the newest variant automatically. Two exceptions: `convert_cellxgene_to_hca` does not auto-resolve (call it with the exact path you want to convert), and `copy_cap_annotations` only auto-resolves its `target_path` (the `source_path` is used verbatim).

## Step 5 — Report

Re-run `view_edit_log` on the final file, then produce a structured report with these sections in order. Also re-run `validate_schema` — but only if `check_schema_type` reports `hca` on the final file. If the file is still CellxGENE (e.g. conversion wasn't approved), skip the validator rerun and note why under "Validator delta" instead of pasting a misleading error list. Use markdown tables; skip any section with no content.

Also re-run `get_cap_annotations` on the final file, and if it reports `has_cap_annotations: true`, run `validate_cell_annotation` on the final file too. This is the structural validator the dataset-validator service runs at upload time under the `hcaCellAnnotation` key — running it here catches issues during curation instead of post-upload. Gate on `has_cap_annotations` directly (not on the edit log) so the validator runs on any file that ships with CAP, including files where the producer pre-attached CAP without going through `copy_cap_annotations`. Its output feeds the **Validator delta** section's cell-annotation rows.

For the Provenance line below, re-run `get_summary` on the final file to fetch its obs columns, then run `get_descriptive_stats` with `columns` set to the intersection of `["donor_id", "sample_id", "library_id"]` and the final file's obs column names (extract `name` from each `{name, dtype}` object in `get_summary.obs_columns`).

### Summary

Two or three sentences distilling the session: which Bucket A operations actually ran, the validator delta in one phrase (e.g. "errors went 4 → 2; remaining errors are Bucket C upstream-data issues"), and a one-clause hand-off (e.g. "Bucket B1 awaiting wrangler input on `study_pi`"). Tight prose paragraph, no nested headings.

End the paragraph with the privacy-scan line, **always, including when the scan found nothing and no column was dropped**: "A privacy scan for ethnicity and race columns was run; columns not flagged by it are not thereby cleared — it reduces privacy risk, it does not eliminate it." A clean file is exactly the case a reader is most likely to mistake for a clearance, and it is the case where every other trace of the scan is omitted: report row 0 only appears when `drop_obs_columns` ran. This sentence is the one that always ships.

Then add an **Outstanding issues** bullet list pulled from Buckets B1, B2, and C — one line per item, no bucket-label prefixes (the reader doesn't need our internal taxonomy). Order: validator errors first, then warnings, then non-validator items. The full detail with action questions lives in the *Still to do* section near the bottom — keep this list tight: one line per item, no inline tables. If all three buckets are empty, replace the bullet list with a single line: "Outstanding issues: none."

### Header
One short paragraph or bullet block with: final file path, shape (`n_obs × n_vars`), `title` from `uns`, schema type (include version only when schema is CellxGENE — HCA is unversioned), X verdict + `raw.X` presence, compression status, `obsm` keys present. Add a **Provenance** line: `N donors · M samples · K libraries` from `get_descriptive_stats.columns[<col>].unique` for each column. Skip any metric whose column wasn't returned or whose `unique` is 0.

### Mechanical fixes applied

| # | Operation | Effect |
|---|---|---|
| 0 | `drop_obs_columns` | Name every column dropped, from the tool's own `obs_columns_dropped`, and say why — e.g. "Dropped `ethnicity_verbatim`, `ethnicity_grouped`, `self_reported_ethnicity_label` — privacy-sensitive ethnicity data under non-canonical names, approved individually." Name the columns, never their values. If the wrangler declined a candidate, record that too, so a deliberate keep is distinguishable from a column nobody looked at. (The "not thereby cleared" caveat lives in the Summary, which ships whether or not this row does.) |
| 1 | `normalize_raw` | e.g. "Moved raw counts → raw.X; normalized X with `normalize_total(target_sum=10000)` + log1p", or "raw.X already held the same counts and was left unmodified; normalized X with `normalize_total(target_sum=10000)` + log1p". The tool's `raw_x` field says which. |
| 2 | `replace_placeholder_values` (`library_preparation_batch`) | e.g. "N cells: `'unknown'` → NaN" |
| 3 | `populate_labels` | Name the columns from the tool's own `filled` and `matched` lists — e.g. "Filled `var['feature_name']`, `feature_reference`, `cell_type`, `tissue`; `assay` and `sex` already matched". The tool returns column names, not row counts, so do not quote per-row figures here unless another tool supplied them. Populated rows are verified against canonical before anything is written, so this step never overwrites producer text. |
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

Source the numbers from the `copy_cap_annotations` tool result's `marker_gene_validation` field if it ran this session. If only a prior `import_cap_annotations` entry exists, call `validate_marker_genes` on the final file to get fresh numbers — a marker list that matched against `var.index` before `populate_labels` filled `var['feature_name']` will look very different now.

Marker symbols are resolved against the target's var gene-name source: `var['feature_name']` is preferred, else `var['gene_name']`, else `var.index` (the Ensembl IDs) as a last resort. Files that went through `populate_labels` have `feature_name` filled wherever GENCODE knew the Ensembl ID; files that skipped labeling fall back to whatever the producer shipped.

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
