---
name: evaluate-h5ad
description: Evaluate an h5ad file for HCA readiness — checks metadata, compression, embeddings, CAP annotations, and edit history.
argument-hint: <absolute-path-to-h5ad-file>
---

# Evaluate H5AD File

Evaluate the h5ad file at absolute path: `$ARGUMENTS`

Pass an absolute path to the `.h5ad` file. Relative paths are resolved against the MCP server's working directory, which may not match the user's, so they can silently evaluate the wrong file.

Run all of the following MCP tool calls in parallel to gather data:

1. **get_summary** — cell/gene counts, obs/var columns, uns keys, layers, obsm
2. **get_storage_info** — compression, chunking, sparse format, file size
3. **check_schema_type** — report CellxGENE vs HCA layout and schema version
4. **check_x_normalization** — classify X as raw_counts / normalized / indeterminate
5. **list_uns_fields** — HCA schema field completeness (required vs set vs missing)
6. **get_cap_annotations** — CAP cell annotation sets, if present
7. **view_edit_log** — read `uns/provenance/edit_history` so edit history is already in hand when synthesizing the report

Then synthesize the results into a report with these sections in order. Use markdown tables wherever multiple items share the same shape; keep prose tight.

## 1. File overview
One compact block (bullets or a short table) with:
- Final file path (resolved snapshot, not the input path if they differ)
- Shape: `n_obs × n_vars`, file size (MB)
- `title` from `uns`
- Schema type + version (from `check_schema_type`)
- X verdict (from `check_x_normalization`: `raw_counts` / `normalized` / `indeterminate`) + whether `raw.X` is present

## 2. HCA metadata readiness

| Category | Missing |
|---|---|
| Required (schema-wide) | list the `missing_required` field names |
| Required (bionetwork) | list the `missing_required_bionetwork` field names |
| Extra uns keys (not in schema) | list any `extra_uns_keys` |

If nothing is missing, say so in a single line instead of an empty table.

## 3. Storage & compression

| Dataset | Codec | Level | Chunks |
|---|---|---|---|
| X.data | gzip / — | 4 / — | … |
| raw/X.data | gzip / — | 4 / — | … |

Flag any uncompressed dataset in a >100 MB file as an issue.

## 4. Embeddings
- List each `obsm` key with its shape.
- Does `uns['default_embedding']` exist? Does it name a real `obsm` key?

## 5. CAP annotations
- Are CAP annotation sets present? If yes, name them and give the cell-label count per set. If no, state that CAP is missing.
- If `view_edit_log` contains any `import_cap_annotations` entries, render the latest entry's overlap stats as a table (this shows how faithfully CAP aligns to the current cells):

| Metric | Value |
|---|---|
| CAP source file | `cap_source_file` |
| `source_n_obs` | … |
| `target_n_obs` | … |
| `matched_n_obs` | … |
| `match_fraction_of_source` | as % |
| `match_fraction_of_target` | as % |

## 6. Edit history
Summarize entries as a table: `timestamp`, `operation`, one-line `description`. If absent, note that the file hasn't been edited through `hca-anndata-tools`.

## 7. Summary & recommendations
- One-line readiness verdict: ready / needs work / not started.
- Prioritized list of next actions, most important first.
- If `check_schema_type` reported `cellxgene`, the first action is `convert_cellxgene_to_hca`.
