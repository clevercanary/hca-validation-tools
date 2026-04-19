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

Only these are in Bucket A. Nothing else.

- **`convert_cellxgene_to_hca`** — when `check_schema_type` reports `schema: "cellxgene"`. Must run **first**: it reshapes the file into HCA layout before any other fix makes sense, and the other tools (including `validate_schema`) assume HCA layout. After conversion, re-enter Step 1 on the converted file to get an accurate Bucket A/B/C list.
- **`normalize_raw`** — when `check_x_normalization` reports `verdict: "raw_counts"` and `has_raw_x: false`. Deterministic: moves X→raw.X, normalizes X with `normalize_total(target_sum=10000) + log1p`.
- **`replace_placeholder_values` on `library_preparation_batch`** — only if the column actually contains placeholder values flagged by the validator.
- **`replace_placeholder_values` on `library_sequencing_run`** — same condition.
- **`copy_cap_annotations`** — only if the wrangler provided a CAP source file in Step 3. Copies annotation sets + `cellannotation_schema_version` + `cellannotation_metadata` from the source into the target. Partial overlap is allowed: the source and target obs indexes only need to match at ≥95% in both directions (target-covered and source-covered); target rows absent from source get NaN in the new CAP columns. If the overlap is below 95% the tool aborts — treat that as a Bucket B item and bring it back to the wrangler (usually the CAP source is stale or wrong).
- **`compress_h5ad`** — when `get_storage_info` shows no HDF5 filter on X's underlying dataset (`X.data.compression` for sparse X, `X.compression` for dense X). If the file is already compressed, the tool safely returns `{skipped: true, reason: ...}` rather than rewriting. Pure compression, no data change.

### Bucket B — Needs wrangler input (todo — stop and ask)

Split these into two classes so the wrangler sees which items actually block validation vs. which are recommended-but-optional. Ground the split in `list_uns_fields` output: `required: true` fields that are unset are blocking; `required: false` fields that are unset are recommended at most.

For each item, write a concrete question — not a suggested answer.

**B1 — Blocking (validator errors or unset `required: true` fields)**

- Missing required `uns` fields (e.g. `study_pi`) — ask for the value(s).
- **No CAP annotation set present** — the file must ship with at least one CAP annotation set (see the [HCA Cell Annotation schema](https://data.humancellatlas.org/metadata/cell-annotation)). Ask the wrangler to provide a local path to a CAP-exported version of this file (same cells, with CAP annotation sets populated) — `copy_cap_annotations` reads the source via AnnData/h5py so a URL must be downloaded locally first. If supplied, `copy_cap_annotations` becomes a mechanical fix for Step 4.
- Any other `uns` field the validator flags as missing.

**B2 — Recommended (optional fields the wrangler may want to set)**

- `default_embedding` — list the obsm keys and ask which one. Optional per schema, but a file shipped without it will display in CELLxGENE Explorer with no default scatter. Must name a 2D embedding to actually plot; 30D latents (e.g. `X_scVI`) are valid per schema but won't display. If only one 2D embedding exists, surface that — the wrangler will almost certainly pick it.
- Any other field where `list_uns_fields` reports `required: false` and `is_set: false` — mention only if there's a reason the wrangler might care; otherwise omit.

If the wrangler answers during the session, those answers become additional mechanical fixes (`set_uns ...`, `copy_cap_annotations`, ...) to run in Step 4.

### Bucket C — Upstream / curator judgment (out of scope for this skill)

Report these but don't attempt to fix:

- High NaN rates on non-allowed columns (e.g. `library_id`) — needs real values from source.
- Sparse or missing `ambient_count_correction` / `doublet_detection` obs columns — per-cell values must come from the upstream source (each source dataset's processing record). Do not broadcast a single value. Report fill rate and move on.
- Delimited-list values in single-identifier columns (e.g. `library_preparation_batch` containing `"lib1; lib2; lib3"`) — needs per-cell resolution, not placeholder replacement.
- Gene IDs missing from the current GENCODE — needs annotation-version decision.
- Inconsistent `author_cell_type` variants — needs a curator mapping.
- (CAP annotations are handled in Bucket B above — the wrangler provides a CAP source file and `copy_cap_annotations` runs mechanically.)
- Cells whose labels don't match the atlas focus (e.g. non-myeloid labels in a myeloid atlas) — needs a curator decision on keep/drop.

## Step 3 — Present the punch list

Show these sections: **A (will run)**, **B1 (blocking — needs your answer)**, **B2 (recommended — optional)**, **C (still to do, out of scope)**. Then stop and wait for explicit approval before running anything.

If the wrangler answers any Bucket B items (B1 or B2), promote those to Bucket A as `set_uns` calls.

## Step 4 — Run the mechanical fixes

Order:

1. `convert_cellxgene_to_hca` first if applicable — then stop, re-run Steps 1–3 on the converted file before continuing (conversion changes the layout enough that the prior punch list is stale).
2. Content edits: `normalize_raw`, each `replace_placeholder_values`, `copy_cap_annotations` (if a source was supplied), and any `set_uns` approved in Step 3.
3. `compress_h5ad` last.

Each tool writes a new timestamped file. For most subsequent calls, passing either the original path or the latest works — `resolve_latest` picks up the newest variant automatically. Two exceptions: `convert_cellxgene_to_hca` does not auto-resolve (call it with the exact path you want to convert), and `copy_cap_annotations` only auto-resolves its `target_path` (the `source_path` is used verbatim).

## Step 5 — Report

Re-run `view_edit_log` and the validator on the final file, then produce a structured report with these sections in order. Use markdown tables; skip any section with no content.

### Header
One short paragraph or bullet block with: final file path, shape (`n_obs × n_vars`), `title` from `uns`, schema type + version, X verdict + `raw.X` presence, compression status, `obsm` keys present.

### Mechanical fixes applied

| # | Operation | Effect |
|---|---|---|
| 1 | `normalize_raw` | e.g. "Moved raw counts → raw.X; normalized X with `normalize_total(target_sum=10000)` + log1p" |
| 2 | `replace_placeholder_values` (`library_preparation_batch`) | e.g. "N cells: `'unknown'` → NaN" |
| 3 | `copy_cap_annotations` | name the CAP source file |
| 4 | `compress_h5ad` | e.g. "Skipped — already gzipped" or "Rewrote X with gzip level 4" |

Only include the rows for tools that actually ran this session.

### Validator delta

|  | Before | After |
|---|---|---|
| Errors | N | M |
| Non-feature-ID warnings | N | M |
| CAP zero-observation warnings | N | M |
| Named warnings resolved | — | e.g. "raw.X absent", "`unknown` placeholder in `library_preparation_batch`" |

Count **CAP "zero observations" warnings** (text: `contains a category '...' with zero observations`) separately from other warnings. These are *expected* after `copy_cap_annotations`: CAP declares a closed vocabulary per annotation set that spans all lineages, and a per-lineage file only realizes a subset — unused vocabulary terms are intentional schema information, not a defect. Report the count and move on; don't prune them. The validator's `--add-labels` remediation note comes from vendored CellxGENE code and does not apply to HCA.

Also list the specific error/warning kinds that disappeared or newly appeared, one line each.

### CAP overlap (only if `copy_cap_annotations` ran this session, or a prior `import_cap_annotations` entry is in the edit log)

Pull from the latest `import_cap_annotations` entry's `details`:

| Metric | Value |
|---|---|
| CAP source file | `cap_source_file` |
| `source_n_obs` | … |
| `target_n_obs` | … |
| `matched_n_obs` | … |
| `match_fraction_of_source` | as % |
| `match_fraction_of_target` | as % |

### Still to do

**Bucket B1 — blocking (validator errors or unset `required: true` fields)**

| Field | Question |
|---|---|
| `ambient_count_correction` | which value from the allowed set? |

**Bucket B2 — recommended (optional)**

| Field | Question |
|---|---|
| `default_embedding` | `X_umap` (only 2D option) — confirm? |

**Bucket C — upstream / curator**

| Issue | Detail |
|---|---|
| `library_id` NaN (validator error) | Needs real values from source |

Only surface items that are still open — don't re-list anything resolved this session. Omit any of the three sub-tables that have no entries.
