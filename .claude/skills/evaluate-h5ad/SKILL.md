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
8. **check_embeddings** — every numeric array-encoded entry in `obsm` is 2-D, finite, and not degenerate (all-zero, constant, or zero-variance columns); other entries (a DataFrame, a sparse matrix, a bool, string, or complex array) are not value-checked and come back under `skipped`; a row-count mismatch fails anndata's open and arrives as the tool's `error`, not a finding
9. **check_barcodes** — which cell IDs contain a run of 12 or more A/C/G/T bases, by run length (Lattice `extract_barcodes`). Structural only: a 16-base run is the shape of a 10x v2/v3 barcode and a 14-base run of Chromium v1, but nothing here checks a whitelist (that is #696), so never call a run a 10x barcode

Second batch, once `get_summary` and `get_cap_annotations` are back, in this order — the dependent calls first, the matrix passes last:

10. **get_descriptive_stats** — `columns` set to the intersection of `["donor_id", "sample_id", "library_id"]` and the obs column names from `get_summary.obs_columns` (a list of `{name, dtype}` objects — extract `name`), which is why it waits for `get_summary`. Used only for the Provenance bullet in Section 1.
11. **validate_marker_genes** — only if `get_cap_annotations` reports `has_cap_annotations: true`. CAP marker-gene coverage against the target's var gene-name source (`var['feature_name']` preferred, else `var['gene_name']`, else `var.index`).
12. **validate_cell_annotation** — only if `has_cap_annotations: true`. HCA Cell Annotation structural checks (annotation-set presence, well-formed `cellannotation_schema_version`, per-set metadata is a dict, required `--<suffix>` obs columns). This is the validator the dataset-validator service runs under the `hcaCellAnnotation` key at upload time; running it here surfaces issues during curation instead of post-upload.
13. **check_raw_counts** — one streaming pass over `raw.X` (else `X`): negative, NaN/Inf, or fractional values, zero-count cells, undetected genes
14. **check_duplicate_cells** — cells whose raw count rows are byte-identical after canonicalization (Lattice `evaluate_dup_counts`)
15. **check_donor_sex** — each donor's sex inferred from Y-linked and X-escapee expression, compared with `sex_ontology_term_id` (Lattice `evaluate_donors_sex`)

The `has_cap_annotations` gate on 11 and 12 already implies HCA-layout, so both tools have what they need; skipping them on non-CAP files avoids redundant calls (and on a no-CAP file `validate_cell_annotation` would only emit the obvious `NO_SETS_ERROR`).

Tools 8, 9, and 13–15 take only the path and are read-only, so they run on any file anndata opens. The three matrix passes stream the matrix (raw counts and duplicate cells always in full; donor sex in full on CSR and dense, but only its 17 panel columns on CSC), so on a multi-gigabyte object expect minutes, not seconds — the time scales with stored entries, and a wide obs slows every tool's open. That is expected and not a reason to skip them; results of backgrounded calls arrive as notifications, so keep going and pick them up when they land. Each check returns `findings` in the shared shape its docstring describes (empty when clean), or a top-level `error` when it could not run.

Then synthesize the results into a report with these sections in order. Use markdown tables wherever multiple items share the same shape; keep prose tight.

## 1. File overview
One compact block (bullets or a short table) with:
- Input path (`$ARGUMENTS`). If the tools auto-resolved to a newer snapshot, add the resolved basename on a second line — read it from any tool that returns a `filename` field (e.g. `check_schema_type.filename`). Skip the second line when input and resolved agree.
- Shape: `n_obs × n_vars`, file size (MB)
- `title` from `uns`
- Schema type (from `check_schema_type`) — include the version only when schema is CellxGENE (HCA is unversioned)
- X verdict (from `check_x_normalization`: `raw_counts` / `normalized` / `indeterminate`) + whether `raw.X` is present
- Provenance: render `N donors · M samples · K libraries` from `get_descriptive_stats.columns[<col>].unique` for `donor_id` / `sample_id` / `library_id`. Skip any metric whose column wasn't returned or whose `unique` is 0.
- Cell IDs (from `check_barcodes.structure`): `with_barcode` of `n_obs` cell IDs contain a run of 12 or more A/C/G/T bases (`fraction` as a percentage), then the `by_length` histogram inline, longest run first, rendering each key `N` as `N-base` and the tool's `"0"` key (no run) as `none`, e.g. `16-base: 2,101,441 · 14-base: 27,064 · none: 12`. Say what was measured — a run of 12+ A/C/G/T bases in the ID, with 16 the length of a 10x v2/v3 barcode and 14 of Chromium v1 — and not that the cells carry 10x barcodes: no whitelist is consulted (#696). No verdict here — an ID family without a run is a fact about provenance, not a defect; its finding, if any, renders in Section 2. Skip the bullet if the tool returned `error`.
- Labels: is `feature_name` in `var_columns`? which of the derived HCA obs labels (`tissue`, `cell_type`, `assay`, `disease`, `sex`, `organism`, `development_stage`) appear in `obs_columns`? Also note whether any labeling entry (`populate_labels`, or the older `label_h5ad`) exists in the edit log. If derived label columns are present but no labeling entry is logged and their `*_ontology_term_id` counterparts also exist, flag as "possible producer drift — values may disagree with `_ontology_term_id`" (don't quantify drift here; `/curate-h5ad` handles that when `populate_labels` runs, which verifies every populated row against canonical and reports each disagreement with row counts). Separately flag `obs['self_reported_ethnicity']` / `obs['self_reported_ethnicity_ontology_term_id']` if either is present — HCA forbids these for privacy. On a CellxGENE-layout input the next step (`convert_cellxgene_to_hca`) strips both columns automatically as a side-effect of converting; on an HCA-layout input run `strip_forbidden_obs_columns` to remove them mechanically.

## 2. Matrix & embedding gate

The five read-only checks, rendered before anything about metadata so a bad matrix is never buried under a clean `uns`. The three matrix checks all read the same matrix (`raw/X` when present, else `X`); name it once above the table.

| Check | Element | Result |
|---|---|---|
| `check_raw_counts` | the matrix | **clean** — or `N finding(s)` |
| `check_embeddings` | `obsm` (`K` arrays checked) | **clean** — or `N finding(s)` |
| `check_duplicate_cells` | the matrix | **clean** — or `N surplus cell(s) in G group(s)` |
| `check_donor_sex` | the matrix; `M` male / `F` female panel genes found | **all D donor rows agree** — only when `verdict_counts.agree` is above zero and every other entry is 0 (`D` is `verdict_counts.agree`; a donor with droplet and plate-based libraries is two rows, so `D` can exceed the donor count); otherwise the non-zero entries of `verdict_counts`, e.g. `41 agree · 3 indeterminate · 1 contradiction` |
| `check_barcodes` | obs index | **every cell ID contains a run of 12+ bases** — or `N cell ID(s) without one` |

The Result cell is one of three disjoint cases:

- **`error` present** → the error text verbatim. A by-name refusal (duplicate cells on CSC storage, donor sex on a donor with two annotated sexes) is the tool working, not failing (`docs/anndata-tools-contract.md`, principle 4); name the check that owns the defect when the message does.
- **A caveat present** → the caveat with its `reason`, alongside the finding count. The caveats are `check_raw_counts.integer_check.status == "not_applicable"` (no `raw.X` and `X` is not counts, so only the criteria that hold for any matrix ran), `check_donor_sex.gene_panel.status == "not_applicable"` (no inference made), and a non-empty `check_embeddings.skipped` (name each `key`).
- **Otherwise, empty `findings`** → **clean** — except for `check_donor_sex`, where `indeterminate` and `not_applicable` verdicts produce no finding, so its clean case is the one its row states, and anything else renders the verdict counts.

Then one block per tool with non-empty `findings`, as a table:

| Code | Element | Count | Sample IDs |
|---|---|---|---|
| `non_finite_values` | `raw/X` | 1,204 | `AAACCTGAGAAACCAT-1`, … |

Cite `count`, never the length of `sample_ids` (a sample of at most 20 — the same rule as `unsupported_truncated` in Section 4), and say what unit the IDs are in: the code and `element` tell you whether they are cells, genes, or `obsm` columns. Render any extra keys a finding carries beyond the four (`sample_groups` on `duplicate_cells`, one row per entry — a sample of at most 20 groups of at most 20 IDs, so cite `groups` for the total; `shape` on `wrong_shape`; `value` on `constant`). Two top-level fields render on their own line: `check_duplicate_cells.non_canonical_rows` (information, never a finding) and, whenever `check_donor_sex.donors` is non-empty (`indeterminate` and `not_applicable` produce no finding, so do not key this on `findings`), those rows as returned (`agree` rows are already excluded and each other verdict lists at most 20 rows, so cite `verdict_counts` for totals, never the table's length):

| Donor | Cells | Ratio (male/female) | Inferred | Annotated | Male signal carried by | Verdict |
|---|---|---|---|---|---|---|
| `D12` | 4,201 | 1.84 | male | female | `ZFY` (61%) | **contradiction** |

Ratio is `null` when the female sum is zero: render `∞` when `male_counts` is above zero and `—` when both sums are zero. A `null` `inferred` (only below-floor rows; a non-human donor still gets an inference, its verdict is what says `not_applicable`) renders as `—`. A `-smartseq` suffix on `donor_id` is one donor's plate-based libraries split into their own row, not a second donor. The "Male signal carried by" cell is `male_dominant_gene` with `male_dominant_share` as a percentage, and `—` when both are `null` (no male counts at all). Verdict meanings are in the tool's docstring; `contradiction` is the adjudicate-first case (Section 8), and it is never reported on the ratio alone. `undetected_genes` in a lineage subset is expected (the genes were detected in cells the subset dropped) and gets one clause of context, not alarm.

Whenever any row is a `contradiction`, also render `panel_summary` — one row per panel gene, with its mean per-cell count in donors annotated male, the same for female, and `male_over_female` — and read it in the report:

| Gene | Panel | Annotated male | Annotated female | Male / female |
|---|---|---|---|---|
| `DDX3Y` | male | 0.175 | 0.0015 | 117 |
| `ZFY` | male | 1.16 | 2.22 | 0.5 |
| `XIST` | female | 0.075 | 3.018 | 0.02 |

`male_over_female` is one ratio, always the male mean over the female mean, and it says how well that gene tells the sexes apart **in this file** — measured against the annotation, not the inference. What counts as working depends on the gene's panel, so read distance from 1 rather than the number itself: a Y-linked gene that works sits far **above** 1 (`DDX3Y` at 117), an X-escapee that works sits far **below** it (`XIST` at 0.02), and a gene sitting **near** 1 on either panel has stopped discriminating and cannot support a call (`ZFY` at 0.5). Never read a low ratio on a female-panel gene as a defect — that is the gene doing its job.

Before leaning on that table, check what it rests on. `panel_reference` gives the donors and cells behind each side, and the means are weighted by cells — so divide the contradicted donor's `donor_cells` by its side's total. Use `donor_cells`, never the row's own `cells`: a donor split across chemistries is two rows, only the contradicted one is listed, and its agreeing sibling still counts toward the reference. A 4-cell row can look negligible while the same donor's 1,000 Smart-seq cells define nearly the whole side. If it is most of its side, the comparison is largely that donor against itself: a contradicted donor big enough to set its own side's mean drags the ratios toward 1, which reads as a degraded panel and appears to excuse the very contradiction being judged. Say so and treat the summary as uninformative for that donor rather than as evidence in its favour. Report the split whenever it is lopsided, for example "the female column is 30 of 32 cells from this donor".

A `null` ratio is not a number near 1, and it does not always mean the same thing — read the two means to tell which case it is. If the annotated-male mean is positive and the female mean is zero, the ratio is infinite: render `∞`, which is **maximal** separation and the strongest evidence the gene can give, not missing evidence. If both means are zero, render `—`: the gene is silent in this file and says nothing either way. If one annotated sex has no donors at all — a cohort annotated one sex throughout, which breast, prostate and ovary all are — render `—` and say so plainly: this evidence cannot adjudicate a contradiction there at all, and the call has to be settled against the study's own metadata. Never read a table of `—` as agreement or as a degraded panel.

One limit on the table itself: it pools droplet and plate-based rows, though the ratio differs by chemistry — that is why the tool splits a donor's Smart-seq libraries into their own row in the first place. `panel_reference` reports `smart_seq_cells` per side, so compare the two sides: if chemistry falls unevenly across the annotated sexes, some of what the table reads as separation is protocol, and you should say so rather than treat the ratios as clean.

So when a contradicted donor's signal is carried by genes whose `male_over_female` sits near 1, say plainly that the contradiction is not supported by the evidence, and name those genes and their ratios from `panel_summary` — never from memory of which genes are usually unreliable, since which ones degrade is a property of how the file was aligned. When it is carried by genes far from 1 in the direction their panel expects, and `xist_per_cell` agrees, say that too: that is a contradiction worth adjudicating. Cite `XIST` whenever it is present — but check its own `male_over_female` in `panel_summary` first and weigh it the same way as any other gene, rather than treating it as decisive by reputation. `XIST` usually separates the sexes better than anything else on the panel, and on this atlas it does; it is also the gene that inflated ambient signal can carry, which is exactly the case where an annotated-male donor is wrongly inferred female. A gene is only as good as its ratio in the file in front of you. For each contradicted donor, give its `per_gene` `per_cell` values for **both** panels, on one line each, so the reader sees the split the verdict rests on rather than taking the summary's word for it. Both, because a contradiction runs in either direction: a donor annotated female and inferred male is carried by the seven Y-linked genes, but one annotated male and inferred female is carried by the ten X-escapees — its male panel is near zero and says nothing, and the evidence is entirely in `XIST` and its neighbours. Rendering only the male panel would hide the whole case for that second kind. Lead with whichever panel supports the *inferred* sex, since that is the one making the claim. `per_gene` is carried on `contradiction` rows only; every other row has its panel totals, `male_dominant_gene` and `xist_per_cell` but no gene-by-gene breakdown, which is expected and not a gap.

One limit to state whenever you lean on `male_over_female`: it is computed against the annotated sexes, which is what a contradiction disputes. If a file's sex annotations are systematically wrong — a swapped column, a mis-joined donor table — then genes that work will also read near 1, which looks identical to a degraded panel. The diagnosis is sound while contradicted donors are a small share of their side's **cells**, and weakens as that share grows. Judge it in cells, not in donors: the means are cell-weighted, so three contradicted donors out of thirty can still be most of a side. Sum the contradicted rows' `donor_cells` against `panel_reference`, with two corrections, and say so rather than reading a ratio near 1 as proof when much of the side is contradicted.

- **Deduplicate by donor.** `donor_cells` is the donor's whole contribution, so a donor contradicted in *both* chemistry rows appears twice carrying the same number. Count each donor once, stripping the `-smartseq` suffix **only from rows whose `smart_seq` is true** — that flag marks the suffix the tool added, and a donor may legitimately be named `X-smartseq` and have droplet libraries only, which stripping blindly would merge with a donor `X`. Otherwise the share comes out roughly double.
- **Check the table is complete first.** `donors` is capped at 20 rows per verdict, so if `verdict_counts.contradiction` exceeds the number of contradiction rows listed, the sum is missing donors and is a floor, not the share. Say the aggregate is unavailable and that `panel_summary` cannot be trusted for this file, rather than dividing what is there — a truncated sum reads as a small share, which is exactly the answer that would wrongly clear the table.

Neither correction applies to the single-donor check above, which uses one row's own `donor_cells` and needs no sum.

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
- One-line readiness verdict: ready / needs work / not started. A gate finding that names an objective defect forces at least **needs work** — `negative_values`, `non_finite_values`, `non_integer_values`, `zero_count_cells`, `empty_matrix`, any `check_embeddings` code, and `duplicate_cells` — whoever has to fix it, because no metadata state offsets a wrong value or a duplicated cell. `undetected_genes`, `no_barcode_in_index`, `sex_contradiction`, `sex_below_floor`, and `sex_fillable` are informational and do not affect the verdict. `sex_contradiction` is informational because the inference behind it is not reliable enough to force a verdict on its own (#707): all seven Y-linked panel genes are X-Y gametologs, and where the alignment counted introns, four of them stop discriminating and can carry a female donor over the male cut. Report it with the evidence below and say it needs adjudication; do not state it as a defect the file is known to have.
- Prioritized list of next actions, most important first, gate findings leading. `duplicate_cells` is a **relay-to-producer** action — no tool of ours fixes it, and which duplicate to keep is the producer's call — so name the group count so the message can be written from the report. `sex_contradiction` is an **adjudicate-first** action: name the donors, say what the per-gene evidence shows, and state that the call has to be settled against the study's own metadata (GEO, the publication, the submitter) before anything is relayed. Never relay a contradiction on the ratio alone.
- If `check_schema_type` reported `cellxgene`, the first action is `convert_cellxgene_to_hca`.
- If the file is HCA-layout and has no labeling edit-log entry (`populate_labels`, or the older `label_h5ad`), recommend running `/curate-h5ad` so `populate_labels` fills `var['feature_name']` and the obs ontology labels before CAP handoff or marker-gene validation.

## Save the report

After rendering the full report on screen, use the Write tool to save the same markdown to a file alongside the h5ad. Path: same directory as the input file, basename of the input minus the `.h5ad` extension, then `-evaluation-<YYYY-MM-DD>.md` (use today's date). Example: `/foo/bar/myeloid.h5ad` → `/foo/bar/myeloid-evaluation-2026-05-07.md`. Overwrite if it already exists. After saving, confirm the path back to the user as a single line.
