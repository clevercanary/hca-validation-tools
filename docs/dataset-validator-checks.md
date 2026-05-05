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
- **`pattern` regex on columns** — errors on values that don't fullmatch; uses `pattern_description` for the error text.
- **`element_type: string` on lists** — errors on non-string or whitespace-only entries.
- **Raw-layer retry** — re-runs `_validate_raw()` if the base class skipped it but `assay_ontology_term_id` exists.
- **GENCODE-aware feature-ID warnings** — warning text includes a GENCODE version label, plus a dataset-organism vs. feature-ID-organism mismatch warning (excluding exempt organisms).
- **Warning reordering** — feature-ID warnings pushed to the end.

All other rules come from the vendored base class (§5).

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

### Ontology-term columns in `obs` (all errors)

- `cell_type_ontology_term_id` — CL/ZFA/FBbt/WBbt per organism; special rules for cell lines.
- `tissue_ontology_term_id` — UBERON or organism-specific equivalent.
- `assay_ontology_term_id` — EFO; non-deprecated.
- `disease_ontology_term_id` — MONDO.
- `development_stage_ontology_term_id` — HsapDv/MmusDv per organism.
- `sex_ontology_term_id` — PATO.
- `self_reported_ethnicity_ontology_term_id` — HANCESTRO.
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
