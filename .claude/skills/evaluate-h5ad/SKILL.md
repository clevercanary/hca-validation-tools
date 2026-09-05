---
name: evaluate-h5ad
description: Evaluate an h5ad file for HCA readiness — checks metadata, compression, the count matrix and embeddings (values a count cannot hold, duplicated cells, donor sex vs expression, barcode-shaped cell IDs), CAP annotations, and edit history.
argument-hint: <absolute-path-to-h5ad-file>
---

# Evaluate H5AD File

Evaluate the h5ad file at absolute path: `$ARGUMENTS`

Pass an absolute path to the `.h5ad` file. Relative paths are resolved against the MCP server's working directory, which may not match the user's, so they can silently evaluate the wrong file.

Gather data with the MCP tools below. The client runs MCP calls one at a time and moves any call that passes two minutes to the background, so order matters: issue the cheap tools first, the dependent calls next, and the three matrix passes last.

First batch — cheap, obs-sized:

1. **get_summary** — cell/gene counts, obs/var columns, uns keys, layers, obsm
2. **get_storage_info** — compression, chunking, sparse format, file size
3. **check_schema_type** — report CellxGENE vs HCA layout (CellxGENE carries a schema version; HCA is not versioned so skip the version for HCA files)
4. **check_x_normalization** — classify X as raw_counts / normalized / indeterminate
5. **list_uns_fields** — HCA schema field completeness (required vs set vs missing)
6. **get_cap_annotations** — CAP cell annotation sets, if present
7. **view_edit_log** — read `uns/provenance/edit_history` so edit history is already in hand when synthesizing the report
8. **check_embeddings** — every array in `obsm` is 2-D, finite, and not degenerate (all-zero, constant, or zero-variance columns); a row-count mismatch fails anndata's open and arrives as the tool's `error`, not a finding
9. **check_barcodes** — which cell IDs contain a nucleotide run of 12 or more bases, by run length (Lattice `extract_barcodes`). Structural only: a 16-base run is the shape of a 10x v2/v3 barcode and a 14-base run of Chromium v1, but nothing here checks a whitelist (that is #696), so never call a run a 10x barcode

Second batch, once `get_summary` and `get_cap_annotations` are back — the dependent calls (`get_descriptive_stats` and, when CAP is present, the two validators below) first, then the matrix passes:

10. **check_raw_counts** — one streaming pass over `raw.X` (else `X`): negative, NaN/Inf, or fractional values, zero-count cells, undetected genes
11. **check_duplicate_cells** — cells whose raw count rows are byte-identical after canonicalization (Lattice `evaluate_dup_counts`)
12. **check_donor_sex** — each donor's sex inferred from Y-linked and X-escapee expression, compared with `sex_ontology_term_id` (Lattice `evaluate_donors_sex`)

Tools 8–12 take only the path and are read-only, so they run on any file anndata opens. The three matrix passes stream the whole matrix, so on a multi-gigabyte object expect minutes, not seconds — the time scales with stored entries, and a wide obs slows every tool's open. That is expected and not a reason to skip them; results of backgrounded calls arrive as notifications, so keep going and pick them up when they land. Each check returns `findings` in the shared shape its docstring describes (empty when clean), or a top-level `error` when it could not run.

Only if `get_cap_annotations` reports `has_cap_annotations: true`, call both of these:
- **validate_marker_genes** — CAP marker-gene coverage against the target's var gene-name source (`var['feature_name']` preferred, else `var['gene_name']`, else `var.index`).
- **validate_cell_annotation** — HCA Cell Annotation structural checks (annotation-set presence, well-formed `cellannotation_schema_version`, per-set metadata is a dict, required `--<suffix>` obs columns). This is the validator the dataset-validator service runs under the `hcaCellAnnotation` key at upload time; running it here surfaces issues during curation instead of post-upload.

The `has_cap_annotations` gate already implies HCA-layout, so both tools have what they need; skipping on non-CAP files avoids redundant calls (and on a no-CAP file `validate_cell_annotation` would only emit the obvious `NO_SETS_ERROR`).

**get_descriptive_stats** takes `columns` set to the intersection of `["donor_id", "sample_id", "library_id"]` and the obs column names from `get_summary.obs_columns` (a list of `{name, dtype}` objects — extract `name`), which is why it waits for `get_summary`. Used only for the Provenance bullet in Section 1.

Then synthesize the results into a report with these sections in order. Use markdown tables wherever multiple items share the same shape; keep prose tight.

## 1. File overview
One compact block (bullets or a short table) with:
- Input path (`$ARGUMENTS`). If the tools auto-resolved to a newer snapshot, add the resolved basename on a second line — read it from any tool that returns a `filename` field (e.g. `check_schema_type.filename`). Skip the second line when input and resolved agree.
- Shape: `n_obs × n_vars`, file size (MB)
- `title` from `uns`
- Schema type (from `check_schema_type`) — include the version only when schema is CellxGENE (HCA is unversioned)
- X verdict (from `check_x_normalization`: `raw_counts` / `normalized` / `indeterminate`) + whether `raw.X` is present
- Provenance: render `N donors · M samples · K libraries` from `get_descriptive_stats.columns[<col>].unique` for `donor_id` / `sample_id` / `library_id`. Skip any metric whose column wasn't returned or whose `unique` is 0.
- Cell IDs (from `check_barcodes.structure`): `with_barcode` of `n_obs` cell IDs contain a nucleotide run (`fraction` as a percentage), then the `by_length` histogram inline, longest run first, e.g. `16-base: 2,101,441 · 14-base: 27,064 · none: 12`. Say what was measured — a run of A/C/G/T in the ID, with 16 the length of a 10x v2/v3 barcode and 14 of Chromium v1 — and not that the cells carry 10x barcodes: no whitelist is consulted (#696). No verdict here — an ID family without a run is a fact about provenance, not a defect; its finding, if any, renders in Section 2. Skip the bullet if the tool returned `error`.
- Labels: is `feature_name` in `var_columns`? which of the derived HCA obs labels (`tissue`, `cell_type`, `assay`, `disease`, `sex`, `organism`, `development_stage`) appear in `obs_columns`? Also note whether any labeling entry (`populate_labels`, or the older `label_h5ad`) exists in the edit log. If derived label columns are present but no labeling entry is logged and their `*_ontology_term_id` counterparts also exist, flag as "possible producer drift — values may disagree with `_ontology_term_id`" (don't quantify drift here; `/curate-h5ad` handles that when `populate_labels` runs, which verifies every populated row against canonical and reports each disagreement with row counts). Separately flag `obs['self_reported_ethnicity']` / `obs['self_reported_ethnicity_ontology_term_id']` if either is present — HCA forbids these for privacy. On a CellxGENE-layout input the next step (`convert_cellxgene_to_hca`) strips both columns automatically as a side-effect of converting; on an HCA-layout input run `strip_forbidden_obs_columns` to remove them mechanically.

## 2. Matrix & embedding gate

The five read-only checks, rendered before anything about metadata so a bad matrix is never buried under a clean `uns`. The three matrix checks all read the same matrix (`raw/X` when present, else `X`); name it once above the table.

| Check | Element | Result |
|---|---|---|
| `check_raw_counts` | the matrix | **clean** — or `N finding(s)` |
| `check_embeddings` | `obsm` (`K` arrays checked) | **clean** — or `N finding(s)` |
| `check_duplicate_cells` | the matrix | **clean** — or `N surplus cell(s) in G group(s)` |
| `check_donor_sex` | the matrix; `M` male / `F` female panel genes found | **all D donors agree** — only when every `donors[].verdict` is `agree`; otherwise the verdict counts, e.g. `41 agree · 3 indeterminate · 1 contradiction` |
| `check_barcodes` | obs index | **every cell ID contains a nucleotide run** — or `N cell ID(s) without one` |

The Result cell is one of three disjoint cases:

- **`error` present** → the error text verbatim. A by-name refusal (duplicate cells on CSC storage, donor sex on a donor with two annotated sexes) is the tool working, not failing (`docs/anndata-tools-contract.md`, principle 4); name the check that owns the defect when the message does.
- **A caveat present** → the caveat with its `reason`, alongside the finding count. The caveats are `check_raw_counts.integer_check.status == "not_applicable"` (no `raw.X` and `X` is not counts, so only the criteria that hold for any matrix ran), `check_donor_sex.gene_panel.status == "not_applicable"` (no inference made), and a non-empty `check_embeddings.skipped` (name each `key`).
- **Otherwise, empty `findings`** → **clean** — except for `check_donor_sex`, where `indeterminate` and `not_applicable` verdicts produce no finding, so its clean case is every `donors[].verdict == "agree"` (as its row says), and anything else renders the verdict counts.

Then one block per tool with non-empty `findings`, as a table:

| Code | Element | Count | Sample IDs |
|---|---|---|---|
| `non_finite_values` | `raw/X` | 1,204 | `AAACCTGAGAAACCAT-1`, … |

Cite `count`, never the length of `sample_ids` (a sample of at most 20 — the same rule as `unsupported_truncated` in Section 4), and say what unit the IDs are in: the code and `element` tell you whether they are cells, genes, or `obsm` columns. Render any extra keys a finding carries beyond the four (`sample_groups` on `duplicate_cells`, one row per entry — a sample of at most 20 groups of at most 20 IDs, so cite `groups` for the total; `shape` on `wrong_shape`; `value` on `constant`). Two top-level fields render on their own line: `check_duplicate_cells.non_canonical_rows` (information, never a finding) and, whenever any `donors[].verdict` is not `agree` (`indeterminate` and `not_applicable` produce no finding, so do not key this on `findings`), `check_donor_sex.donors` filtered to those rows:

| Donor | Cells | Ratio (male/female) | Inferred | Annotated | Verdict |
|---|---|---|---|---|---|
| `D12` | 4,201 | 1.84 | male | female | **contradiction** |

Ratio is `null` when the female sum is zero: render `∞` when `male_counts` is above zero and `—` when both sums are zero. A `null` `inferred` (below-floor and non-human rows) renders as `—`. A `-smartseq` suffix on `donor_id` is one donor's plate-based libraries split into their own row, not a second donor. Verdict meanings are in the tool's docstring; `contradiction` is the relay-to-producer case (Section 8). `undetected_genes` in a lineage subset is expected (the genes were detected in cells the subset dropped) and gets one clause of context, not alarm.

Interim, until `check_donor_sex` trims its own output (#700): on an atlas with a few hundred donors the `donors` table pushes the result past the client's tool-result size limit and the whole result is saved to a file. That is not an error. One `jq` over the file gives everything the two tables need: `{n_donors: (.donors|length), verdicts: (.donors|group_by(.verdict)|map({(.[0].verdict): length})|add), findings, rows: (.donors|map(select(.verdict != "agree")))}`.

## 3. HCA metadata readiness

| Category | Missing |
|---|---|
| Required (schema-wide) | list the `missing_required` field names |
| Required (bionetwork) | list the `missing_required_bionetwork` field names |
| Extra uns keys (not in schema) | list any `extra_uns_keys` |

If nothing is missing, say so in a single line instead of an empty table.

## 4. Storage & compression

Render one row per dataset that `get_storage_info` actually returns — the shape depends on the matrix format:

- **Dense X**: one row, `X` (no `data`/`indices`/`indptr` sub-datasets).
- **Sparse X** (csr/csc): three rows — `X.data`, `X.indices`, `X.indptr`.
- Same pattern for `raw/X` when present — note that `get_storage_info` returns this under the result key `raw_X` (underscore), but label the rendered rows as `raw/X` / `raw/X.data` / etc. to match the HDF5 path.
- Include a row for each populated `layers/<name>` if any.

| Dataset | Codec | Level | Chunks |
|---|---|---|---|
| … | gzip / — | 4 / — | … |

Flag any uncompressed dataset in a >100 MB file as an issue.

### Encodings

From `get_storage_info.encodings`, render one row per dataframe — `obs`, `var`, `raw.var`, and each entry of the `obsm` map (an obsm DataFrame carries its own index and fails the same way). Skip any whose value is `null`, and skip `obsm` entirely when its map is empty:

| Dataframe | Index encoding | Categoricals |
|---|---|---|
| `obs` | `string-array` | 38 × `string-array` |

Then apply two checks, which mean different things and must not be merged:

- **`unsupported_count > 0` — informational.** Report it and name it: these elements use a nullable-string encoding, and since hca-validation-tools#641 **nothing refuses it — every write normalizes what it touches** (a full rewrite normalizes everything and reports `encodings_normalized`; an in-place tool normalizes the elements it replaces), so the flags describe the file as it stands and clear as curation writes happen. Give the count, and the sample paths in `unsupported` — note that when `unsupported_truncated` is true the list is a sample and `unsupported_count` is the real total, so cite the count, never the length of the list. `nullable-string-array` is the encoding this normally means, **not** a defect in the file — but a **masked** string value (`index_masked > 0`, or a masked-value refusal from a tool that writes) is a data problem no rewrite may flatten. The reported paths are on-disk HDF5 paths, so they can be pasted straight into h5py or grep.

  Scope: a flagged file normally blocks nothing — the tools run, and each write normalizes the flagged elements it touches (per `docs/anndata-tools-contract.md`). The check covers the reported dataframes' nullable-*string* indexes, plain columns, and categorical `categories`; nullable-numeric and categorical-group elements are in-profile and not flagged; `varm` and `uns` elements are normalized by writes but not inspected here. Two exceptions. Masked (null) string *values* are a hard stop: a tool that meets one refuses by name. And a flagged `.../categories` path is where an unopenable file shows up: if its categories are masked, anndata cannot read the file at all, which puts it out of scope (`docs/anndata-tools-contract.md`, Scope) — some reads proceed anyway, so a clean run there is not a clean verdict.
- **`index_masked` greater than 0 — data.** Report this as a *separate and more serious* issue: the index contains null values. A null cell ID corrupts every join silently, and unlike an unsupported encoding it is a problem with the data rather than with our tools. `index_masked` is `null` when the index carries no mask of its own — usually because the encoding cannot hold nulls, which is not the same as `0`. A *categorical* index is the exception, and it cuts the other way: its nulls are codes of -1 over plain categories, which `_mask_count` cannot see and `unsupported` does not list — the report comes back clean on a file whose cell IDs contain nulls. On a categorical index `null` means *not checked*; only a tool that reads the index through `read_index` will refuse it (#659).

## 5. Embeddings
- List each `obsm` key with its shape (from `get_summary.obsm_keys`, which has every key) and dtype (from `check_embeddings.embeddings` where present; a key that is only in `check_embeddings.skipped` was not value-checked — say so with its `reason`).
- Does `uns['default_embedding']` exist? Does it name a real `obsm` key?
- Value-level problems (NaN rows, zero-variance columns) are already in Section 2; refer back rather than repeating them here.

## 6. CAP annotations
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

See `/curate-h5ad` Step 5 for classification meanings (`not_in_gencode` / `missing_from_var` / `known_rename`), the `feature_name` → `gene_name` → `var.index` fallback order, and where each miss kind points for remediation. Report each missing marker by symbol and classification only — do not speculate about cause (typo / glob / rename); the classification name is the answer.

- If `validate_cell_annotation` ran (CAP present), render its result as a single sub-block. Render this block independently of the marker-gene table — the two are conditionally independent and either may render without the other. The wrapper has two failure shapes; handle each accordingly:
  - **Top-level `{error: str}`** — only fires on wrapper-level failures (path resolution, missing file, unexpected exception in the wrapper itself). Report the error as a single line and skip the table below.
  - **Normal shape with `is_valid: false` + a populated `errors[]`** — covers everything the validator caught internally. Render the table normally and list each `errors[]` entry verbatim. One entry is not a validation finding at all: `"Unable to read h5ad file: ..."` in `errors[0]` means anndata could not open the file, which puts it out of scope for these tools (`docs/anndata-tools-contract.md`). Quote that message verbatim, say the fix belongs upstream with whoever produced the file, and stop rather than rendering the rest as if it were a verdict.

| HCA Cell Annotation validator | Value |
|---|---|
| `is_valid` | true / false |
| `error_count` | … |
| `warning_count` | … |

Then list each error and warning verbatim, one per line. If `error_count` and `warning_count` are both 0, replace the list with a single "No structural cell-annotation issues" line. This is what the dataset-validator service runs at upload time under the `hcaCellAnnotation` key — catching issues here means fewer red-dot surprises in the tracker.

## 7. Edit history

Render every entry returned by `view_edit_log` as a table, oldest first:

| # | Timestamp (UTC) | Operation | Description |
|---|---|---|---|
| 1 | 2026-04-21 04:19:10 | `normalize_raw` | Moved raw counts to raw.X and normalized X with normalize_total(target_sum=10000) + log1p |

Format the timestamp as `YYYY-MM-DD HH:MM:SS` (drop the `T` and the fractional seconds and timezone — entries are always UTC). Use the entry's `description` field verbatim. If the file has no edit log, say "No edit history — file hasn't been edited through `hca-anndata-tools`."

## 8. Summary & recommendations
- One-line readiness verdict: ready / needs work / not started. A gate finding that names an objective defect forces at least **needs work** — `negative_values`, `non_finite_values`, `non_integer_values`, `zero_count_cells`, `empty_matrix`, any `check_embeddings` code, `duplicate_cells`, and `sex_contradiction` — whoever has to fix it, because no metadata state offsets a wrong value, a duplicated cell, or a donor whose annotation contradicts expression. `undetected_genes`, `no_barcode_in_index`, `sex_below_floor`, and `sex_fillable` are informational and do not.
- Prioritized list of next actions, most important first, gate findings leading. `sex_contradiction` and `duplicate_cells` are **relay-to-producer** actions — no tool of ours fixes either, and which annotation is right or which duplicate to keep is the producer's call — so name the donors or the group count so the message can be written from the report.
- If `check_schema_type` reported `cellxgene`, the first action is `convert_cellxgene_to_hca`.
- If the file is HCA-layout and has no labeling edit-log entry (`populate_labels`, or the older `label_h5ad`), recommend running `/curate-h5ad` so `populate_labels` fills `var['feature_name']` and the obs ontology labels before CAP handoff or marker-gene validation.

## Save the report

After rendering the full report on screen, use the Write tool to save the same markdown to a file alongside the h5ad. Path: same directory as the input file, basename of the input minus the `.h5ad` extension, then `-evaluation-<YYYY-MM-DD>.md` (use today's date). Example: `/foo/bar/myeloid.h5ad` → `/foo/bar/myeloid-evaluation-2026-05-07.md`. Overwrite if it already exists. After saving, confirm the path back to the user as a single line.
