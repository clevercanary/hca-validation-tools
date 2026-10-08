# Dataset Validator — Check Inventory

This document enumerates every check performed by the HCA dataset validator, including the rules inherited from the vendored `cellxgene_schema` core. The dataset validator runs as an AWS Batch job and orchestrates three downstream validators (CAP, CELLxGENE, HCA schema) plus pre-validation integrity checks.

Source files:
- Orchestrator: `services/dataset-validator/src/dataset_validator/main.py`
- CAP wrapper: `services/dataset-validator/src/dataset_validator/cap_validator_script.py`
- CELLxGENE wrapper: `services/cellxgene-validator/src/cellxgene_validator/main.py`
- HCA wrapper: `services/hca-schema-validator/src/hca_schema_validator_service/main.py`
- HCA validator: `packages/hca-schema-validator/src/hca_schema_validator/validator.py`
- Vendored core: `packages/hca-schema-validator/src/hca_schema_validator/_vendored/cellxgene_schema/`

---

## 1. Orchestration-level checks (`main.py`)

Run before any schema validator:

- **Required env vars present** — `S3_BUCKET`, `S3_KEY`, `FILE_ID`, `SNS_TOPIC_ARN`, `AWS_BATCH_JOB_ID` (bypassed when `LOCAL_FILE` is set).
- **S3 object has `source-sha256` metadata** — hard-fail if missing.
- **File integrity** — SHA256 computed on the downloaded file must match the S3 metadata hash.
- **Metadata summary readable** — opens the h5ad in backed mode and extracts `uns.title`, `obs.assay`, `obs.suspension_type`, `obs.tissue`, `obs.disease`, `n_obs`, `n_vars`.

Each downstream validator runs as a subprocess (memory isolation) and its result is aggregated under `tool_reports.{cap, cellxgene, hcaSchema}`.

---

## 2. CAP validator (`cap_upload_validator.UploadValidator`)

Runs the external `cap_upload_validator` package against the file. Validates CAP's cell-annotation-platform upload contract: cell label tables, marker genes, and annotation provenance structures in `obs`/`uns`. `CapException` / `CapMultiException` messages are surfaced as errors; warnings are not captured.

---

## 3. CELLxGENE validator (vendored `cellxgene_schema.validate.validate`)

Runs the full vendored schema validator against the unmodified CELLxGENE schema YAML. See §5 below for the rule set.

---

## 4. HCA schema validator (`HCAValidator`)

`HCAValidator` subclasses the vendored `Validator` and swaps in `hca_schema_definition.yaml`. Differences vs. CELLxGENE:

- **`organism_ontology_term_id` lives in `obs`**, not `uns`. Feature-id/organism checks read from obs.
- **`requirement_level: optional`** — silently skipped if missing, fully validated if present.
- **`requirement_level: strongly_recommended`** — warns when missing; warns on NaN with count/percent; errors on list-separator values (`,`/`;`/`|`); errors on blocklist placeholder values.
- **`requirement_level: forbidden`** — errors if the column is present in the dataframe; error text comes from `forbidden_error` on the schema entry. Currently used to enforce that `obs['self_reported_ethnicity_ontology_term_id']` and `obs['self_reported_ethnicity']` are absent (HCA does not collect ethnicity — privacy). `HCALabeler._preflight` rejects the same columns symmetrically so the labeler can never produce an HCA-invalid file.
- **`pattern` regex on columns** — errors on values that don't fullmatch; uses `pattern_description` for the error text.
- **`element_type: string` on lists** — errors on non-string or whitespace-only entries.
- **Raw-layer retry** — re-runs `_validate_raw()` if the base class skipped it but `assay_ontology_term_id` exists.
- **GENCODE-aware feature-ID warnings** — warning text includes a GENCODE version label, plus a dataset-organism vs. feature-ID-organism mismatch warning (excluding exempt organisms).
- **Warning reordering** — feature-ID warnings pushed to the end.
- **Expression matrix contract** — see §4.1. Not inherited from CELLxGENE, which checks that `raw.X` is raw but never looks at `X`.
- **Producer label columns** (`check_cosmetic_labels`) — a populated `obs['sex']`, `obs['tissue']`, etc. must have its `*_ontology_term_id` source column (else warning) and every label must equal the canonical ontology label for the row's term (else error). #377, #443.
- **Donor-level consistency** — see §4.2.
- **Declared gene annotation vs. the file's genes** — see §4.3.
- **Retired feature identifiers** — see §4.4. Summarises and classifies the per-identifier feature-ID warnings rather than replacing them.

All other rules come from the vendored base class (§5).

### 4.1 Expression matrix contract (`check_x_normalization`)

Three matrices, and no more. Everything else in circulation — `normalized_counts`, `desouped_normalized_counts`, `logcounts` — is recomputable from these, so storing it buys no information and silently goes stale when the file is edited.

| matrix | required | holds |
|---|---|---|
| `raw.X` | yes | raw counts, float32, empty droplets removed only |
| `layers['desouped_counts']` | when ambient RNA removal was applied | counts surviving removal, float32 |
| `X` | yes | `log1p(normalize_total(desouped_counts if present else raw.X))` |

The table is the contract, not the check list. `raw.X`'s dtype and integrality are enforced (by the vendored raw-layer validation); `desouped_counts`' are **not** — check 5 below establishes only that the layer is usable as a reference, and check 6 that it does not exceed `raw.X`. Validating the layer as counts in its own right is open work.

`desouped_counts` is required rather than optional because it cannot be recovered: ambient RNA removal is parameterised and often stochastic, so discarding it leaves `X` an assertion no one can check. `normalize_total`'s target sum is *not* pinned — the checks compare per-cell profiles, in which the target cancels, so `scanpy`'s `target_sum=None` default is accepted.

Checks run cheapest first and short-circuit, so one defect yields one message:

1. **`X` identical to `raw.X`** — normalization never ran. The two-matrix layout means `raw.X` present implies `X` is the normalized one; CELLxGENE has no state where both are present and equal, which is why its `_has_valid_raw` walks past such files without inspecting `X`.
2. **`X` holds NaN or infinite values** — reported before the rest, which a non-finite entry makes unreliable rather than merely wrong.
3. **`X` above the `log1p` ceiling** (~20; `exp(20)` is 4.8e8 counts in one cell) — raw counts in `X`, or a normalization that was never log-transformed.
4. **`X` holds no positive values** — the matrix was emptied or dropped.
5. **`layers['desouped_counts']` holds NaN, infinities, negatives, or no counts** — it cannot serve as the reference. Checked before it is trusted, because such a layer does not make checks 8–9 fail, it makes them silently not happen: every sampled row drops out of the comparison and the file reports clean. Nothing else would catch it — no vendored check reads layer *values*, only their encoding.
6. **`layers['desouped_counts']` exceeds `raw.X`** — the layer is not a desouped version of `raw.X`, so it cannot be trusted as the reference.
7. **No sampled cell could be compared** — the checks below would not run, and passing on that is indistinguishable from passing on a clean file. The whole-matrix checks do not cover it: they ask about `X` and `raw.X` as a whole, so an `X` whose first cells are empty or negative while later ones are not clears all four and still leaves the sample with nothing to compare.
8. **`X` disagrees with its source.** With the layer present that is the whole finding. Against `raw.X`, the recovered counts name the cause — a pipeline can remove counts but never invent them:

   | recovered counts | verdict |
   |---|---|
   | not whole numbers | `X` is not a normalization of any count matrix (a different transform, or altered afterwards) |
   | whole, only above `raw.X` | `X` came from a different matrix |
   | whole, only below `raw.X` | desouping ran and `layers['desouped_counts']` is missing |
   | whole, both above and below | both at once — desouping ran, *and* `raw.X` cannot be its source |

   The last row is a real population rather than a tolerance artifact; the corpus measurement that establishes that is recorded on `_implied_counts_verdict`.

9. **`X` log-transformed but never total-normalized** — every cell's recovered total is its own depth, so no rescaling was applied.

Silent when `raw.X` is absent: the vendored `_validate_raw` owns that case. Also silent when the layer's chunking does not match `X`'s — `read_backed` chunks CSC as `(n_obs, chunk_size)`, so sampling 200 rows off a CSC layer would read the layer whole; the vendored sparsity check has already errored on that encoding, so the file fails regardless.

Sampling: checks 1–4 scan both matrices in full; 5–9 use the first 200 cells, since the identity is per-cell and independent across cells.

Assay coverage: these run on every file, and do **not** yet inherit the ATAC-seq / Methyl-seq / methylation-profiling / snmC-seq exemptions that `hca_schema_definition.yaml` declares for raw-layer validation. HCA does not currently accept those assays; see the open issue before it does.

### 4.2 Donor-level consistency (`check_donor_consistency`)

Every obs row is otherwise validated on its own, so one `donor_id` carrying two sexes — a mis-join of two individuals, or a producer error — passed. This check groups obs by `donor_id` alone (one individual legitimately spans several `dataset_id` values in an integrated object) and looks at each donor's distinct non-null values per column. Port of the donor-metadata cell in Lattice's CELLxGENE curation notebook; the deviations are listed at the constant block in `validator.py`. #680.

| column | two or more real values | one real value + an unknown sentinel |
|---|---|---|
| `organism_ontology_term_id`, `sex_ontology_term_id`, `manner_of_death` (the LinkML Donor slots) | **error** | warning: can be filled in |
| `development_stage_ontology_term_id`, `disease_ontology_term_id` (Sample grain; longitudinal or tumor-plus-adjacent donors legitimately vary) | warning | warning: can be filled in |

Unknown values are `unknown`, `na`, and the empty string, on every column; `not applicable` is a claim. Null is never a claim. Rows whose `donor_id` is `pooled`, `unknown`, `na`, or empty are skipped, since none of those names one individual. One message per column and bucket, naming at most 10 donors with at most 5 values each. Silent when `donor_id` is absent. Reads obs only.

---

### 4.3 Declared gene annotation vs. the file's genes (`check_gene_annotation_version`)

`obs['gene_annotation_version']` records the annotation a dataset was built against and nothing verified it. Six of seven breast source datasets declare a release their own gene list rules out. Two independent comparisons, **warning-only** — the field is the producer's to correct, and the schema documents it with assembly accessions (#719), so some non-datable values are conforming rather than mistaken. #710.

**1. Declared assembly vs. `reference_genome`.** Needs no reference data. Compared per distinct (version, assembly) pair rather than per column: an integrated object legitimately carries cells from several assemblies, so the question is not whether `reference_genome` is unanimous but whether any pair contradicts itself. The message names the cells when the disagreement is confined to some of them. Values that name no assembly — a placeholder, or a malformed value the column's own enum already errors on — are skipped rather than compared.

**2. Declared release vs. the genes.** For each release, count the genes it cannot explain; the releases explaining all of them are the window that could have produced the file. Reported as both ends, not just the earliest: genes are **retired** as well as born (`ENSG00000130723` exists r76–r102 and then stops), so a declared release can be wrong by being too late. Nine declarations in the prod corpus are. Reported as contiguous runs (`r105 to r110`, or `r100 to r104 and r109 to r116`) rather than as a min–max span: a resurrected gene punches a hole, and a span would name releases that do not explain the file — including, where the hole contains it, the very release being reported as wrong. The absent genes are split by reason, since defined-after and retired-before say opposite things about the declaration.

The window is bounded by the table's coverage as well as by the genes. Where a run reaches r76 or r116, that end is the table's limit rather than something the genes establish — a gene retired at r102 pins the upper end, but the lower end is only "as far back as this reference data goes", and the gene may well exist in GRCh37 (`ENSG00000130723` does, in r75). Every file in the prod corpus has both ends pinned by genes, so this is a limit to know about rather than one that currently bites; it resolves when the table covers r55–r75 (#724).

| declared value | what happens |
|---|---|
| Ensembl release r76+ (`v98`) | dated against the gene list |
| number below r76 (`v32`) | **ambiguous** — Ensembl r32 or GENCODE 32; claims no assembly, converts neither |
| number above GENCODE's newest release, below r76 | only Ensembl has issued it. The boundary is the shipped table's top release minus GENCODE's offset of 66, so it moves when the table is regenerated — currently 50, making r51–r75 Ensembl-only. Of those, **r55–r75 are GRCh37** and **r51–r54 predate it** (NCBI36) and claim no assembly. Verified from the archive's own database names, grouped by assembly family — r48–r54 NCBI36, r55–r75 GRCh37, r76–r116 GRCh38, none with gaps. The suffix is not uniform: early GRCh37 releases carry a patch letter (`_56_37a` … `_62_37g`) and NCBI36 appears as `_36j` … `_36p`, so a query for plain `_37` sees only part of the range |
| release newer than the table | not checked; says so, and that message is the trigger to regenerate the table |
| assembly accession (`GCF_000001405.40`) | names a genome, not an annotation — reported as such, not as the producer's error |
| unparseable | silent; the schema pattern owns format errors |

Dates on human `ENSG` identifiers only, matched as an anchored `ENSG\d+` — gorilla identifiers are `ENSGGOG...` and a prefix test would date them as human. Spike-ins, other species and custom transgenes are excluded from dating and their count is named alongside whatever finding the file produces. They are not a finding in themselves: a file whose annotation is consistent says nothing about them, because carrying spike-ins is not a defect. One prod file in 208 has any. The declared organism gates the **assembly** comparison and nothing else: Ensembl numbers releases across all species, so r110 pairs with GRCh38 only for a human file and that comparison is withheld unless `organism_ontology_term_id` says human throughout. Dating is not withheld -- an `ENSG` identifier is a human gene whatever the column says, so a file declaring a non-human organism while carrying human genes is still dated against them, and the disagreement between the two is itself worth seeing.

Reads `var.index`, `obs['gene_annotation_version']`, `obs['reference_genome']` and `obs['organism_ontology_term_id']`. The reference data is `gene_release_intervals.csv.gz`; its regeneration procedure is in the package README.

**Limitation.** This dates a *gene list*. Prod files carry between 19.7% and 98.1% of the genes Ensembl defines at the earliest release that explains them, so most are filtered to detected genes and a few are close to a full reference. Filtering can only remove evidence — so the computed window is a superset of the true one. A declared release falling outside it is therefore sound; what is weakened is pinning the exact release, not the finding.

### 4.4 Retired feature identifiers (`check_retired_feature_ids`)

A summary of the per-identifier feature ID warnings (§5), not a replacement for them: those stay, and this says what they add up to. **#728.**

A retired Ensembl identifier is a warning here and an **error** at CELLxGENE, so every atlas heading for CZI has to clear them — but each warning says only that an identifier is not in the current GENCODE table, which is the same sentence for every cause. The breast v1 integrated object emits **1,482** of them for **741** distinct identifiers, counted once in `var` and once in `raw.var`.

Ensembl's `stable_id_event` records what became of each one, shipped as `gene_id_events.csv.gz` (format, event classes and regeneration in the package README). The identifiers are sorted into classes that need different fixes:

| tag | what happened | what it means |
|---|---|---|
| `[rename]` | renamed to X / merged into X | the successor is in the allowed gene set and not already in this file |
| `[review]` | renamed to X / merged into X, which is already in this file, or shared with other IDs here | renaming would leave columns sharing a name, so whether to add the counts is a decision |
| `[drop]` | retired, no successor | nothing in the allowed gene set to point at |
| `[drop]` | successor not in the allowed set | the successor is on a patch or alt sequence, or postdates the set |
| `[drop]` | patch or alt sequence | not on the primary assembly, so no reference gene set carries it |
| `[drop or re-align]` | split into X, Y | the reads cannot be divided after the fact, but are recoverable under the successors' names |
| `[strip suffix]` | version suffix | the gene is in the allowed gene set; the written form is not |
| `[none]` | issued after GENCODE v48 | a real current gene; the file's annotation is newer than the allowed set, not wrong |
| `[ask]` | no event recorded | in neither the allowed gene set nor Ensembl's GRCh38 event history |

**What "current" means here.** The gene set a file is validated against is not all of Ensembl. It is GENCODE's reference annotation — **Ensembl 114 restricted to the primary assembly** — the chromosomes plus the unplaced and unlocalized scaffolds, excluding alt loci and patches. Measured against r114: Ensembl lists 86,364 human genes, this set holds 78,894 — 78,686 on chromosomes and 208 on scaffolds — and every one of the 7,470 absent sits on a patch or alt sequence. Aligners count against the primary assembly for the same reason it is drawn that way — include a region and its alternate copy and reads map to both — so a successor annotated only on a patch is alive in Ensembl and still unusable as a column name. That is the **off the reference** class, 13 identifiers table-wide; CELLxGENE rejects such a column too. The sentence the check prints is derived from the vendored `gene_info.yml`, so bumping `cellxgene-schema` moves it.

Three populations used to share the unclassified bucket, and the shipped interval table separates them offline. Of the genes it holds that the reference does not, **7,470** were already present at the reference's release and every one sits on a patch or alt contig; **87** were first issued afterwards and every one is on a primary chromosome. No crossover. The first group matters in practice — **3,231 of them appear across eight prod files** (six MSK, one heart, one pancreas), and one MSK file alone carries 1,964. Carrying many of these means the file was aligned against a reference that includes patch sequences, which almost nothing does and which makes its counts hard to compare. The second group is dormant: no prod file carries one yet.

**Chains are followed.** Ensembl may replace A with B and later B with C, and renaming A to B leaves an identifier CELLxGENE still rejects. Every hop is a row in the shipped table, so the walk needs no network; the notebook this came from had to go back to the server for it, because it only knew about the identifiers in one atlas.

**Claimed replacements are held against the genome**, offline, from spans the table carries: if two identifiers describe the same DNA, the old gene's position in the last release that carried it falls inside its successor's span, on the same chromosome and strand. Three outcomes, not two. **Contained** confirms the record. **Overlapping but not nested** means Ensembl redrew where the gene starts or ends as well as renaming it — the replacement stands, and the two annotations simply disagree about its extent. **Contradicted** — a different chromosome, the opposite strand, or no overlap at all — is the one Ensembl's record cannot be right about. The separation matters because the failures are not alike: across the shipped table 14 pairs overlap, 20 do not overlap, and 19 sit on the opposite strand. On breast v1, 670 of 673 are contained, **3 overlap** (two of them by 4 and 5 bases) and **none are contradicted** — reporting those three as contradictions sent a curator to the genome browser over rounding. The old coordinates are per-gene, from each identifier's own last release, which is why none are unexplainable; comparing everything against one old release left 8 of breast's genes absent from both ends.

**Why `successor already present` is not a mechanical fix.** Renaming would produce two columns with one name. Where a source study was aligned against an annotation that treated the two as separate loci, its cells legitimately carry counts in both and summing them double-counts. Which pairs are safe to sum is a cross-file question (#530) and the merge itself is the producer's call.

**Every warning in the pile carries its own verdict.** The summary can name only a handful of examples per class, so on a file with 625 identifiers in one class it describes the problem and withholds the data needed to act on it. Each per-identifier warning is therefore annotated with the fate of the gene it names, which makes the pile the per-gene answer and the summary its index — `grep "\[rename\]"` returns the list of renames:

```
Feature ID 'ENSG00000148362' in 'var' not found in GENCODE v48 (Ensembl 114): now ENSG00000310560 [rename]
Feature ID 'ENSG00000236938' in 'var' not found in GENCODE v48 (Ensembl 114): now ENSG00000285090 (in file) [review]
Feature ID 'ENSG00000224247' in 'var' not found in GENCODE v48 (Ensembl 114): retired, no successor [drop]
Feature ID 'ENSG00000282823' in 'var' not found in GENCODE v48 (Ensembl 114): patch or alt sequence [drop]
```

**What happened and what to do are separate fields**, because they do not map one to one: the same Ensembl merge is a plain rename when its target is absent from the file and a judgement call when it is already there. The action is a bracketed tag so it is greppable, and the reasoning behind each is stated once in the finding that counts the class rather than repeated on every line.

Warnings naming an identifier this check does not classify — a spike-in, another species — are left untouched, and the `Feature ID '` prefix both warning sorters match on is preserved.

Reads `var.index` and `raw.var.index`, nothing else — no `obs`, no network. Counts are over distinct identifiers; the warning count is reported beside them, which is where 1,482 becomes 741.

---

## 5. Vendored `cellxgene_schema` checks (shared by CXG and HCA validators)

### File / structure

- h5ad encoding-version is `0.1.0` (AnnData 0.8+).
- `obs`, `var`, `raw.var` column names are unique.
- No `obs`/`var` columns with `__` prefix (reserved).
- No reserved/add-labels columns present when `ignore_labels=False`.
- Deprecated columns absent (`ethnicity`, `ethnicity_ontology_term_id`, `organism`, `organism_ontology_term_id` in CXG).

### `obs`

- `obs` exists; index is unique.
- All required columns exist; no forbidden/deprecated columns.
- Categorical columns are `category` dtype; bool columns are `bool` dtype; categories are single-typed and not bool.
- No empty strings in categorical columns; no unused categories (warning).
- No NaN in columns that don't declare NaN-permitting dependencies.
- `unique`-flagged columns contain no duplicates.
- Enum columns contain only allowed values; forbidden/deprecated ontology terms rejected; ancestor constraints enforced.
- Multi-term (delimited) values are sorted ascending with no duplicates.
- < 20 000 rows triggers a warning about filtered features.

### `var` / `raw.var`

- `var` exists; indices unique.
- No mixed-type columns.
- `raw.var` must not contain `feature_is_filtered`.
- `var.feature_is_filtered` is bool; if no raw, all `False`; if raw exists, see X/raw.X rules below.

### Feature IDs (GENCODE)

- Each feature ID must map to a supported organism: human, mouse, SARS-CoV-2, ERCC, drosophila, zebrafish, C. elegans, macaque, rabbit, marmoset, gorilla, rhesus, chimp, pig, mouse lemur, rat.
- Each feature ID must be valid within its organism's GENCODE table.
- Dataset organism vs. feature-ID organism mismatch → warning (HCA adds GENCODE version label).
- These warnings are one per feature ID per dataframe, so a retired identifier in `var` and `raw.var` produces two. HCA classifies the human ones into actionable groups in §4.4; the individual warnings are left in place beneath that summary.

### Ontology-term columns in `obs` (all errors)

- `cell_type_ontology_term_id` — CL/ZFA/FBbt/WBbt per organism; special rules for cell lines.
- `tissue_ontology_term_id` — UBERON or organism-specific equivalent.
- `assay_ontology_term_id` — EFO; non-deprecated.
- `disease_ontology_term_id` — MONDO.
- `development_stage_ontology_term_id` — HsapDv/MmusDv per organism.
- `sex_ontology_term_id` — PATO.
- `organism_ontology_term_id` — NCBITaxon allowlist.

### `uns`

- `uns` required.
- `organism_ontology_term_id` (CXG only — CURIE + NCBITaxon allowlist).
- `title` — non-empty string; no leading/trailing/double spaces.
- `batch_condition` — list of `obs` column names.
- `default_embedding` — must exist as a key in `obsm`.
- `X_approximate_distribution` — `"count"` or `"normal"`.
- No empty values; string values have no leading/trailing/double spaces.
- `*_colors` keys: corresponding categorical column exists in `obs`; value is `np.ndarray` of strings; ≥ n_categories entries; all hex (`#RRGGBB`) or all CSS4 names, not mixed.

### `X` and `raw.X`

- Non-zero values are `float32`.
- Encoding is dense or `csr` (reject `csc`/`coo`).
- If sparsity > 0.5, must be `csr_matrix`.
- `raw.X` non-zero values are positive integers.
- Every cell has ≥ 1 non-zero value in the raw matrix (Visium `in_tissue==0` has its own rules).
- `raw.X` present when schema requires it (RNA-seq); warning if only raw exists and no normalized X.
- `feature_is_filtered` consistency: `True` ⇒ X column all zero; X all-zero column ⇒ either filtered or `raw.X` all-zero too.
- If both X and `raw.X` exist: same n_obs, n_var, `obs.index`, `var.index`.
- Visium `is_single=True`: raw must be exactly 4 992 rows (standard) or 14 336 rows (11M).

### `obsm`

- At least one embedding for non-spatial assays.
- Keys match `^[a-zA-Z][a-zA-Z0-9_.-]*$`; `X_…` suffix must match the same pattern.
- `x_spatial` forbidden; `spatial` key allowed with shape `(n_obs, ≥2)`.
- Non-`X_`/non-`spatial` keys → "won't appear in Explorer" warning.
- Every embedding: `np.ndarray`, ≥ 2 dims, first dim == n_obs, numeric dtype, no Inf.
- `X_…`/`spatial` ≥ 2 columns; others ≥ 1.
- `spatial` contains no NaN; other embeddings can't be all-NaN.

### Spatial assays (Visium / Slide-seqV2)

- Spatial metadata only for Visium descendants (`EFO:0010961`) or Slide-seqV2 (`EFO:0030062`); `EFO:0010961` itself is rejected (a descendant is required).
- Single assay per dataset.
- `uns['spatial']` is a dict containing boolean `is_single`; exactly one `library_id` (when applicable).
- `library_id` dict contains only `images` and `scalefactors`.
- `images.hires` required: `uint8` ndarray, 3D `(H, W, 3|4)`, largest dim 2 000 (or 4 000 for Visium 11M).
- `images.fullres` optional; same dtype/shape rules if present (warning if missing).
- `scalefactors.spot_diameter_fullres` and `scalefactors.tissue_hires_scalef` required floats.
- `obs.array_row`, `obs.array_col`: int, in range per platform, non-null — required for Visium `is_single=True`, forbidden otherwise.
- `obs.in_tissue`: 0 or 1 only; special raw-matrix rules when zeros are present.
- `obs.cell_type_ontology_term_id == "unknown"` where `in_tissue==0`.
- `obs.is_primary_data == False` when `is_single=False`.

### Duplicates (`validation_internals/check_duplicates.py`)

- No exact duplicate rows in the raw count matrix (per-row hash). For Visium, rows with `in_tissue==0` are excluded first.

### ATAC-seq (`atac_seq.py`, when fragment file validated)

- Organism is human or mouse (`NCBITaxon:9606` / `NCBITaxon:10090`).
- All `obs.is_primary_data == True`.
- Fragments: chromosomes valid for organism; `start > 0`; `stop > start`; `stop ≤ chromosome length`; `read_support > 0`; no duplicate fragments; barcodes are a subset of `obs.index`.

---

## Cross-reference

| Stage | Source | Fail mode |
|---|---|---|
| Env & S3 integrity | `main.py` | Hard fail, no tool reports |
| Metadata summary | `main.py:read_metadata` | Exception → failure message |
| CAP | `cap_validator_script.py` | `tool_reports.cap.errors` |
| CELLxGENE | `services/cellxgene-validator` → vendored `validate()` | `tool_reports.cellxgene` |
| HCA | `services/hca-schema-validator` → `HCAValidator` | `tool_reports.hcaSchema` |
