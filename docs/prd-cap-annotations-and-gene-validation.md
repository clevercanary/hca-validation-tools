# PRD: CAP Annotations & Gene Reference Validation

This PRD covers three related features, ordered by dependency:

1. **Gene reference validation** (#255) — check var Ensembl IDs and symbols against GENCODE. *Lives in hca-schema-validator. Not on the critical path for #254 — documented here for context.*
2. **CAP marker gene validation** (#256) — verify marker genes cited in CAP annotations exist in var. *Lives in hca-anndata-tools.*
3. **Copy CAP annotations** (#254) — copy CAP metadata from source h5ad into HCA-converted target. *Lives in hca-anndata-tools. Depends on the GENCODE name lookup from #256 for rename detection.*

---

## 1. Gene Reference Validation (#255)

> **Note:** This lives in hca-schema-validator, not hca-anndata-tools. It is not on the critical path for #254. Documented here for context and because the GENCODE reference data is reused by #256 for rename detection.

### Summary

Add deterministic gene reference validations to hca-schema-validator that check var against the vendored GENCODE reference. No LLM required to run — just loads the reference CSV, compares, and reports.

**Important: These validations are report-only. They MUST NOT auto-fix or update gene names.** Updating feature_name would break reproducibility for downstream consumers — models may already be trained, integrations built, and analyses published using the existing names. The validator reports what it finds; the wrangler decides whether and when to act.

### Validations

#### 1a. Ensembl ID exists in GENCODE reference

**Check:** For each Ensembl ID in var index, verify it exists in `genes_homo_sapiens.csv.gz`.

**Severity:** Warning

**Rationale:** A retired Ensembl ID means the gene model was reclassified as an artifact, merged into another gene, or deemed not real by GENCODE annotators. Counts against retired IDs can't be validated or compared across datasets that use the current reference. These are almost always non-coding RNAs from older annotation versions.

**What we found:** 931 retired genes in the ocular CAP file (all absent from GENCODE v48). Zero in the CXG-processed version of the same dataset, because CXG re-annotates var on ingest — it drops genes that aren't in its current GENCODE release (v48 / Ensembl 114) and maps all remaining genes to current symbols.

**Why not an error:** The counts themselves aren't wrong — they reflect real reads that mapped to a sequence. The gene model was simply reclassified in a newer annotation. Contributor data shouldn't be rejected for using an older reference.

**Why not ignored:** Retired gene IDs can't participate in cross-dataset comparisons or marker gene validation. Knowing how many retired IDs a file contains is a useful signal for how stale its gene reference is.

**Note:** Consider persisting the stale gene count and other QC metrics somewhere in the h5ad (e.g., an internal uns field for QC reports). See #257.

#### 1b. Gene symbol matches GENCODE reference

**Check:** For each Ensembl ID in var that exists in the GENCODE reference, compare `feature_name` to the reference gene symbol. Report mismatches in two categories:

- **Real renames:** File has a different proper symbol than the reference (e.g., `PIFO` → `CIMAP3`)
- **Gained a name:** File has a versioned Ensembl ID as feature_name but the reference now has a proper symbol (e.g., `ENSG00000215014.5` → `SSU72-AS1`)

Do NOT report cases where both the file and the reference use an Ensembl ID (with or without version suffix) — these are genuinely unnamed genes, not a data quality issue.

**Severity:** Warning

**Rationale:** Stale gene symbols cause silent failures in downstream analysis. Someone searching for CIMAP3 expression won't find it if the file still calls it PIFO. It also breaks marker gene validation — CAP annotations may use the new HGNC name while the file has the old one. Stale symbols also cause joins to fail when merging datasets annotated against different GENCODE versions.

**What we found:** 201 real renames in the ocular CAP file, from three main HGNC renaming campaigns:
- **Placeholder cleanup:** C1orf112 → FIRRM, C9orf24 → SPMIP6, C12orf4 → FERRY3
- **FAM gene standardization:** FAM104A → VCF1, FAM166A → CIMIP2A, FAM172A → ARB2A
- **Cilia/sperm motility genes:** ODF3 → CIMAP1A, PIFO → CIMAP3, TEX33 → CIMIP4, TTC26 → IFT56
- **Individual renames:** TDGF1 → CRIPTO, ADAL → MAPDA, PRPF4B → PRP4K

Plus 148 genes that gained a symbol since the contributor's reference (were unnamed, now have proper HGNC symbols).

Zero mismatches in the CXG-processed file (CXG re-annotates var against current reference).

**Why not an error:** The Ensembl ID is correct and the counts are valid. The symbol is cosmetic metadata — wrong but not data-corrupting.

**Why not ignored:** Stale symbols break searchability, cross-dataset joins on gene name, and marker gene validation. Reporting them lets wranglers decide whether to update feature_name or leave as-is.

**Why report-only, never auto-fix:** Gene name updates must be an explicit, optional wrangler action — never automatic. Downstream consumers (trained models, published analyses, integrated atlases) may depend on the existing names. Silently updating feature_name breaks reproducibility. The validator surfaces the information; the wrangler chooses when updating is safe.

### Implementation notes

- **Location:** Lives in `packages/hca-schema-validator/`. The GENCODE reference CSVs are already vendored there.
- **Reference data:** Already vendored at `packages/hca-schema-validator/src/hca_schema_validator/_vendored/cellxgene_schema/gencode_files/genes_homo_sapiens.csv.gz`. hca-anndata-tools will copy the reference CSVs it needs for rename detection (#256) independently.
- **Deterministic:** Load reference CSV into a dict, compare against var. No external calls, no LLM.
- **Fast:** Reference is ~79K genes, var is typically 20-40K. Single pass, O(n) lookup.
- **Organism-aware:** Use `organism_ontology_term_id` to select the correct reference file (human, mouse, etc.)
- **Report format:** Include counts and specific gene lists so wranglers can assess severity. Example:
  ```
  Gene reference: GENCODE v48 (Ensembl 114)
  Ensembl IDs checked: 35,477
  Missing from reference: 931 (retired gene models)
  Symbol mismatches: 201 (renamed), 148 (gained name)
  ```

### What we explicitly chose NOT to validate

- **Unnamed genes (ENSG as feature_name matching reference):** ~10,134 genes in the ocular CAP file have no HGNC symbol in either the file or GENCODE v48. This is a property of the genome annotation, not a data quality issue. Reporting them would generate thousands of non-actionable warnings.
- **Version suffix differences (ENSG*.1 vs ENSG*):** CXG strips version suffixes, contributors may keep them. Not meaningful for data quality.

---

## 2. CAP Marker Gene Validation (#256)

### Summary

When CAP annotations are present in an h5ad file, validate that the marker genes cited as evidence for cell type calls actually exist in the file's var. Deterministic check — no LLM required.

### Validations

#### 2a. Marker genes exist in var

**Check:** Parse gene symbols from all `*--marker_gene_evidence` obs columns. For each unique gene symbol, verify it exists in `var['feature_name']`.

**Severity:** Warning (typo or reference mismatch), Info (known rename)

**Rationale:** CAP marker genes are the evidence trail for a cell type call — they're the reason a cell was labeled "alveolar macrophage" instead of "monocyte." If a marker gene doesn't exist in var, you can't verify the annotation against the expression data in this file. The cell type label becomes unverifiable for that marker.

**What we found:** In the ocular scRNA-seq CAP file, 159 of 161 unique marker genes were found in var. Two were missing:
- `CIMAP3` — not a typo, but a HGNC rename of `PIFO` (which IS in var). The CAP annotator used the new name, the file has the old name.
- `SCL25A5` — typo for `SLC25A5` (transposed C and L).

#### 2b. Distinguish typos from known renames

**Check:** When a marker gene is not found in var, check if it's a known current HGNC symbol that maps to an older symbol present in var. This requires a reverse lookup: given a current gene name, find what it was previously called.

**Severity:**
- **Known rename (marker uses new name, var has old name):** Info — the data is fine, the gene reference versions just differ. Report both names so the wrangler can see the mapping.
- **Not a known rename (probable typo):** Warning — this is an annotation error in CAP that should be reported back to the CAP authors.

**Rationale:** Without this distinction, every rename produces a false positive. CIMAP3 was flagged as "missing" but the gene exists in var under its old name PIFO. Reporting this as the same severity as a genuine typo (SCL25A5) wastes the wrangler's time investigating a non-issue. The rename case is informational; the typo case is actionable.

**What we found:** Of the 2 missing markers in the ocular dataset:
- 1 was a rename (CIMAP3/PIFO) — info
- 1 was a typo (SCL25A5) — warning

### Implementation notes

#### Marker gene extraction
```
For each obs column matching *--marker_gene_evidence:
    For each unique value (skip "unknown", "", null):
        Split on comma
        Strip whitespace
        Add to set of marker genes
```

#### Var gene set
```
gene_names = set(var['feature_name'])
```

#### Missing gene classification

For the rename lookup, two options:

**Option A: Build from GENCODE reference (simpler, partial coverage)**
- Load `genes_homo_sapiens.csv.gz` into a name→ensembl_id dict
- If a missing marker gene IS in the GENCODE reference (meaning it's a valid current symbol), look up its Ensembl ID, then check if that Ensembl ID exists in var under a different feature_name
- If found: it's a rename (var has old name, marker has new name)
- If not found: it's either a typo or a gene not in this file at all

**Option B: Use HGNC alias table (comprehensive, requires external data)**
- HGNC publishes a complete download with previous symbols, alias symbols, and current approved symbols
- Would catch renames across all HGNC history, not just what's in the current GENCODE release
- Adds an external dependency that needs periodic updating

Recommend starting with Option A — it uses data we already have vendored and covers the most common case (CAP annotator used current name, file has older name).

#### Report format
```
CAP marker gene validation:
  Annotation sets with markers: 1 (author_cell_type)
  Unique marker genes: 161
  Found in var: 159
  Missing — known rename: 1
    CIMAP3 → PIFO (ENSG00000173947, renamed in GENCODE v48)
  Missing — probable typo: 1
    SCL25A5 (did you mean SLC25A5?)
```

### What we explicitly chose NOT to validate

- **Marker gene expression levels:** We don't check whether the marker genes are actually highly expressed in the cells they're supposed to mark. That would require loading the expression matrix and defining thresholds — a much heavier analysis that belongs in a separate tool.
- **Marker gene completeness:** We don't check whether the marker set is "sufficient" for the cell type call. That's a biological judgment, not a data quality check.
- **Canonical marker genes column:** The `*--canonical_marker_genes` column was 85% "unknown" in the lung dataset. We validate `marker_gene_evidence` only, since that's what annotators actually fill in.

---

## 3. Copy CAP Annotations (#254)

### Summary

Add a new MCP tool `copy_cap_annotations` that copies CAP (Cell Annotation Platform) annotation data from a source h5ad file to a target h5ad file, after validating prerequisites.

### Motivation

When working with HCA datasets, CellxGENE files are first converted to HCA format, then CAP cell annotation metadata needs to be copied from the CAP-annotated source into the HCA-converted file. Currently there's no tool to do this — you'd have to manually extract and re-attach the annotations.

Real-world example: the ocular outflow dataset has a CAP source file (4.8G) and an HCA-converted file (3.1G) with the same 332,995 cells. The CAP annotations need to be copied into the HCA file.

### Pre-copy validations (ordered by cost — fail fast on cheap checks)

#### 1. Source has CAP annotations
- `cellannotation_metadata` exists in source uns
- `cellannotation_schema_version` exists in source uns
- At least one annotation set is defined in `cellannotation_metadata`
- **Fail if not met** — nothing to copy.

#### 2. Target doesn't already have CAP columns
- No `--` prefixed columns exist in target obs that would be overwritten
- **Fail if not met** — don't silently clobber existing annotations.
- **`overwrite` flag** (default: false) — if true, remove existing CAP `--` columns and CAP uns keys before proceeding. This supports the iterative workflow where CAP data is copied, issues are found, fixes are made, and CAP needs to be re-imported.

#### 3. Cell identity match
- Same number of cells (n_obs) in source and target
- Same obs index values (cell IDs must match exactly, order can differ)
- **Fail if not met** — these aren't the same dataset.

#### 4. Marker genes exist in target var
- Parse gene symbols from all `*--marker_gene_evidence` columns in source
- Check each exists in target `var['feature_name']`
- If missing: check if it's a known GENCODE rename (info) vs probable typo (warning)
- **Does not block the copy** — warn only. Missing marker genes don't invalidate the annotations.
- See #256 for detailed marker gene validation spec

#### 5. Required HCA annotation fields are populated
Per the [HCA cell annotation schema](https://data.humancellatlas.org/metadata/cell-annotation#annotation), verify the CAP source has all required fields populated for each annotation set:

**Per cell label (required, stored in obs as `<set_name>--<field>`):**
- `cell_fullname`
- `cell_ontology_exists`
- `cell_ontology_term_id`
- `cell_ontology_term`
- `rationale`
- `marker_gene_evidence`
- `canonical_marker_genes`
- `synonyms`
- `category_fullname`
- `category_cell_ontology_exists`
- `category_cell_ontology_term_id`
- `category_cell_ontology_term`

**Per annotation set (required, stored in uns `cellannotation_metadata`):**
- `description`
- `algorithm_name`
- `algorithm_version`
- `algorithm_repository_url`
- `annotation_method`

Report which required fields are missing or have placeholder values ("unknown", "NA", "", null). **Does not block the copy** — warn with a summary so the wrangler knows what needs to be filled in after copy.

**Per cell label (optional, copy if present):**
- `rationale_dois`
- `cell_ontology_assessment`

**Per annotation set (optional, copy if present):**
- `reference_location`
- `reference_description`
- `clustering`

### What to copy

#### obs columns (matched by obs index)
Only the primary CAP annotation set columns — the real cell type annotations:
- `<set_name>--cell_fullname`
- `<set_name>--cell_ontology_exists`
- `<set_name>--cell_ontology_term_id`
- `<set_name>--cell_ontology_term`
- `<set_name>--rationale`
- `<set_name>--rationale_dois` (if present)
- `<set_name>--marker_gene_evidence`
- `<set_name>--canonical_marker_genes`
- `<set_name>--synonyms`
- `<set_name>--category_fullname`
- `<set_name>--category_cell_ontology_exists`
- `<set_name>--category_cell_ontology_term_id`
- `<set_name>--category_cell_ontology_term`
- `<set_name>--cell_ontology_assessment` (if present)

Also copy `cell_type--*` enrichment columns if present:
- `cell_type--cell_fullname`
- `cell_type--cell_ontology_exists`
- `cell_type--cell_ontology_term`

#### uns metadata

Copied as-is (already namespaced):
- `cellannotation_schema_version`
- `cellannotation_metadata`
- `cap_dataset_url`
- `cap_publication_title`
- `cap_publication_description`
- `cap_publication_url`

Renamed on copy to avoid collisions with HCA/CXG fields (source name → target name):
- `authors_list` → `cap_authors_list`
- `hierarchy` → `cap_hierarchy`
- `description` → `cap_description`
- `publication_timestamp` → `cap_publication_timestamp`
- `publication_version` → `cap_publication_version`

NOT copied (CXG fields, already in target or handled by HCA conversion):
- `citation`, `schema_version`, `schema_reference`, `default_embedding`, `title`

#### What NOT to copy
- `sex--cell_ontology_term_id` — just a rename of the CXG column. HCA/CXG `sex_ontology_term_id` is authoritative.
- `development_stage--cell_ontology_term_id` — same, CXG column is authoritative.
- `self_reported_ethnicity--cell_ontology_term_id` — same, and ontology versions can diverge (we found HANCESTRO:0014 vs HANCESTRO:0612 for the same ethnicity between CAP and CXG).
- `cell_type--cell_ontology_term_id` — rename of CXG column, already in target.
- The `user_provided` layer — large, not needed for annotations.
- Any var changes — target var is authoritative.

### Post-copy
- Log the operation in `hca_edit_log` with:
  - `operation`: `import_cap_annotations`
  - `source_file`: filename of the CAP source file
  - `source_sha256`: hash of the CAP source file for provenance
  - `cap_schema_version`: the `cellannotation_schema_version` from the source
  - `annotation_sets`: list of annotation set names copied
  - `obs_columns_added`: list of obs columns added
  - `uns_keys_added`: list of uns keys added (using target names, e.g., `cap_authors_list`)
  - `warnings`: any marker gene or field completeness warnings
- Report: number of obs columns copied, list of uns keys copied, any validation warnings

### Validation report format
```
CAP Copy Validation:
  Source: public-anndata_project-557_2_...h5ad
  Target: scrna-seq-of-human-ocular-...h5ad
  
  Source has CAP: PASS (schema v1.0.2, 1 annotation set)
  Target clean: PASS (no existing CAP columns)
  Cell identity: PASS (332,995 cells, all IDs match)
  
  Annotation set: author_cell_type
    Required fields populated: 12/12
    Optional fields present: 0/2
    Marker genes in target var: 159/161
      Known rename: CIMAP3 → PIFO (ENSG00000173947)
      Probable typo: SCL25A5 (did you mean SLC25A5?)
  
  Ready to copy: YES (2 warnings)
```

---

## Related issues
- #255 — Gene reference validation
- #256 — CAP marker gene validation
- #254 — Copy CAP annotations
