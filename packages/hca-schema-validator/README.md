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

Install uv by following the
[official installation guide](https://docs.astral.sh/uv/getting-started/installation/).
On macOS, `brew install uv` also works.

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

# object_kind is required: "source" for a source dataset (one study), or
# "integrated" for an integrated object (cells combined from several datasets).
validator = HCAValidator(object_kind="source")

# Validate an h5ad file. The result is False when there are errors.
is_valid = validator.validate_adata("path/to/file.h5ad")

print("✅ No errors" if is_valid else "❌ Errors:")
for error in validator.errors:
    print(f"  - {error}")

# A file with no errors can still have warnings to review or fix,
# including the gene ID report.
for warning in validator.warnings:
    print(f"  ! {warning}")
```

## What this validator checks

The HCA overrides and HCA extensions are listed with the reason for each. The
core CELLxGENE checks are CELLxGENE's own rules, listed as CELLxGENE states
them. The detailed rules behind the gene ID checks are in
[docs/gene-id-contract.md](https://github.com/clevercanary/hca-validation-tools/blob/main/docs/gene-id-contract.md).

### Parts of an h5ad file

- **`obs`**: the table of cells and their metadata
- **`var`** and **`raw.var`**: the tables of genes
- **`uns`**: metadata for the whole file
- **`X`**: the normalized expression matrix
- **`raw.X`**: the raw count matrix
- **`layers`**: extra matrices stored alongside `X`, such as
  `layers['desouped_counts']`, the counts left after ambient RNA removal.
  Ambient RNA is RNA from broken cells floating in the sample, which gets
  counted in every droplet.
- **`obsm`**: cell embeddings, such as UMAP coordinates

### Genes and gene annotations

- **Gene annotation**: the list of genes, with their IDs and positions on the
  genome, that sequencing reads were counted against when the file was made.
- **Ensembl**: the public genome annotation database run by EMBL-EBI (the
  European Bioinformatics Institute). Ensembl gives every gene a stable ID, such
  as `ENSG00000141510`, and publishes a numbered release a few times a year.
  Between releases, genes can be renamed, merged, split or removed, so an ID
  that was valid when a file was made can later be outdated. Validator messages
  write release 114 as `r114`.
- **GENCODE**: the human gene annotation that Ensembl publishes, under GENCODE's
  own version numbers. GENCODE v48 is Ensembl release 114.
- **Genome assembly**: one version of the reference genome sequence, such as
  GRCh38 (the current human assembly) or the older GRCh37. Gene positions are
  given on an assembly.
- **Primary assembly**: the main human genome sequence (GRCh38), made up of the
  chromosomes plus short scaffolds whose chromosome or position is not yet
  known. **Alternate and patch sequences**, which describe variant versions of
  some regions, are not part of the primary assembly.
- **Gene tables**: two tables built from Ensembl that ship with this package.
  The **gene history table** records what happened to each gene ID across
  releases. The **gene release table** records which releases each gene ID
  appears in. Both cover Ensembl releases 76 to 116.

### Source datasets and integrated objects

`HCAValidator` must be told what kind of file it is checking, with
`object_kind`:

- **`"source"`**: a source dataset, one study built with one gene annotation.
- **`"integrated"`**: an integrated object, which combines cells from several
  source datasets.

For files registered in the HCA Atlas Tracker (the HCA's record of each atlas
and its files), use the kind the tracker lists the file under.

The validator never guesses the kind from the file path. Leaving `object_kind`
out, or passing any other value, raises an error that names the two choices.

The kind changes only the last sentence of some warnings about the declared
gene annotation ([Declared gene annotation](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#declared-gene-annotation)).
It never changes which problems are reported.

## Core CELLxGENE checks

CELLxGENE is CZI's single-cell data portal, and the CELLxGENE schema defines
what the portal accepts. The CELLxGENE validator runs every check in this
section. CELLxGENE's reasoning for these rules is in the
[CELLxGENE schema 7.0.0](https://github.com/chanzuckerberg/single-cell-curation/blob/main/schema/7.0.0/schema.md),
the schema version that `cellxgene-schema` 7.0.1 checks. Where HCA changes a
group, a note under its heading says what changes;
[HCA overrides](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#hca-overrides) gives the reasons.

### File structure

*[HCA override](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#hca-overrides): `obs['organism_ontology_term_id']` is
required rather than rejected as deprecated, and reserved and label columns
are allowed.*

- Column names in `obs`, `var` and `raw.var` are unique.
- No column name starts with `__`, which is reserved.
- Deprecated columns are absent.
- No array stored in `obsm`, `obsp`, `varm` or `varp` is empty.

### Cell metadata (`obs`)

*[HCA override](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#hca-overrides): HCA's own schema decides which columns
are required, and columns outside the schema skip the type and value checks.*

- `obs` exists, and every cell ID is unique.
- Every required column is present (the
  [HCA schema](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/src/hca_schema_validator/schema_definitions/hca_schema_definition.yaml)
  lists them).
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
- **Development stage**: HsapDv (Human Developmental Stages) for human, MmusDv
  (Mouse Developmental Stages) for mouse.
- **Sex**: PATO (the Phenotype And Trait Ontology).
- **Organism**: an allowed term from the NCBI Taxonomy, the organism list of
  the US National Center for Biotechnology Information.

### Genes (`var`, `raw.var`)

*[HCA override](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#hca-overrides): gene ID warnings name the gene set
version, and human Ensembl gene IDs are listed in one gene ID report instead.*

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

*[HCA override](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#hca-overrides): `uns['study_pi']` is required.*

- `uns` exists.
- `title` is not empty and has no leading, trailing or double spaces.
- `batch_condition` lists `obs` column names.
- `default_embedding` names an embedding in `obsm`.
- `X_approximate_distribution` is `count` or `normal`.
- No value is empty, and the text fields the schema defines have no leading,
  trailing or double spaces.
- Color lists (`<column>_colors`) belong to an existing category column, have
  at least one color per category, and are all hex codes or all CSS color names.

### Matrices (`X`, `raw.X`, `layers`)

*[HCA override](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#hca-overrides): the raw count checks run even when
the file has other errors.*

- Non-zero values in the raw matrix (`raw.X`, or `X` when there is no
  `raw.X`) are 32-bit floats.
- Every matrix, including each layer, is dense or CSR (compressed sparse row).
  CSR is required when more than half the values are zero.
- Non-zero raw counts are whole positive numbers.
- Every cell has at least one raw count. Visium spots outside the tissue follow
  a separate rule.
- RNA-seq files have a raw matrix. If `X` holds raw counts and there is no
  `raw.X`, the file gets a warning that normalized data is strongly
  recommended.
- A gene marked filtered (`feature_is_filtered`) is all zeros in `X`. A gene
  that is all zeros in `X` is either marked filtered or all zeros in `raw.X` too.
- `X` and `raw.X` hold the same cells and genes, in the same order.

### Embeddings (`obsm`)

- Every file has at least one embedding, and files from non-spatial assays have
  at least one named `X_…`.
- Embedding names start with a letter and use only letters, digits, `_`, `.`
  and `-`. For a name starting with `X_`, the rule applies to the part after
  `X_`: `X_umap` is accepted, `X_1` and `X__umap` are not.
- `X_spatial` cannot be used. Spatial coordinates go in `spatial`.
- An embedding not named `X_…` or `spatial` gets a warning, because the
  CELLxGENE Explorer will not show it.
- Every embedding is a numeric array with one row per cell, at least two
  dimensions and no infinite values. `X_…` and `spatial` embeddings have at
  least two columns. `spatial` has no missing values, and other embeddings are
  not entirely missing.
- A `spatial` embedding is required when `uns['spatial']['is_single']` is true,
  and not allowed when `is_single` is not set.

### Spatial data

- Spatial metadata is allowed only for Visium (a specific Visium assay term, not
  the general one) and Slide-seqV2, with one assay per file.
- `uns['spatial']` holds an `is_single` true/false flag, plus at most one
  library entry, which holds the section's images and scale factors.
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

- **Schema.** HCA uses its own schema
  ([`hca_schema_definition.yaml`](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/src/hca_schema_validator/schema_definitions/hca_schema_definition.yaml))
  in place of the CELLxGENE schema:
  - Organism is recorded per cell, in `obs['organism_ontology_term_id']`.
    CELLxGENE expects organism once, in `uns`, and rejects the `obs` column as
    deprecated.
  - `uns['study_pi']` is required: a list naming the study's principal
    investigators, each a non-empty string.
  - Each field has a level:
    - **required** (the default): an error when missing
    - **optional**: checked only when present
    - **strongly recommended**: a warning when the column is absent or has
      missing values. A value that packs several values into one, separated by
      `,`, `;` or `|`, is an error. For some fields, a placeholder value such as
      `unknown`, `na` or `tbd` is also an error: leave the value missing
      instead.
    - **forbidden**: an error when present. Self-reported ethnicity is
      forbidden, because HCA does not collect it, to protect donor privacy.
  - Some fields must match a set format, and list fields must hold non-empty
    text.
- **Reserved and label columns.** CELLxGENE rejects files that already carry
  columns the portal fills in itself: reserved columns such as `citation` and
  `observation_joinid`, and label columns such as `cell_type` and `tissue`. HCA
  does not reject these columns, and checks each label against its ontology
  term instead
  ([Cell metadata labels](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#cell-metadata-labels)).
- **Gene ID warnings.** Each `Feature ID '…' not found` warning names the gene
  set version, for example "not found in GENCODE v48 (Ensembl 114)", and these
  warnings are listed after all other warnings. Human Ensembl gene IDs do not
  get this warning. They are listed in one gene ID report instead
  ([Gene IDs outside the allowed gene set](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#gene-ids-outside-the-allowed-gene-set)).
- **Raw count checks.** CELLxGENE skips the raw count checks when a file already
  has errors. HCA runs them anyway, as long as `obs` has
  `assay_ontology_term_id` and the assay needs raw counts (ATAC-seq and
  methylation assays are exempt), so one pass shows more problems.
- **Missing or malformed assay and organism values.** A missing or malformed
  value in `assay_ontology_term_id` or `organism_ontology_term_id` is reported
  by the `obs` column checks, and the rest of validation still runs. The organism
  used in gene ID warnings is the first valid NCBI Taxonomy term in the column.
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
  Without the layer, nobody can check how `X` was made. The validator looks for
  this exact name, whichever tool removed the ambient RNA (SoupX, CellBender,
  DecontX or another).
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
7. **None of the first 200 cells could be compared.** For example, those
   cells are empty in `X`. The checks below could not run, and passing in that
   case would look the same as passing a clean file. Confirm `X` was not partly
   emptied or overwritten.
8. **`X` does not match its source.** When the source is `raw.X`, the validator
   recovers each cell's counts from `X` to show why. A pipeline can remove
   counts but never invent them:

   | Counts recovered from `X` | Meaning | What to do |
   |---|---|---|
   | Not whole numbers | `X` is not a normalization of any count matrix | Rebuild `X` by normalizing and log-transforming `raw.X` |
   | Whole numbers, some higher than `raw.X` and none lower | `X` was made from a different matrix | Rebuild `X` from `raw.X`, or replace `raw.X` with the raw counts `X` was made from |
   | Whole numbers, some lower than `raw.X` and none higher | Ambient RNA was removed, and `layers['desouped_counts']` is missing | Add the counts left after ambient RNA removal as `layers['desouped_counts']` |
   | Whole numbers, some higher and some lower | `X` was made from a different matrix, after ambient RNA was removed from something other than `raw.X` | Find the raw counts the ambient RNA removal started from: store them as `raw.X` and its output as `layers['desouped_counts']` |

9. **`X` was log-transformed but never normalized per cell.** Each cell's
   recovered total is just its own read depth.

Notes:

- None of the checks in this section run when there is no `raw.X`.
- Checks 1 to 4 scan the whole matrices. Checks 5 to 9 use the first 200 cells,
  because each cell is checked on its own.
- Unlike the raw count checks, these checks run for every assay, including
  ATAC-seq and methylation. HCA does not accept those assays yet.
- `desouped_counts` is not yet checked as counts in its own right (data type,
  whole numbers).

#### How counts are recovered from `X`

When `X` does not match `raw.X` (check 8), the validator recovers each cell's
counts to say why. That needs each cell's scale factor, which the validator
reads from `X` alone:

- `X` holds `log1p(scale × count)`, so the validator first undoes the log
  transform with `expm1`. After that, a cell's smallest non-zero value is its
  scale times a count of 1, and nearly every cell has a gene with a count of 1.
- Cells with fewer than 30 genes are left out of this explanation, because
  ambient RNA removal can take all of their count-1 genes. The comparison
  itself, and check 9, still cover those cells.
- On about half a million cells with known answers, this estimate was exact
  every time, and it raised no false finding on 2.2 million correctly
  normalized cells.

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

Cells with the same `donor_id` are treated as one person, even when they come
from different source datasets in an integrated object. A `donor_id` must name
the same person everywhere in the file.

| Column | Two or more different values | One value plus an unknown |
|---|---|---|
| Organism, sex, manner of death | Error | Warning: the unknown can be filled in |
| Development stage, disease | Warning, because these can legitimately differ, for example over time or between a tumor and nearby tissue | Warning: the unknown can be filled in |

- `unknown`, `na` and empty strings count as unknown. `not applicable` counts
  as a real value. Missing values (NaN) are ignored.
- Donors named `pooled`, `unknown`, `na` or empty are skipped, because none of
  those names one person.
- Each message names at most 10 donors, with up to 5 values each.
- Nothing is checked when `obs` has no `donor_id` column.

### Declared gene annotation

`obs['gene_annotation_version']` records the gene annotation a dataset was built
with. Write `v` followed by the Ensembl release number, such as `v114`. The
schema also accepts a GENCODE number, but every GENCODE number so far is below
76 and reads the same as an old Ensembl release, so the genes cannot be checked
against it. If you only know the GENCODE version, look up its Ensembl release:
GENCODE v48 is Ensembl 114, for example.

The validator checks that the declared version fits the genes in the file. This
matters in practice: in one HCA atlas, six of seven source datasets declared a
release their own genes rule out.

Every finding here is a warning. Only the data producer (the lab or team that
made the file) can correct the value, and some values the schema allows, such
as assembly accession numbers (`GCF_000001405.40`), cannot be checked against
the genes.

Two comparisons:

1. **Declared assembly against `obs['reference_genome']`.** For each
   combination of `gene_annotation_version` and `reference_genome` found in the
   cells, the validator checks that both name the same genome assembly, such as
   GRCh38. An integrated atlas can hold cells aligned to different assemblies,
   so each combination is checked on its own. The message names the cells that
   disagree. A combination where either value names no assembly is skipped.
2. **Declared release against the genes.** For each Ensembl release, the
   validator counts the file's genes that release does not have. The releases
   that have every gene are the file's compatible releases. Human IDs the gene
   release table has never seen are left out of this range and named in a
   warning of their own.
   - Both ends matter. Genes are removed as well as added, so a declared release
     can be too late as well as too early. For example, `ENSG00000130723` exists
     from release 76 to release 102 and then stops.
   - Compatible releases are reported as runs, such as "r100 to r104 and r109 to
     r116", because a gene that is removed and later restored leaves a gap.
   - The genes that rule out the declared release are split into those added
     after it and those removed before it, since the two say opposite things
     about the declaration.
   - The gene release table covers releases 76 to 116 only, so a run that ends
     at 76 or 116 may really extend further.
   - A finding that the genes rule out the declared release, or that no single
     release fits them, ends with one sentence that depends on the
     `object_kind` the validator was given:
     - **source dataset** (one study, one annotation): the declared value
       cannot be right, or the reference mixes releases or was built outside
       Ensembl
     - **integrated object** (its genes are the union of its sources' genes):
       each declared value must match the source dataset its cells came from,
       and no single release is expected to fit the whole union

| Declared value | What happens |
|---|---|
| Ensembl release 76 or later (`v98`) | Matched against the file's genes |
| A number below 76 (`v32`) | Ambiguous: Ensembl release 32 or GENCODE 32. No assembly is assumed. |
| A number GENCODE has not reached, below 76 | Only Ensembl issued it (currently 51 to 75). Releases 55 to 75 are GRCh37, and 51 to 54 are the older NCBI36. |
| Newer than release 116 | Not checked, because the gene release table stops at release 116. The message says so. A newer version of this package may cover it. |
| An assembly accession (`GCF_000001405.40`) | Names a genome, not a gene annotation, and is reported as such |
| Unreadable | No message. The schema's format rule reports it. |
| Nothing declared | The genes are still matched ([When no version is declared](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#when-no-version-is-declared)) |

- Only human Ensembl gene IDs (`ENSG` followed by digits, with or without a
  version suffix such as `.18`) are matched. Spike-ins, other species and
  custom genes are left out, and their count is mentioned next to most findings.
- The declared organism only controls the assembly comparison, because Ensembl
  numbers its releases across all species: release 110 means GRCh38 only for a
  human file. Release matching still runs, because an `ENSG` ID is a human gene
  whatever the organism column says.
- **Limitation.** This matches a list of genes, and most files keep only the
  genes that were detected. Removing genes removes evidence, so the compatible
  range can only come out wider than the truth. For a source dataset, a
  declared release outside the range is still certainly wrong; what is weaker
  is pinning down the exact release. For an integrated object, the range covers
  the union of its sources' genes, so a declared release outside it is not
  wrong by itself: check it against the source dataset its cells came from.

#### When no version is declared

A file with no `obs['gene_annotation_version']` column, or only missing values
such as `nan` or `unknown`, still has its genes matched against each release.
Every finding about the gene list itself still appears, plus one warning about
the missing version:

- Where the genes fit a range of releases, the warning names it:
  `obs['gene_annotation_version'] is not declared. This file's gene set is
  consistent with r105 to r110.`
- Where no release fits the genes, the warning says the version cannot be
  inferred.
- Where `obs` says the cells are human but the file has no human Ensembl gene
  IDs, the warning says there are none to infer the version from.

### Gene IDs outside the allowed gene set

The **allowed gene set** is the list of human gene IDs a file is checked
against: **GENCODE v48 (Ensembl release 114), primary assembly only**, meaning
every gene on the chromosomes and on the unplaced and unlocalized scaffolds,
**minus the genes on alternate (alt) and patch sequences**. The allowed gene set
is CELLxGENE's own, copied from `cellxgene-schema`.

A gene ID missing from the allowed gene set is a **warning** in this validator
and an **error** at CELLxGENE, so every atlas heading to CELLxGENE has to deal
with them. The base warning says only that an ID is not in the set, which is the
same sentence for every cause. One integrated HCA atlas produced 1,482 of these
warnings, for 741 distinct IDs. HCA groups them by what happened to each gene,
so the pile becomes a handful of decisions.

#### Why alt and patch genes are left out

- At Ensembl release 114, Ensembl lists 86,364 human genes and the allowed gene
  set holds 78,894. Every one of the 7,470 missing genes sits on an alternate or
  patch sequence.
- Aligners count reads against the primary assembly for the same reason. If a
  region and its alternate copy were both included, reads would map to both. A
  gene annotated only on a patch is real in Ensembl, but a pipeline that aligns
  to the primary assembly never counts it.
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

- **Successor**: the ID Ensembl replaced the old ID with. In `Summary:`,
  *replaced* covers both a rename and a merge; `Details:` says which.
- **Shared**: two or more IDs in the file lead to the same successor.
- **Feature**: a row of `var`, usually a gene.
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
| `[none]` | The gene is newer than the allowed gene set | Nothing to fix for HCA. CELLxGENE will reject the ID until it moves to a newer gene set. |
| `[ask]` | The gene history table (Ensembl releases 76 to 116) has no record of the ID, for example because the gene was removed before release 76 | Ask the data producer which gene annotation the file was built with. |

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
| Gene history table ([how it is built](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/DEVELOPMENT.md#gene-id-event-table)) | Ensembl releases 76 to 116 | What happened to a retired ID |
| Gene release table ([how it is built](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/DEVELOPMENT.md#gene-release-interval-table)) | Ensembl releases 76 to 116 | Matching the declared gene annotation, and telling genes on patch or alternate sequences apart from genes newer than the allowed gene set |

A gene Ensembl added after the allowed gene set was made appears in the gene
release table but not in the allowed gene set, and gets the `[none]` tag.

<!-- Maintainers: these versions are typed by hand, here and elsewhere in this
README (search for "v48", "114", "116" and "7.0.1", including the example
output). Update
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
