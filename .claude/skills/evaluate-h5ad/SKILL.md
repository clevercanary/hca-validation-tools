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
3. **check_schema_type** — report CellxGENE vs HCA layout (CellxGENE carries a schema version; HCA is not versioned so skip the version for HCA files)
4. **check_x_normalization** — classify X as raw_counts / normalized / indeterminate
5. **list_uns_fields** — HCA schema field completeness (required vs set vs missing)
6. **get_cap_annotations** — CAP cell annotation sets, if present
7. **view_edit_log** — read `uns/provenance/edit_history` so edit history is already in hand when synthesizing the report

Then, only if `get_cap_annotations` reports `has_cap_annotations: true`, call both of these in parallel:
- **validate_marker_genes** — CAP marker-gene coverage against the target's var gene-name source (`var['feature_name']` preferred, else `var['gene_name']`, else `var.index`).
- **validate_cell_annotation** — HCA Cell Annotation structural checks (annotation-set presence, well-formed `cellannotation_schema_version`, per-set metadata is a dict, required `--<suffix>` obs columns). This is the validator the dataset-validator service runs under the `hcaCellAnnotation` key at upload time; running it here surfaces issues during curation instead of post-upload.

The `has_cap_annotations` gate already implies HCA-layout, so both tools have what they need; skipping on non-CAP files avoids redundant calls (and on a no-CAP file `validate_cell_annotation` would only emit the obvious `NO_SETS_ERROR`).

After **get_summary** returns, also run **get_descriptive_stats** with `columns` set to the intersection of `["donor_id", "sample_id", "library_id"]` and the obs column names from `get_summary.obs_columns` (which is a list of `{name, dtype}` objects — extract `name`). Depends on `get_summary`, so this step is sequential, not part of the parallel batch. Used only for the Provenance bullet in Section 1.

Then synthesize the results into a report with these sections in order. Use markdown tables wherever multiple items share the same shape; keep prose tight.

## 1. File overview
One compact block (bullets or a short table) with:
- Input path (`$ARGUMENTS`). If the tools auto-resolved to a newer snapshot, add the resolved basename on a second line — read it from any tool that returns a `filename` field (e.g. `check_schema_type.filename`). Skip the second line when input and resolved agree.
- Shape: `n_obs × n_vars`, file size (MB)
- `title` from `uns`
- Schema type (from `check_schema_type`) — include the version only when schema is CellxGENE (HCA is unversioned)
- X verdict (from `check_x_normalization`: `raw_counts` / `normalized` / `indeterminate`) + whether `raw.X` is present
- Provenance: render `N donors · M samples · K libraries` from `get_descriptive_stats.columns[<col>].unique` for `donor_id` / `sample_id` / `library_id`. Skip any metric whose column wasn't returned or whose `unique` is 0.
- Labels: is `feature_name` in `var_columns`? which of the derived HCA obs labels (`tissue`, `cell_type`, `assay`, `disease`, `sex`, `organism`, `development_stage`) appear in `obs_columns`? Also note whether any `label_h5ad` entry exists in the edit log. If derived label columns are present but no `label_h5ad` entry is logged and their `*_ontology_term_id` counterparts also exist, flag as "possible producer drift — values may disagree with `_ontology_term_id`" (don't quantify drift here; `/curate-h5ad` handles that when `label_h5ad` runs). Separately flag `obs['self_reported_ethnicity']` / `obs['self_reported_ethnicity_ontology_term_id']` if either is present — HCA forbids these for privacy. On a CellxGENE-layout input the next step (`convert_cellxgene_to_hca`) will strip both columns automatically; on an HCA-layout input they must be dropped upstream and the file re-emitted.

## 2. HCA metadata readiness

| Category | Missing |
|---|---|
| Required (schema-wide) | list the `missing_required` field names |
| Required (bionetwork) | list the `missing_required_bionetwork` field names |
| Extra uns keys (not in schema) | list any `extra_uns_keys` |

If nothing is missing, say so in a single line instead of an empty table.

## 3. Storage & compression

Render one row per dataset that `get_storage_info` actually returns — the shape depends on the matrix format:

- **Dense X**: one row, `X` (no `data`/`indices`/`indptr` sub-datasets).
- **Sparse X** (csr/csc): three rows — `X.data`, `X.indices`, `X.indptr`.
- Same pattern for `raw/X` when present — note that `get_storage_info` returns this under the result key `raw_X` (underscore), but label the rendered rows as `raw/X` / `raw/X.data` / etc. to match the HDF5 path.
- Include a row for each populated `layers/<name>` if any.

| Dataset | Codec | Level | Chunks |
|---|---|---|---|
| … | gzip / — | 4 / — | … |

Flag any uncompressed dataset in a >100 MB file as an issue.

## 4. Embeddings
- List each `obsm` key with its shape.
- Does `uns['default_embedding']` exist? Does it name a real `obsm` key?

## 5. CAP annotations
- Are CAP annotation sets present? If yes, name them and give the cell-label count per set. If no, state that CAP is missing.
- If `view_edit_log` contains any `import_cap_annotations` entries, render the latest entry's overlap stats as a table (shows how the CAP source and the current HCA file align on both cells and genes — `n_cap` / `n_hca` are the totals on each side, `n_matched` is the intersection, and the `missing_from_*` rows are the asymmetric gaps with their percent denominators noted):

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

- If `validate_marker_genes` ran (CAP present), render its result. If the tool returned `{error: ...}` (e.g. `organism_ontology_term_id` missing or non-human), report the error as a single line and skip the tables below.

| Metric | Value |
|---|---|
| Total unique markers | … |
| Found in var gene-name source | … |
| Missing | … |

| Marker | Classification | Var name | Ensembl ID |
|---|---|---|---|
| … | … | … | … |

See `/curate-h5ad` Step 5 for classification meanings (`not_in_gencode` / `missing_from_var` / `known_rename`), the `feature_name` → `gene_name` → `var.index` fallback order, and where each miss kind points for remediation.

- If `validate_cell_annotation` ran (CAP present), render its result as a single sub-block. Render this block independently of the marker-gene table — the two are conditionally independent and either may render without the other. If the tool returned `{error: ...}` (e.g. file read failure), report the error as a single line and skip the table below.

| HCA Cell Annotation validator | Value |
|---|---|
| `is_valid` | true / false |
| `error_count` | … |
| `warning_count` | … |

Then list each error and warning verbatim, one per line. If `error_count` and `warning_count` are both 0, replace the list with a single "No structural cell-annotation issues" line. This is what the dataset-validator service runs at upload time under the `hcaCellAnnotation` key — catching issues here means fewer red-dot surprises in the tracker.

## 6. Edit history
Summarize entries as a table: `timestamp`, `operation`, one-line `description`. If absent, note that the file hasn't been edited through `hca-anndata-tools`.

## 7. Summary & recommendations
- One-line readiness verdict: ready / needs work / not started.
- Prioritized list of next actions, most important first.
- If `check_schema_type` reported `cellxgene`, the first action is `convert_cellxgene_to_hca`.
- If the file is HCA-layout and has no `label_h5ad` edit-log entry, recommend running `/curate-h5ad` so `label_h5ad` populates `var['feature_name']` and regenerates the obs ontology labels before CAP handoff or marker-gene validation.

## Save the report

After rendering the full report on screen, use the Write tool to save the same markdown to a file alongside the h5ad. Path: same directory as the input file, basename of the input minus the `.h5ad` extension, then `-evaluation-<YYYY-MM-DD>.md` (use today's date). Example: `/foo/bar/myeloid.h5ad` → `/foo/bar/myeloid-evaluation-2026-05-07.md`. Overwrite if it already exists. After saving, confirm the path back to the user as a single line.
