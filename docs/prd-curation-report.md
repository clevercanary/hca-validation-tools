# PRD: Curation Report Shape

Status: draft (2026-05-07) — for review, not committed to the skill yet.

## Problem

The persisted markdown report from `/curate-h5ad` is currently shaped around the curator's session: *"these fixes ran in this session, here's the validator delta, here are the buckets we classified items into"*. That serves the operator running the skill, but it doesn't serve the two readers who actually receive the report:

1. **Data generators** receiving the file back from curation. They need to know: *what did the curator change in my file, and what do I still need to fix upstream?*
2. **Future readers** (handoff, audit, weeks later). They need to know: *what is this file, what state is it in, what's still outstanding?*

The session framing also leans on internal taxonomy — "Bucket A / B1 / B2 / C" — that means nothing to anyone outside this skill.

## Goals

- Refocus the report on **the file's current state and outstanding responsibilities**, not on the session that produced it.
- Make it unambiguous **what the curator changed** so data generators can verify their data wasn't broken.
- Make it unambiguous **what the data generator must fix** that the curator can't (bad gene IDs, ontology mismatches, NaN required fields, delimited-list values, etc.).
- Replace the A/B/C bucket labels with descriptive responsibility labels.

## Non-goals

- Preserving the session-narrative shape (validator-delta-style "before/after" table, "fixes applied this session" log as the dominant view). Audit data still lives in the edit log; we just don't lead with it.
- Reproducing the existing PDF's *Session context — tool and skill changes* table. That coupled tooling-PR work to data work; it's not part of the file itself.

## Audiences

| Audience | What they want |
|---|---|
| Data generator | What changed in the file; what they must fix upstream |
| Future reader | Orientation; current state; outstanding actions |
| Curator (in-session) | Confirmation that fixes ran cleanly; deferred action list — this is the *least* primary now |

## Proposed shape

Five sections, file-state-oriented:

### 1. Header — current state snapshot

Same shape as today's Header: file path, shape, title, schema, X verdict + raw.X presence, compression, embeddings, provenance line. No session detail.

### 2. Validation summary

A single-line verdict and counts:

> **Validation: not yet passing — 2 errors, 32 warnings (excluding 2,138 expected feature-ID warnings against GENCODE v48).**

Errors are spelled out verbatim under the line — they're the immediate eye-level "what's blocking" signal. Warnings are summarized by kind/count, not enumerated.

### 3. Validation checklist (the new core)

Every check the validator runs, each with a status symbol and an owner. Two presentation options:

**Option A — comprehensive table (every check, even passing ones).**
Pros: gives the data generator a confidence-list ("47/47 checks evaluated, 2 currently failing"); makes new failures introduced by re-curation easy to spot. Cons: long; lots of repetitive green rows.

**Option B — findings-only with header counts.**
Pros: tight; reads in seconds. Cons: loses the "everything was checked" reassurance; a missing failure could be confused with an absent check.

**Recommendation: Option B with a header line stating the total checks evaluated** ("47 checks evaluated; 2 failing, 5 warnings, 2 fixed during curation, 38 passing"). The body lists only the non-pass + fixed-during-curation rows.

Each row shows:

| Check | Status | Owner | Notes |
|---|---|---|---|
| `obs['library_id']` populated | ✗ Fail | Data generator | 28,633 / 50,296 cells NaN. Validator error. |
| `obs['library_preparation_batch']` single-value | ✗ Fail | Data generator | Some rows hold semicolon-delimited lists. Validator error. |
| Var feature_* labels populated | ✓ Fixed during curation | (curator) | `label_h5ad` populated `var['feature_name']` + 4 sibling columns from Ensembl IDs (34,505 / 35,574 matched GENCODE). |
| Obs ontology labels populated | ✓ Fixed during curation | (curator) | `label_h5ad` wrote 8 derived obs labels from their `_ontology_term_id` columns. |
| `obs['library_preparation_batch']` placeholder values | ✓ Fixed during curation | (curator) | `replace_placeholder_values` removed 464 `'unknown'` cells. |
| CAP marker symbols resolve in GENCODE | ⚠ Warn | Data generator | 2 markers (`H2*`, `STMN`) classified `not_in_gencode`. |
| Var Ensembl IDs in current GENCODE | ⚠ Warn | Data generator | 1,069 IDs unmatched in GENCODE v48 / Ensembl 114 (mirrored in raw.var). |

Status symbols (5 values, picked to be both color-blind safe and skim-able):

- ✓ **Pass** — currently meets the check.
- ✓ **Fixed during curation** — was failing on the file we received; the curator's tools made it pass. The "during curation" annotation comes from any `import_*` / `label_h5ad` / `replace_placeholder_values` / `set_uns` / `normalize_raw` / `compress_h5ad` entry in `uns/provenance/edit_history`. *Not session-bounded* — if a previous curation session fixed it, it still shows here.
- ✗ **Fail** — currently failing. Validator error.
- ⚠ **Warn** — validator warning that isn't expected schema noise (CAP zero-observation warnings, for example, are filtered out and counted separately).
- ➖ **Skipped** — check didn't apply (e.g. CAP marker validation when CAP isn't present).

Owner is one of: `(curator)`, `Data generator`, or `(none — passing)`. The owner field is the key new affordance — it tells data generators which rows belong to them at a glance.

### 4. Curator changes

Audit trail of every edit the curator's tools made to the file, derived from `uns/provenance/edit_history`. Same 4-column table the skill template already uses (`#` / Timestamp / Operation / Description). This is for verification: the data generator can trace every modification.

### 5. Outstanding actions

Two sub-sections, **named by responsibility, no A/B/C**:

#### Data generator must fix

The current Bucket C list. Validator errors and warnings the curator can't address from inside the file: NaN sources, delimited-list values, gene-ID mismatches with GENCODE, CAP marker text quality, label/term-id drift the labeler refused to overwrite, etc.

#### Curator (awaiting input)

The current Bucket B list, merged. Required-but-unset values that need a wrangler decision (`study_pi`, `default_embedding`). One row per question.

Either subsection is omitted when empty.

## Bucket-name → descriptive-name mapping

| Old | New |
|---|---|
| Bucket A | *(no longer surfaced — folded into "Fixed during curation" rows in the checklist)* |
| Bucket B1 | "Curator (awaiting input) — blocking" |
| Bucket B2 | "Curator (awaiting input) — recommended" |
| Bucket C | "Data generator must fix" |

The skill internally can keep the A/B/C taxonomy for routing logic; the report just doesn't expose it.

## Open questions

1. **Comprehensive vs findings-only checklist (Option A vs B)?** Default to B with the count header.
2. **Do we keep the "Validator delta" before/after table?** I think no — it's session-flavored. The checklist's "Fixed during curation" status conveys the same information in a file-state idiom. If we want to retain the visual delta, we could add a tiny header line under "Validation summary": *"This curation has fixed 5 checks since the original file."* Less prominent than today's table.
3. **Where does CAP overlap and CAP marker validation live?** Today they're top-level sections. Proposal: collapse into rows in the validation checklist (`CAP cell overlap ≥ 95%`, `CAP marker symbols resolve in GENCODE`). Data behind those rows still goes in a CAP-specific subsection right after the checklist for the cases where richer detail matters.
4. **Should "Curator changes" precede or follow "Outstanding actions"?** I lean *follow* — outstanding-actions is the call-to-action, curator-changes is reference. Keep the call-to-action up where the eye lands.
5. **Section ordering overall?** Proposed:
   1. Header
   2. Validation summary
   3. Outstanding actions (split by responsibility) ← elevated
   4. Validation checklist
   5. CAP details (overlap + marker validation, when applicable)
   6. Curator changes (edit log audit)

## Tension: checklist vs. fixes log

The user noted this directly: a single-status checklist can mask the fact that an item was fixed by the curator. The proposed `Fixed during curation` status resolves that — it's a distinct value, not collapsed into pass. The data generator can filter the table to that status to see exactly what changed.

## Template — myeloid example

Below is what the report would look like rendered on the current myeloid file under the proposed shape, for review.

```markdown
# Curation report — `myeloid-r1-wip-10-edit-2026-05-07-12-07-56.h5ad`

## Header

- **File**: `/Users/dave/hca-tracker-upload/prod/gut/gut-v1/integrated-objects/myeloid-r1-wip-10-edit-2026-05-07-12-07-56.h5ad`
- **Shape**: 50,296 × 35,574 (424.9 MB)
- **Title**: *Human Gut Cell Atlas (HGCA) v1 - Myeloid*
- **Schema**: HCA (unversioned)
- **X**: `normalized` · `raw.X` present
- **Compression**: gzip level 4 on every dataset
- **Embeddings**: `X_scVI` (50296, 30), `X_umap` (50296, 2)
- **Provenance**: 199 donors · 371 samples · 52 libraries

## Validation summary

**Validation: not yet passing — 2 errors, 32 unexpected warnings.** (2,138 GENCODE feature-ID warnings excluded from the count; 32 CAP zero-observation warnings excluded as expected schema behavior.)

Errors:
- `Column 'library_id' in dataframe 'obs' must not contain NaN values.`
- `Column 'library_preparation_batch' in dataframe 'obs' contains values with list separators (e.g. 'library1; library2; …; library16'). Each value must be a single identifier, not a delimited list.`

## Outstanding actions

### Data generator must fix

| Issue | Detail |
|---|---|
| `obs['library_id']` NaN values | 28,633 / 50,296 cells; populated rows hold comma-concatenated lists. Needs real per-cell values from source. Validator error. |
| `obs['library_preparation_batch']` delimited lists | Some rows hold semicolon-delimited values like `'library1; library2; …; library16'`. Each value must be a single identifier. Validator error. |
| Var Ensembl IDs not in GENCODE v48 | 1,069 distinct IDs unmatched (mirrored in `raw.var` → 2,138 warnings). Annotation-version decision required. |
| CAP marker symbols (`H2*`, `STMN`) | Both classified `not_in_gencode` by `validate_marker_genes` — not in var and not in GENCODE. CAP-side curator decision. |

### Curator (awaiting input)

*(none)*

## Validation checklist

47 checks evaluated · 2 failing · 2 warnings (non-feature-ID) · 6 fixed during curation · 37 passing.

| Check | Status | Owner | Notes |
|---|---|---|---|
| `obs['library_id']` populated | ✗ Fail | Data generator | 28,633 / 50,296 NaN. Validator error. |
| `obs['library_preparation_batch']` single value per row | ✗ Fail | Data generator | Some rows are delimited lists. Validator error. |
| `obs['library_preparation_batch']` no placeholder values | ✓ Fixed during curation | (curator) | `replace_placeholder_values` removed 464 `'unknown'` cells (2026-04-21). |
| `obs['library_sequencing_run']` no placeholder values | ✓ Fixed during curation | (curator) | `replace_placeholder_values` removed 464 `'unknown'` cells (2026-04-21). |
| X is normalized | ✓ Fixed during curation | (curator) | `normalize_raw` moved raw counts to `raw.X` and applied `normalize_total(target_sum=10000) + log1p` (2026-04-21). |
| Var feature_* columns populated | ✓ Fixed during curation | (curator) | `label_h5ad` populated `var['feature_name']` and four sibling `feature_*` columns; 34,505 / 35,574 matched GENCODE (2026-04-21). |
| Obs ontology label columns populated | ✓ Fixed during curation | (curator) | `label_h5ad` wrote 8 obs labels (`tissue`, `cell_type`, `assay`, `disease`, `sex`, `organism`, `development_stage`, `self_reported_ethnicity`) from their `_ontology_term_id` columns (2026-04-21). |
| CAP annotations present | ✓ Fixed during curation | (curator) | `copy_cap_annotations` imported 1 annotation set (`Prelim annotation`) from `HCA Gut Cell Atlas v1 Myeloid Lineage.h5ad` (latest run 2026-05-07). |
| Var Ensembl IDs match current GENCODE | ⚠ Warn | Data generator | 1,069 IDs unmatched in GENCODE v48 / Ensembl 114. |
| CAP marker symbols resolve in GENCODE | ⚠ Warn | Data generator | 2 markers (`H2*`, `STMN`) classified `not_in_gencode`. |

(Passing rows omitted; full count in the header line.)

## CAP details

### Cell overlap

| Metric | Value |
|---|---|
| CAP source file | `HCA Gut Cell Atlas v1 Myeloid Lineage.h5ad` |
| `cells.n_cap` | 52,311 |
| `cells.n_hca` | 50,296 |
| `cells.n_matched` | 49,904 |
| `cells.missing_from_hca` | 2,407 (4.6% of CAP) |
| `cells.missing_from_cap` | 392 (0.8% of HCA) |

### Gene overlap

| Metric | Value |
|---|---|
| `genes.n_cap` | 36,353 |
| `genes.n_hca` | 35,574 |
| `genes.n_matched` | 35,574 |
| `genes.missing_from_hca` | 779 (2.1% of CAP) |
| `genes.missing_from_cap` | 0 (0.0% of HCA) |

### Marker validation

| Metric | Value |
|---|---|
| Total unique markers | 56 |
| Found in var gene-name source | 54 |
| Missing | 2 |

| Marker | Classification | Var name | Ensembl ID |
|---|---|---|---|
| `H2*` | `not_in_gencode` | — | — |
| `STMN` | `not_in_gencode` | — | — |

## Curator changes

Audit trail from `uns/provenance/edit_history`, oldest first.

| # | Timestamp (UTC) | Operation | Description |
|---|---|---|---|
| 1 | 2026-04-21 04:19:10 | `normalize_raw` | Moved raw counts to raw.X and normalized X with normalize_total(target_sum=10000) + log1p |
| 2 | 2026-04-21 04:19:51 | `replace_placeholder_values` | Replaced placeholder values with NaN in `library_preparation_batch` |
| 3 | 2026-04-21 04:19:57 | `replace_placeholder_values` | Replaced placeholder values with NaN in `library_sequencing_run` |
| 4 | 2026-04-21 04:20:03 | `label_h5ad` | Populated var feature_* from Ensembl IDs (34505/35574 matched GENCODE) and 8 obs ontology labels |
| 5 | 2026-04-21 04:20:49 | `import_cap_annotations` | Copied CAP annotations from HCA Gut Cell Atlas v1 Myeloid Lineage.h5ad |
| 6 | 2026-04-21 04:21:05 | `set_uns` | Set uns['default_embedding'] |
| 7–14 | 2026-05-07 | `import_cap_annotations` | 8 re-runs (consolidating tooling iterations on the new shape). |
```

## Decisions to make before implementing

- [ ] Comprehensive vs findings-only checklist (Option A vs B). PRD recommends B.
- [ ] Section ordering — confirmed list above?
- [ ] Whether to keep `Validator delta` (PRD says drop).
- [ ] Whether to collapse CAP overlap/marker into the checklist or keep as a sub-section. PRD: keep sub-section for richer detail, but also surface as one-line checklist rows.
- [ ] Final descriptive names for the responsibility labels — *"Data generator"* and *"Curator (awaiting input)"* read fine but worth team review.

## Implementation notes (deferred)

Once the shape is agreed, the skill changes are:

1. Replace `## Step 5 — Report` body in `curate-h5ad/SKILL.md` with the new section list.
2. Add a parallel template fragment in `evaluate-h5ad/SKILL.md` for the read-only case (no curator changes section, no outstanding actions for the curator).
3. Build the validation-checklist row generator from `validate_schema` errors+warnings + `view_edit_log` entries. Each tool name in the edit log maps deterministically to a set of checks it satisfies.

The mapping in (3) is the meaningful new logic. Worth a follow-up issue to enumerate it explicitly.
