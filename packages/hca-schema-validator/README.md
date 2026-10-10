# HCA Schema Validator

Validates single-cell data files in h5ad format (the
[AnnData](https://anndata.readthedocs.io/) file format) against the Human Cell
Atlas (HCA) metadata schema.

The checks fall into three groups:

- **Core CELLxGENE checks.** This package extends the CELLxGENE schema validator
  from the Chan Zuckerberg Initiative (CZI). A copy of the CELLxGENE validator
  (`cellxgene-schema` 7.0.1) ships with the package and runs on every file.
- **HCA overrides.** HCA replaces some CELLxGENE rules with its own.
- **HCA extensions.** HCA adds checks that CELLxGENE does not have.

The validator reports two kinds of finding:

- **Errors**: the file does not meet the schema.
- **Warnings**: something to review or fix. A missing **strongly recommended**
  field is a warning, not an error.

## Installation

### From PyPI (Recommended)

```bash
pip install hca-schema-validator
```

### From Source (Development)

Install uv by whichever method you prefer — see the
[official installation guide](https://docs.astral.sh/uv/getting-started/installation/).
On macOS `brew install uv` and `pipx install uv` are both auditable alternatives
to the piped install script. Any method works; uv's version is what matters, not
how it got there.

```bash
# Clone the repository
git clone https://github.com/clevercanary/hca-validation-tools.git
cd hca-validation-tools/packages/hca-schema-validator

# Install dependencies and package
uv sync

# Run tests
uv run pytest tests/
```

## Usage

```python
from hca_schema_validator import HCAValidator

# Create validator instance
validator = HCAValidator()

# Validate an h5ad file
is_valid = validator.validate_adata("path/to/file.h5ad")

# Check results
if is_valid:
    print("✅ Validation passed!")
else:
    print("❌ Validation failed:")
    for error in validator.errors:
        print(f"  - {error}")
```

## What this validator checks

Each check is listed with the reason for it. The rules the gene ID checks are
built against are in the
[gene ID contract](https://github.com/clevercanary/hca-validation-tools/blob/main/docs/gene-id-contract.md).

### Parts of an h5ad file

- **`obs`**: the table of cells and their metadata
- **`var`** and **`raw.var`**: the tables of genes
- **`uns`**: metadata for the whole file
- **`X`**: the normalized expression matrix
- **`raw.X`**: the raw count matrix
- **`layers`**: extra matrices stored alongside `X`, such as
  `layers['desouped_counts']`
- **`obsm`**: cell embeddings, such as UMAP coordinates

## Core CELLxGENE checks

CELLxGENE is CZI's single-cell data portal, and the CELLxGENE schema defines
what the portal accepts. The CELLxGENE validator runs every check in this
section. Groups marked *HCA override* behave differently for HCA files, as
described in [HCA overrides](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#hca-overrides).

### File structure

*[HCA override](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#hca-overrides)*

- The h5ad encoding version is `0.1.0`, as written by AnnData 0.8 or later.
- Column names in `obs`, `var` and `raw.var` are unique.
- No column name starts with `__`, which is reserved.
- Reserved and deprecated columns are absent.

### Cell metadata (`obs`)

*[HCA override](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#hca-overrides)*

- `obs` exists, and every cell ID is unique.
- Every required column is present.
- Category columns are stored as categories, and true/false columns as
  booleans. A category column holds one kind of value and no empty strings.
  Unused categories are a warning.
- Values are only missing where the schema allows.
- Columns marked unique hold no repeated values.
- Columns with a fixed list of allowed values hold only those values.
- A cell with several values in one column lists them sorted, with no repeats.

### Ontology terms (`obs`)

Each term must come from the right ontology, must not be deprecated, and in
some columns must sit below a given parent term. Every problem here is an error.

- **Cell type**: the Cell Ontology (CL), or the zebrafish, fruit fly or worm
  equivalent for those organisms. Cell lines have their own rules.
- **Tissue**: UBERON (the Uber-anatomy Ontology), or the organism's equivalent.
- **Assay**: EFO (the Experimental Factor Ontology).
- **Disease**: MONDO (the Mondo Disease Ontology).
- **Development stage**: HsapDv for human, MmusDv for mouse.
- **Sex**: PATO (the Phenotype And Trait Ontology).
- **Organism**: an allowed term from the NCBI Taxonomy.

### Genes (`var`, `raw.var`)

*[HCA override](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#hca-overrides)*

- `var` exists, and every gene ID is unique.
- No column mixes value types.
- Fewer than 20,000 genes is a warning, because the file may have been filtered
  to fewer genes.
- Every gene ID belongs to a supported organism (human, mouse, SARS-CoV-2, ERCC
  spike-ins, and several model organisms and primates) and appears in that
  organism's gene list. An ID missing from the list is a warning.
- A gene ID from a different organism than the file's is a warning.
- `var['feature_is_filtered']` is true/false, and is all false when the file has
  no raw matrix. `raw.var` must not have this column.

### File metadata (`uns`)

*[HCA override](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#hca-overrides)*

- `uns` exists.
- `title` is not empty and has no leading, trailing or double spaces.
- `batch_condition` lists `obs` column names.
- `default_embedding` names an embedding in `obsm`.
- `X_approximate_distribution` is `count` or `normal`.
- No value is empty, and text values have no leading, trailing or double spaces.
- Color lists (`<column>_colors`) belong to an existing category column, have
  at least one color per category, and are all hex codes or all CSS color names.

### Matrices (`X`, `raw.X`)

*[HCA override](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#hca-overrides)*

- Non-zero values in the raw matrix (`raw.X`, or `X` when there is no
  `raw.X`) are 32-bit floats.
- Matrices are dense or CSR (compressed sparse row). CSR is required when more
  than half the values are zero.
- Non-zero raw counts are whole positive numbers.
- Every cell has at least one raw count. Visium spots outside the tissue follow
  a separate rule.
- RNA-seq files have a raw matrix. A file with only a raw matrix and no
  normalized `X` gets a warning.
- A gene marked filtered (`feature_is_filtered`) is all zeros in `X`. A gene
  that is all zeros in `X` is either marked filtered or all zeros in `raw.X` too.
- `X` and `raw.X` hold the same cells and genes, in the same order.

### Embeddings (`obsm`)

- Every file has at least one embedding, and files from non-spatial assays have
  at least one named `X_…`.
- Embedding names start with a letter and use only letters, digits, `_`, `.`
  and `-`. `x_spatial` is not allowed.
- An embedding not named `X_…` or `spatial` gets a warning, because the
  CELLxGENE Explorer will not show it.
- Every embedding is a numeric array with one row per cell, at least two
  dimensions and no infinite values. `X_…` and `spatial` embeddings have at
  least two columns. `spatial` has no missing values, and other embeddings are
  not entirely missing.

### Spatial data

- Spatial metadata is allowed only for Visium (a specific Visium assay term, not
  the general one) and Slide-seqV2, with one assay per file.
- `uns['spatial']` holds an `is_single` true/false flag, and exactly one
  library when one applies.
- For a single-section Visium file:
  - the high-resolution image is required: 8-bit, height × width × 3 or 4, with
    a longest side of 2,000 pixels (4,000 for the 11 mm slide)
  - the full-resolution image is optional, and its absence is a warning
  - spot diameter and image scale factors are required
  - `obs['array_row']` and `obs['array_col']` are whole numbers within the
    slide's range
  - the raw matrix has exactly 4,992 spots (14,336 for the 11 mm slide)
- `obs['in_tissue']` is 0 or 1, and spots outside the tissue have cell type
  `unknown`.
- A file that is not a single section has `is_primary_data` set to false.

### Duplicate cells

- No two cells have identical raw counts. For Visium, spots outside the tissue
  are left out of this check.

## HCA overrides

HCA replaces some CELLxGENE rules with its own.

- **Schema.** HCA uses its own schema (`hca_schema_definition.yaml`) in place of
  the CELLxGENE schema:
  - Organism is recorded per cell, in `obs['organism_ontology_term_id']`.
    CELLxGENE expects organism once, in `uns`, and rejects the `obs` column as
    deprecated.
  - `uns['study_pi']` is required: a list naming the study's principal
    investigators, each a non-empty string.
  - Each field has a level:
    - **required** (the default): an error when missing
    - **optional**: checked only when present
    - **strongly recommended**: a warning when the column is absent or has
      missing values, and an error for an empty string, a value holding a list
      separator such as `,` or `;`, or a placeholder
    - **forbidden**: an error when present. Self-reported ethnicity is
      forbidden, because HCA does not collect it, to protect donor privacy.
  - Some fields must match a set format, and list fields must hold non-empty
    text.
- **Label columns.** CELLxGENE rejects files that already carry label columns
  such as `cell_type` and `tissue`, because the portal fills those labels in
  itself. HCA files keep the label columns, and HCA checks each label against
  its ontology term instead
  ([Cell metadata labels](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#cell-metadata-labels)).
- **Gene ID warnings.** Each `Feature ID '…' not found` warning names the gene
  set version, for example "not found in GENCODE v48 (Ensembl 114)", and these
  warnings are listed after all other warnings. Human IDs among them are grouped
  into one report
  ([Gene IDs outside the allowed gene set](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#gene-ids-outside-the-allowed-gene-set)).
- **Raw count checks.** CELLxGENE skips the raw count checks when a file already
  has errors. HCA runs them anyway, as long as `obs` has
  `assay_ontology_term_id`, so one pass shows more problems.
- **Extra `obs` columns.** Curators often add columns of their own, such as an
  original cell type. Columns that are not in the schema skip the per-column
  type and value checks, so warnings about columns the schema says nothing about
  do not bury the real findings.

## HCA extensions

HCA adds checks that CELLxGENE does not have.

### Expression matrices

HCA expects up to three matrices in a file, and the validator checks that they
agree with each other.

| Matrix | Expected | Holds |
|---|---|---|
| `raw.X` | Yes | Raw counts as 32-bit floats, with only empty droplets removed |
| `layers['desouped_counts']` | When ambient RNA was removed | The counts left after ambient RNA removal |
| `X` | Yes | `desouped_counts` (or `raw.X` when there is none), normalized per cell and log-transformed |

Why these three:

- Other matrices people store, such as `normalized_counts` or `logcounts`, can
  be recomputed from these three. Storing them adds nothing, and they silently
  go out of date when the file is edited.
- `desouped_counts` is required whenever ambient RNA was removed, because that
  step has settings and is often random, so it cannot be repeated exactly.
  Without the layer, nobody can check how `X` was made.
- The total each cell is normalized to is not fixed. The checks compare each
  cell's profile, where the total cancels out, so any target works.

What is checked, in this order. The first problem found is the one reported.

1. **`X` is identical to `raw.X`.** Normalization never ran.
2. **`X` has missing (NaN) or infinite values.** Reported first, because those
   values make the later checks unreliable.
3. **`X` has values above about 20.** That is too high for log-transformed data
   (e^20 is about 480 million counts in one cell), so `X` holds raw counts, or
   was normalized but never log-transformed.
4. **`X` has no positive values.** The matrix was emptied.
5. **`layers['desouped_counts']` has missing, infinite or negative values, or no
   counts.** The layer cannot serve as the reference. This runs early because a
   broken layer would make the later checks skip every cell and report the file
   as clean.
6. **`layers['desouped_counts']` is larger than `raw.X` somewhere.** The layer
   is not a corrected version of `raw.X`.
7. **No sampled cell could be compared.** The checks below could not run, and
   passing in that case would look the same as passing a clean file.
8. **`X` does not match its source.** When the source is `raw.X`, the counts
   recovered from `X` show why. A pipeline can remove counts but never invent
   them:

   | Recovered counts | Meaning |
   |---|---|
   | Not whole numbers | `X` is not a normalization of any count matrix |
   | Whole, only above `raw.X` | `X` came from a different matrix |
   | Whole, only below `raw.X` | Ambient RNA was removed, and `layers['desouped_counts']` is missing |
   | Whole, both above and below | Both: ambient RNA was removed, and `raw.X` cannot be the source |

9. **`X` was log-transformed but never normalized per cell.** Each cell's
   recovered total is just its own read depth.

Notes:

- A file with raw counts in `X` and no `raw.X` is not rejected for the missing
  matrix. The CELLxGENE rules give a warning that normalized data is strongly
  recommended, and none of the checks in this section run.
- Checks 1 to 4 scan the whole matrices. Checks 5 to 9 use the first 200 cells,
  because each cell is checked on its own.
- These checks run for every assay. ATAC-seq and methylation assays are not
  exempt yet, and HCA does not accept them today.
- `desouped_counts` is not yet checked as counts in its own right (data type,
  whole numbers).

### Cell metadata labels

CELLxGENE fills in readable labels, such as `tissue` = "lung", from the ontology
term IDs when a file is uploaded. HCA files often carry labels of their own, and
a label that disagrees with its term ID misleads anyone reading the file.

- A populated label column (`sex`, `tissue`, `cell_type` and so on) without its
  term ID column (such as `tissue_ontology_term_id`) is a warning.
- A label that does not match the official name of the term on the same row is
  an error.

### Donor metadata

Each row in `obs` is otherwise checked on its own, so one donor recorded with
two different sexes would pass. That usually means two people were mixed up, or
a data entry error.

Cells are grouped by `donor_id` alone, because one donor can appear in several
datasets of an integrated atlas.

| Column | Two or more different values | One value plus an unknown |
|---|---|---|
| Organism, sex, manner of death | Error | Warning: the unknown can be filled in |
| Development stage, disease | Warning, because these can legitimately differ, for example over time or between a tumor and nearby tissue | Warning: the unknown can be filled in |

- `unknown`, `na` and empty values count as unknown. `not applicable` counts as
  a real value. Missing values are ignored.
- Donors named `pooled`, `unknown`, `na` or empty are skipped, because none of
  those names one person.
- Each message names at most 10 donors, with up to 5 values each.
- Nothing is checked when `obs` has no `donor_id` column.

### Declared gene annotation

`obs['gene_annotation_version']` records the gene annotation a dataset was built
with, and nothing used to check it. In one HCA atlas, six of seven source
datasets declared a release their own genes rule out.

Every finding here is a warning. The producer has to correct the value, and some
values, such as assembly accession numbers (`GCF_000001405.40`), are allowed by
the schema.

Two comparisons:

1. **Declared assembly against `obs['reference_genome']`.** Each distinct pair
   of values is compared, because an integrated atlas can legitimately hold cells
   aligned to different assemblies. The message names the cells that disagree.
   Values that name no assembly are skipped.
2. **Declared release against the genes.** For each Ensembl release, the
   validator counts the file's genes that release does not have. The releases
   that have every gene are the file's compatible releases.
   - Both ends matter. Genes are removed as well as added, so a declared release
     can be too late as well as too early. For example, `ENSG00000130723` exists
     from release 76 to release 102 and then stops.
   - Compatible releases are reported as runs, such as "r100 to r104 and r109 to
     r116", because a gene that is removed and later restored leaves a gap.
   - The genes that rule out the declared release are split into those added
     after it and those removed before it, since the two say opposite things
     about the declaration.
   - When a run reaches release 76 or 116, that end is where the gene table
     stops, not something the genes show.

| Declared value | What happens |
|---|---|
| Ensembl release 76 or later (`v98`) | Matched against the file's genes |
| A number below 76 (`v32`) | Ambiguous: Ensembl release 32 or GENCODE 32. No assembly is assumed. |
| A number GENCODE has not reached, below 76 | Only Ensembl issued it (currently 51 to 75). Releases 55 to 75 are GRCh37, and 51 to 54 are the older NCBI36. |
| Newer than the gene table | Not checked. The message says so, and is the cue to regenerate the table. |
| An assembly accession (`GCF_000001405.40`) | Names a genome, not a gene annotation, and is reported as such |
| Unreadable | No message. The schema's format rule reports it. |

- Only human Ensembl gene IDs (`ENSG` followed by digits) are matched. Gorilla
  IDs start with `ENSGGOG` and would pass a looser test. Spike-ins, other
  species and custom genes are left out, and their count is mentioned next to
  any finding.
- The declared organism only controls the assembly comparison, because Ensembl
  numbers its releases across all species: release 110 means GRCh38 only for a
  human file. Release matching still runs, because an `ENSG` ID is a human gene
  whatever the organism column says.
- **Limitation.** This matches a list of genes, and most files keep only the
  genes that were detected. Removing genes removes evidence, so the compatible
  range can only come out wider than the truth. A declared release outside the
  range is still certainly wrong; what is weaker is pinning down the exact
  release.

### Gene IDs outside the allowed gene set

The **allowed gene set** is the list of human gene IDs a file is checked
against: **GENCODE v48 (Ensembl release 114), primary assembly only**, meaning
every gene on the chromosomes and on the unplaced and unlocalized scaffolds,
**minus the genes on alternate (alt) and patch contigs**. The allowed gene set
is CELLxGENE's own, copied from `cellxgene-schema`.

A gene ID missing from the allowed gene set is a **warning** in this validator
and an **error** at CELLxGENE, so every atlas heading to CELLxGENE has to deal
with them. The base warning says only that an ID is not in the set, which is the
same sentence for every cause. One integrated HCA atlas produced 1,482 of these
warnings, for 741 distinct IDs. HCA groups them by what happened to each gene,
so the pile becomes a handful of decisions.

#### Background

- **Ensembl**: the public genome annotation database run by EMBL-EBI (the
  European Bioinformatics Institute). Ensembl gives every gene a stable ID, such
  as `ENSG00000141510`, and publishes a numbered release a few times a year.
  Between releases, genes can be renamed, merged, split or removed, so an ID
  that was valid when a file was made can later be outdated.
- **GENCODE**: the human gene annotation that Ensembl publishes, under GENCODE's
  own version numbers. GENCODE v48 is Ensembl release 114.
- **Primary assembly**: the main human genome sequence (GRCh38), made up of the
  chromosomes plus short scaffolds whose chromosome or position is not yet
  known. Alternate and patch sequences, which describe variant versions of some
  regions, are not part of the primary assembly.

#### Why alt and patch genes are left out

- At Ensembl release 114, Ensembl lists 86,364 human genes and the allowed gene
  set holds 78,894. Every one of the 7,470 missing genes sits on an alternate or
  patch sequence.
- Aligners count reads against the primary assembly for the same reason. If a
  region and its alternate copy were both included, reads would map to both. A
  gene annotated only on a patch is real in Ensembl, but cannot be a column name.
- A file carrying many patch genes was aligned against a reference genome that
  includes patch sequences. Almost no pipeline does that, and the file's counts
  are hard to compare with other files. A few HCA files carry thousands of these
  genes.

#### Reading the gene ID report

All human gene IDs outside the allowed gene set are reported together in one
block with four parts:

- **Headline**: how many IDs are missing from the allowed gene set
- **`Summary:`**: one line per group, with the count, what happened, and a tag
- **`Actions:`**: what each tag in the report means
- **`Details:`**: one line per ID, with the old ID, the new ID when there is
  one, what happened, and the tag

For example:

```
3 gene IDs are not in GENCODE v48 (Ensembl 114, primary assembly only).
Summary:
  1  replaced; successor not in file                [rename]
  1  replaced; successor already in file or shared  [review]
  1  retired; no successor, or one since retired    [drop]
Actions:
  [rename]  Replace the ID with its successor.
  [review]  Needs a decision rather than a fix: these IDs are now one gene, and their counts may not be independent.
  [drop]    Remove the feature. Its counts are not retained.
Details:
  ENSG00000148362 -> ENSG00000310560  renamed  [rename]
  ENSG00000236938 -> ENSG00000285090  merged; successor already in file  [review]
  ENSG00000224247    retired; no successor  [drop]
```

- Each ID is listed once, even when the ID appears in both `var` and `raw.var`.
- An ID in `Details:` does not also get a `Feature ID '…' not found` warning.
  The Details line carries the same fact, plus what happened to the gene.
- Any remaining `Feature ID '…' not found` warnings are for features the report
  does not cover: anything that is not a human Ensembl gene ID, such as other
  species' genes, spike-ins, transgenes or custom features.
- Ensembl's history is followed to the end: if A became B and B later became C,
  the new ID shown is C. Renaming A to B would leave an ID CELLxGENE still
  rejects.
- What happened and what to do are separate columns, because they do not map
  one to one: the same Ensembl merge is a plain rename when the new gene is not
  in the file, and a decision when it is.

#### Tags

| Tag | When you see it | What to do |
|---|---|---|
| `[rename]` | Ensembl replaced the gene with one new gene, which is in the allowed gene set and not yet in the file | Replace the old ID with the new one. |
| `[review]` | The new gene is already in the file; or several IDs in the file lead to the same new gene; or the file spells one gene more than one way (with and without a version suffix, or with two different suffixes) | Decide whether to combine the columns. Their counts may not be independent, so adding them can double-count. Whoever produced the data should decide. |
| `[drop]` | The gene was removed with no replacement; or the replacement was itself removed later; or the replacement is not in the allowed gene set; or the gene is on a patch or alternate sequence | Remove the gene. There is no replacement in the allowed gene set to move its counts to. |
| `[drop or re-align]` | Ensembl split the gene into several genes | Remove the gene, or re-run alignment against a newer annotation to get counts for the new genes. |
| `[strip suffix]` | The ID has a version suffix, such as `.17` | Remove the suffix, then check the ID's Details line: removing the suffix alone may not make the ID valid. |
| `[none]` | The gene is newer than the allowed gene set | Nothing. The file is correct. |
| `[ask]` | The gene history shipped with this package (Ensembl releases 76 to 116) has no record of the ID, for example because the gene was removed before release 76 | Ask the data producer which gene annotation the file was built with. |

**Why `[review]` is not a mechanical fix.** Renaming would leave two columns
with one name. Where a study was aligned against an annotation that treated the
two IDs as separate genes, its cells hold real counts in each, and adding them
double-counts. Which pairs are safe to add depends on how every source in an
atlas was built, so the decision belongs to whoever produced the data.

#### Location notes

When Ensembl replaced a gene with one gene in the allowed gene set (the
`[rename]` rows and most `[review]` rows), the validator compares where the old
and new genes sit on the genome. Other rows get no comparison and no note.

- **No note**: the new gene covers the old one, which is the usual case.
- **`old contains new`**: the new gene lies inside the old one.
- **`overlap`**: the two genes share some positions, but neither covers the
  other.
- **`disjoint`**: the two genes share no positions, or sit on different
  chromosomes or strands.

A note does not mean the replacement is wrong. Ensembl trims gene boundaries as
often as it extends them, and some overlaps differ by a few bases. A note only
means the line deserves a closer look before renaming.

#### Data versions

The gene ID checks use three data sources. Each is updated on its own schedule,
so their versions can differ.

| Data | Version | Used for |
|---|---|---|
| Allowed gene set | GENCODE v48 (Ensembl release 114) | Whether an ID is valid |
| Gene history ([gene ID event table](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/DEVELOPMENT.md#gene-id-event-table)) | Ensembl releases 76 to 116 | What happened to a retired ID |
| Gene presence by release ([gene release interval table](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/DEVELOPMENT.md#gene-release-interval-table)) | Ensembl releases 76 to 116 | Matching the declared gene annotation, and telling genes on patch or alternate sequences apart from genes newer than the allowed gene set |

A gene Ensembl added after the allowed gene set was made appears in the gene
presence table but not in the allowed gene set, and gets the `[none]` tag.

<!-- Maintainers: these versions are typed by hand, here and elsewhere in this
README (search for "v48", "114" and "116", including the example output). Update
them when cellxgene-schema is upgraded or either table is regenerated. -->

## Developing

Running the tests, the package layout, the ontology overlay and regenerating the
gene tables are covered in
[DEVELOPMENT.md](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/DEVELOPMENT.md).

## Acknowledgements

- **The CELLxGENE team at the Chan Zuckerberg Initiative (CZI).** This package
  is built on their schema validator, `cellxgene-schema`, from
  [chanzuckerberg/single-cell-curation](https://github.com/chanzuckerberg/single-cell-curation).
  A copy of `cellxgene-schema` is included here under the MIT License and
  extended for HCA. Every CELLxGENE check in this validator, and the allowed gene
  set, comes from the CELLxGENE team's work. See [`NOTICE`](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/NOTICE).
- **`cellxgene-ontology-guide`**, also by the CZI CELLxGENE team, which supplies
  the ontology data the validator checks terms against, and the build pipeline
  the [ontology overlay](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/DEVELOPMENT.md#ontology-data-overlay) uses.
- **[GENCODE](https://www.gencodegenes.org/)**, the human gene annotation behind
  the allowed gene set.
- **[Ensembl](https://www.ensembl.org/)** at EMBL-EBI, whose public database the
  two gene tables in this package are built from.

## License

MIT
