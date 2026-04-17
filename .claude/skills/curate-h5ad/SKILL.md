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

Run in parallel:

- `/evaluate-h5ad $ARGUMENTS` — produces the structured overview report (schema type, X verdict, metadata, storage, embeddings, CAP, edit history, summary). This already calls `check_schema_type` and `check_x_normalization`, so their verdicts are available for Step 2 gating without a separate tool call.
- `validate_schema` — the HCA schema validator (`is_valid`, full `errors` and `warnings` lists). These are the authoritative blocking/advisory signals for Bucket A decisions. Feature-ID warnings are ordered last; summarize repeated shapes in the punch list rather than pasting thousands of lines verbatim.

## Step 2 — Classify every finding into one bucket

### Bucket A — Mechanical (safe to run after approval)

Only these are in Bucket A. Nothing else.

- **`convert_cellxgene_to_hca`** — when `check_schema_type` reports `schema: "cellxgene"`. Must run **first**: it reshapes the file into HCA layout before any other fix makes sense, and the other tools assume HCA layout. After conversion, re-run the validator + evaluator on the new file to get an accurate Bucket A/B/C list.
- **`normalize_raw`** — when `check_x_normalization` reports `verdict: "raw_counts"` and `has_raw_x: false`. Deterministic: moves X→raw.X, normalizes X with `normalize_total(target_sum=10000) + log1p`.
- **`replace_placeholder_values` on `library_preparation_batch`** — only if the column actually contains placeholder values flagged by the validator.
- **`replace_placeholder_values` on `library_sequencing_run`** — same condition.
- **`copy_cap_annotations`** — only if the wrangler provided a CAP source file in Step 3. Copies annotation sets + `cellannotation_schema_version` + `cellannotation_metadata` from the source into the target.
- **`compress_h5ad`** — when `get_storage_info` shows `compression: null` on X. Pure compression, no data change.

### Bucket B — Needs wrangler input (todo — stop and ask)

For each of these, write a concrete question, not a suggested answer:

- Missing required `uns` fields (e.g. `description`) — ask for the text.
- Missing bionetwork-required `uns` fields (e.g. `ambient_count_correction`, `doublet_detection`) — ask which value from the allowed set applies. If `predicted_doublet` / `doublet_score` columns exist, mention that as context but still ask which tool was used.
- `default_embedding` — list the obsm keys and ask which one.
- **No CAP annotation set present** — the file must ship with at least one CAP annotation set (see the [HCA Cell Annotation schema](https://data.humancellatlas.org/metadata/cell-annotation)). Ask the wrangler to provide a path or URL to a CAP-exported version of this file (same cells, with CAP annotation sets populated). If supplied, `copy_cap_annotations` becomes a mechanical fix for Step 4.
- Any other `uns` field the validator flags as missing.

If the wrangler answers during the session, those answers become additional mechanical fixes (`set_uns ...`, `copy_cap_annotations`, ...) to run in Step 4.

### Bucket C — Upstream / curator judgment (out of scope for this skill)

Report these but don't attempt to fix:

- High NaN rates on non-allowed columns (e.g. `library_id`) — needs real values from source.
- Delimited-list values in single-identifier columns (e.g. `library_preparation_batch` containing `"lib1; lib2; lib3"`) — needs per-cell resolution, not placeholder replacement.
- Gene IDs missing from the current GENCODE — needs annotation-version decision.
- Inconsistent `author_cell_type` variants — needs a curator mapping.
- (CAP annotations are handled in Bucket B above — the wrangler provides a CAP source file and `copy_cap_annotations` runs mechanically.)
- Cells whose labels don't match the atlas focus (e.g. non-myeloid labels in a myeloid atlas) — needs a curator decision on keep/drop.

## Step 3 — Present the punch list

Show three sections: **A (will run)**, **B (needs your answer)**, **C (still to do, out of scope)**. Then stop and wait for explicit approval before running anything.

If the wrangler answers any Bucket B items, promote those to Bucket A as `set_uns` calls.

## Step 4 — Run the mechanical fixes

Order:

1. `convert_cellxgene_to_hca` first if applicable — then stop, re-run Steps 1–3 on the converted file before continuing (conversion changes the layout enough that the prior punch list is stale).
2. Content edits: `normalize_raw`, each `replace_placeholder_values`, `copy_cap_annotations` (if a source was supplied), and any `set_uns` approved in Step 3.
3. `compress_h5ad` last.

Each tool writes a new timestamped file. Subsequent calls can pass either the original path or the latest — `resolve_latest` picks up the newest variant automatically.

## Step 5 — Report

- Call `view_edit_log` on the final file; list the entries added this session.
- Re-run the validator; report error/warning deltas vs. Step 1.
- Summarize:
  - **Fixed this session** — each Bucket A action that ran, with the resulting validator change.
  - **Still to do** — every Bucket B question the wrangler didn't answer, plus every Bucket C item.
