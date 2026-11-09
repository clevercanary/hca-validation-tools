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

The validator is also told whether the file is a source dataset or an
integrated object (`object_kind`). A source dataset holds data from a single
study, while an integrated object holds data from several source datasets
integrated into an atlas. The two kinds have different validation requirements.

The validator reports two kinds of finding:

- **Errors**: the file does not meet the schema.
- **Warnings**: something to review or fix. A missing **strongly recommended**
  field is a warning, not an error.

## Installation

Requires Python 3.10 or later.

```bash
pip install hca-schema-validator
```

## Usage

The validator runs from Python.

```python
from hca_schema_validator import HCAValidator

# object_kind is required: "source" or "integrated". Leaving it out raises a
# TypeError.
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

To validate an integrated object, pass `object_kind="integrated"` instead:

```python
validator = HCAValidator(object_kind="integrated")
is_valid = validator.validate_adata("path/to/atlas.h5ad")
```

## Parts of an h5ad file

- **`obs`**: the table of cells and their metadata
- **`var`** and **`raw.var`**: the tables of genes
- **`uns`**: metadata for the whole dataset
- **`X`**: the normalized expression matrix
- **`raw.X`**: the raw count matrix
- **`layers`**: extra matrices stored alongside `X`, such as
  `layers['desouped_counts']`, the counts left after ambient RNA removal
- **`obsm`**: cell embeddings, such as UMAP coordinates

## Core CELLxGENE checks

CELLxGENE is CZI's single-cell data portal, and the CELLxGENE schema defines
what the portal accepts. The CELLxGENE validator runs every check in this
section. CELLxGENE's reasoning for these rules is in the
[CELLxGENE schema 7.0.0](https://github.com/chanzuckerberg/single-cell-curation/blob/main/schema/7.0.0/schema.md),
the schema version that `cellxgene-schema` 7.0.1 checks. HCA changes some of
these rules. [HCA overrides](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#hca-overrides) lists the changes and the
reason for each.

### File structure validations

- Column names in `obs`, `var` and `raw.var` are unique.
- No column name starts with `__`, which is reserved.
- Deprecated columns are absent.
- No array stored in `obsm`, `obsp`, `varm` or `varp` is empty.

### Cell metadata validations (`obs`)

- `obs` exists, and every cell ID is unique.
- Every required column is present (the
  [HCA schema](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/src/hca_schema_validator/schema_definitions/hca_schema_definition.yaml)
  lists them).
- Category columns are stored as categories, and true/false columns as
  booleans. A category column holds one kind of value and no empty text
  (`""`), except `manner_of_death`, which may be empty text. Unused categories
  are a warning.
- Values are only missing where the schema allows.
- Columns marked unique hold no repeated values.
- Columns with a fixed list of allowed values hold only those values.
- A cell with several values in one column lists them sorted, with no repeats.

### Ontology term validations (`obs`)

Each term must come from the right ontology, must not be deprecated, and in
some columns must sit below a given parent term. Every validation failure here
is an error.

- **Cell type**: the Cell Ontology (CL). Cell lines have their own rules.
- **Tissue**: depends on `obs['tissue_type']`:
  - `tissue` or `organoid`: UBERON (the Uber-anatomy Ontology)
  - `primary cell culture`: a cell type term, following the cell type rules
  - `cell line`: a Cellosaurus (CVCL) term
- **Assay**: EFO (the Experimental Factor Ontology).
- **Disease**: MONDO (the Mondo Disease Ontology), or `PATO:0000461` (normal)
  for healthy samples.
- **Development stage**: HsapDv (Human Developmental Stages).
- **Sex**: PATO (the Phenotype And Trait Ontology).
- **Organism**: an allowed term from the NCBI Taxonomy, the organism list of
  the US National Center for Biotechnology Information.

### Gene validations (`var`, `raw.var`)

- `var` exists, and every gene ID is unique.
- Each column holds one type of value: text such as `"5"` and numbers such as
  `5` cannot share a column.
- Fewer than 20,000 genes is a warning, because the file may have been filtered
  to fewer genes.
- Every gene ID belongs to a supported organism (human, mouse, SARS-CoV-2, ERCC
  spike-ins, and several model organisms and primates) and appears in that
  organism's gene list. CELLxGENE reports an ID missing from the list as an
  error.
- `var['feature_is_filtered']` is true/false, and is all false when the file has
  no raw matrix. `raw.var` must not have this column.

### Dataset metadata validations (`uns`)

- `uns` exists.
- `title` is not empty and has no leading, trailing or double spaces.
- `batch_condition` lists `obs` column names.
- `default_embedding` names an embedding in `obsm`.
- `X_approximate_distribution` is `count` or `normal`.
- No value is empty, and the text fields the schema defines have no leading,
  trailing or double spaces.
- Color lists (`<column>_colors`) belong to an existing category column, have
  at least one color per category, and are all hex codes or all CSS color names.

### Matrix validations (`X`, `raw.X`, `layers`)

- Every matrix, including each layer, is dense or CSR (compressed sparse row).
  CSR is required when more than half the values are zero.
- The raw matrix (`raw.X`, or `X` when there is no `raw.X`) holds raw counts.
  These checks are skipped for ATAC-seq and methylation assays
  ([Raw count checks](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#hca-overrides)):
  - The raw matrix is stored as 32-bit floats.
  - Non-zero values are whole positive numbers.
  - Every cell has at least one raw count.
- RNA-seq files have a raw matrix. If `X` holds raw counts and there is no
  `raw.X`, the file gets a warning that normalized data is strongly
  recommended.
- A gene marked filtered (`feature_is_filtered`) should be all zeros in `X`,
  and a gene that is all zeros in `X` should be marked filtered or be all zeros
  in `raw.X` too. Both are warnings.
- `X` and `raw.X` hold the same cells and genes, in the same order.
- No two cells have identical raw counts.

### Embedding validations (`obsm`)

- Every file has at least one embedding named `X_…`.
- Embedding names start with a letter and use only letters, digits, `_`, `.`
  and `-`. For a name starting with `X_`, the rule applies to the part after
  `X_`: `X_umap` is accepted, `X_1` and `X__umap` are not.
- An embedding not named `X_…` gets a warning, because the
  CELLxGENE Explorer will not show it.
- Every embedding is a numeric array with one row per cell, at least two
  dimensions and no infinite values, and is not entirely missing. `X_…`
  embeddings have at least two columns. For an embedding not named `X_…`, a
  non-numeric type, infinite values or an entirely missing embedding is a
  warning, not an error.

## HCA overrides

- **Schema.** HCA uses its own schema
  ([`hca_schema_definition.yaml`](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/src/hca_schema_validator/schema_definitions/hca_schema_definition.yaml))
  in place of the CELLxGENE schema:
  - Organism is recorded per cell, in `obs['organism_ontology_term_id']`.
    CELLxGENE expects organism once, in `uns`, and rejects the `obs` column as
    deprecated.
  - `uns['study_pi']` is required: a list naming the study's principal
    investigators, each a non-empty string.
  - Each field has a level:
    - **required**: an error when missing
    - **optional**: checked only when present
    - **strongly recommended**: a warning when the column is absent or has
      missing values, for fields a data producer may genuinely not have
    - **forbidden**: an error when present. Self-reported ethnicity is
      forbidden, because HCA does not collect it, to protect donor privacy.
  - **One value per cell.** Some fields hold one value per cell, not several
    packed together with `,`, `;` or `|`.
  - **No placeholders.** Some fields reject placeholders such as `unknown`, `na`
    or `tbd`. Leave the value missing instead, because a placeholder looks like
    real data.
  - Some fields must match a set format, and list fields must hold non-empty
    text.
- **Reserved and label columns.** CELLxGENE rejects files that already carry
  names the portal fills in itself: reserved names such as `citation` in `uns`
  and `observation_joinid` in `obs`, and label columns such as `cell_type` and
  `tissue`. With `HCAValidator`'s default `ignore_labels=True`, HCA does not
  reject these names. Passing `ignore_labels=False` rejects them as CELLxGENE
  does. Either way, HCA checks each label against its ontology term
  ([Cell metadata labels](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#cell-metadata-labels)).
- **Gene ID warnings.** CELLxGENE reports a gene ID missing from its gene list,
  or from a different organism than the file's, as an error. HCA reports both
  as warnings, so that outdated gene IDs, which are common in HCA files, do not
  stop validation from reporting the file's other problems. Each `Feature ID '…' not found` warning names the gene set
  version, for example "not found in GENCODE v48 (Ensembl 114)", and these
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

### Expression matrices

HCA expects up to three matrices in a file, and the validator checks that they
agree with each other.

| Matrix | Expected | Holds |
|---|---|---|
| `raw.X` | Yes | Raw counts as 32-bit floats, with only empty droplets removed |
| `layers['desouped_counts']` | When ambient RNA was removed | The counts left after ambient RNA removal |
| `X` | Yes | Normalized per cell, then transformed with `log1p` (the natural log of 1 plus the value), made from `desouped_counts` if the file has that layer, otherwise from `raw.X` |

Why these three:

- Other matrices people store, such as `normalized_counts` or `logcounts`, can
  be recomputed from these three. Storing them adds nothing, and they silently
  go out of date when the file is edited.
- `desouped_counts` is required whenever ambient RNA was removed, because that
  step has settings and is often random, so it cannot be repeated exactly.
  Without the layer, nobody can check how `X` was made. The validator looks for
  this exact name, whichever tool removed the ambient RNA (SoupX, CellBender,
  DecontX or another). A file does not say whether ambient RNA was removed, so
  the validator reports a missing layer only when `X` shows it (check 8).
- The total each cell is normalized to is not fixed. The checks compare each
  cell's profile, where the total cancels out, so any target works.

What is checked:

1. **`X` is identical to `raw.X`.** Normalization never ran.
2. **`X` has missing (NaN) or infinite values.**
3. **`X` has values above about 20.** That is too high for `log1p` data, so
   `X` holds raw counts or was never log-transformed.
4. **`X` has no positive values.** The matrix was emptied.
5. **`layers['desouped_counts']` has missing, infinite or negative values, or no
   counts.** The layer cannot serve as the reference.
6. **`layers['desouped_counts']` is larger than `raw.X` somewhere.** The layer
   is not a corrected version of `raw.X`.
7. **None of the checked cells could be compared.** For example, those cells
   are empty in `X`, so the checks below could not run.
8. **`X` does not match its source.** When the source is `raw.X`, the validator
   recovers each cell's counts from `X` to show why. A pipeline can remove
   counts but never invent them:

   | Counts recovered from `X` | Meaning | What to do |
   |---|---|---|
   | Not whole numbers | `X` is not a normalization of any count matrix | Rebuild `X` by normalizing and log-transforming `raw.X` |
   | Whole numbers, some higher than `raw.X` and none lower | `X` was made from a different matrix | Rebuild `X` from `raw.X`, or replace `raw.X` with the raw counts `X` was made from |
   | Whole numbers, some lower than `raw.X` and none higher | Ambient RNA was removed, and `layers['desouped_counts']` is missing | Add the counts left after ambient RNA removal as `layers['desouped_counts']` |
   | Whole numbers, some higher and some lower | `X` was made from a different count matrix than `raw.X` | Store the counts `X` was made from in `raw.X`. If those were counts after ambient RNA removal, store them as `layers['desouped_counts']` instead, and keep the counts they were removed from in `raw.X` |

9. **`X` was log-transformed but never normalized per cell.**

Each of these is an error. None of these checks run when there is no `raw.X`.

### Cell metadata labels

Label columns hold the readable name of each ontology term, such as `tissue` =
"lung" next to `tissue_ontology_term_id` = "UBERON:0002048". The label columns
are `assay`, `cell_type`, `development_stage`, `disease`, `organism`, `sex` and
`tissue`.

The HCA curation team adds the labels from the term IDs as a final step in
pre-publication curation, so atlas integration teams can leave the label columns
out, or leave their values missing. Empty text (`""`) counts as a label and is
checked like any other. Any label a team does fill in must match the official
ontology name for its term ID:

- A label that matches the name of the term on the same row passes.
- A label that does not match is an error.
- A label on a row with no term ID is an error.
- A label column whose term ID column is absent from the file, such as `tissue`
  without `tissue_ontology_term_id`, is a warning if it holds any labels,
  because its labels cannot be checked.

### Donor metadata

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

### Gene annotation terms

These are the terms Ensembl, GENCODE and the Genome Reference Consortium use.

- **Gene annotation**: the genes and transcripts of a genome, with their
  positions on a genome assembly, usually published as a GTF file. A dataset's
  counts are made against one gene annotation.
- **Ensembl**: the genome database run by EMBL-EBI (the European Bioinformatics
  Institute). Ensembl publishes a gene annotation in numbered **Ensembl
  releases**, a few times a year. Messages about the declared release write
  release 114 as `r114`.
- **Ensembl stable ID**: the identifier Ensembl gives a gene, transcript or
  protein. A human **Ensembl gene ID** has the form `ENSG00000141510`, and can
  carry a version after a dot (`ENSG00000141510.18`). Stable IDs are meant to
  stay the same across releases, but between releases a gene ID can be retired,
  or replaced by one or more new IDs, so an ID that was valid when a file was
  made can later be outdated.
- **GENCODE**: the human gene annotation made by merging Ensembl's and the
  Havana team's annotation. GENCODE is essentially identical to the Ensembl
  annotation of the same release, under its own version numbers. GENCODE v48 is
  Ensembl release 114.
- **Genome assembly**: a set of chromosomes, unlocalized and unplaced sequences,
  and alternate loci that represents a genome. The Genome Reference Consortium
  (GRC) releases the human assemblies, such as GRCh38 (current) and GRCh37.
- **Primary assembly**: the chromosomes plus the unlocalized and unplaced
  sequences, one copy of each region. Ensembl's `primary_assembly` files and
  GENCODE's `PRI` files cover the primary assembly.
- **Alternate loci** (also called alternate haplotypes): sequences that give a
  different version of a region already in the primary assembly. They are not
  part of the primary assembly.
- **Patches**: sequences the GRC releases between full assemblies. **Fix
  patches** correct errors in the assembly. **Novel patches** add sequence that
  was not in the assembly. Patches are not part of the primary assembly.
- **Gene history table** and **gene release table**: this package's names for
  two files it ships, built from Ensembl. The gene history table
  (`gene_id_events.csv.gz`) records what Ensembl says became of each retired
  gene ID. The gene release table (`gene_release_intervals.csv.gz`) records
  which Ensembl releases each gene ID appears in.

### Declared gene annotation

The validator checks the declared `obs['gene_annotation_version']` against the
file's genes and `obs['reference_genome']`. Every finding here is a warning.
Only the data producer (the lab or team that made the file) can correct the
value, and some values the schema allows, such as assembly accession numbers
(`GCF_000001405.40`), cannot be checked against the genes.

Two comparisons:

1. **Declared assembly against `obs['reference_genome']`.** For each
   combination of `gene_annotation_version` and `reference_genome` found in the
   cells, the validator checks that both name the same genome assembly, such as
   GRCh38. An integrated atlas can hold cells aligned to different assemblies,
   so each combination is checked on its own. The comparison runs only when
   every cell's organism is human.
2. **Declared release against the genes.** The validator works out which Ensembl
   releases are compatible with the file's human Ensembl gene IDs, and warns
   when the declared release is not one of them. The gene release table stops at
   release 116, so a newer declared release is not checked. The rules are in
   [docs/gene-id-contract.md](https://github.com/clevercanary/hca-validation-tools/blob/main/docs/gene-id-contract.md).

#### When no version is declared

A file with no `obs['gene_annotation_version']` column, or only missing values
such as `nan` or `unknown`, fails validation, because the schema requires the
field. The genes are still matched against each release, and a warning names the
releases they fit, for example
`This file's gene set is consistent with r105 to r110.`

### Gene IDs outside the allowed gene set

The **allowed gene set** is the list of human gene IDs a file is checked
against: **GENCODE v48 (Ensembl release 114), primary assembly only**, meaning
every gene on the chromosomes and on the unlocalized and unplaced sequences,
**minus the genes on alternate loci and patches**. The allowed gene set is
CELLxGENE's own, copied from `cellxgene-schema`.

A gene ID missing from the allowed gene set is a **warning**. The missing IDs
are grouped by what happened to each gene
([Reading the gene ID report](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#reading-the-gene-id-report)).

#### Why alternate loci and patches are left out

- At Ensembl release 114, Ensembl lists 86,364 human genes and the allowed gene
  set holds 78,894. Every one of the 7,470 missing genes sits on an alternate
  locus or a patch.
- Aligners count reads against the primary assembly for the same reason. If a
  region and its alternate locus were both included, reads would map to both. A
  gene annotated only on a patch is real in Ensembl, but a pipeline that aligns
  to the primary assembly never counts it.
- A file carrying many patch genes was aligned against a reference genome that
  includes patches. Almost no pipeline does that, and the file's counts are hard
  to compare with other files.

#### Reading the gene ID report

All human gene IDs outside the allowed gene set are reported together, as four
warnings in a row:

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
- Ensembl's history is followed to the end: if A became B and B later became C,
  the new ID shown is C.

#### Tags

| Tag | When you see it | What to do |
|---|---|---|
| `[rename]` | Ensembl replaced the gene with one new gene, which is in the allowed gene set and not yet in the file | Replace the old ID with the new one. |
| `[review]` | The new gene is already in the file; or several IDs in the file lead to the same new gene; or the file spells one gene more than one way. When a file lists the same gene with and without a version suffix, the suffixed ID is `[review]`. The bare ID keeps the tag it would have on its own, unless Ensembl retired the gene with one replacement: then both IDs lead to that gene, and both are `[review]`. Two different suffixes of one gene are both `[review]`. A gene Ensembl retired with no single replacement in the allowed gene set keeps its own tag on every spelling | Decide whether to combine the columns. Adding their counts double-counts if the file was aligned against an annotation that treated the IDs as separate genes. |
| `[drop]` | The gene was removed with no replacement; or the replacement was itself removed later; or no replacement is in the allowed gene set; or the gene is on an alternate locus or a patch | Remove the gene. There is no replacement in the allowed gene set to move its counts to. |
| `[drop or re-align]` | Ensembl split the gene into several genes, and at least one of them is in the allowed gene set | Remove the gene, or re-run alignment against a newer annotation to get counts for the new genes. |
| `[strip suffix]` | The ID has a version suffix, such as `.17`, and without the suffix it is in the allowed gene set or newer than it. Any other suffixed ID gets the tag it would get without the suffix, and its Details line says "version suffix" | Remove the suffix. |
| `[none]` | The gene is newer than the allowed gene set | Nothing to fix. |
| `[ask]` | Neither gene table (Ensembl releases 76 to 116) has a record of the ID, for example because the gene was removed before release 76 | Ask the data producer which gene annotation the file was built with. |

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

A note marks a line to check before renaming. It does not mean the replacement
is wrong.

#### Data versions

The gene ID checks use three data sources. Each is updated on its own schedule,
so their versions can differ.

| Data | Version | Used for |
|---|---|---|
| Allowed gene set | GENCODE v48 (Ensembl release 114) | Whether an ID is valid |
| Gene history table ([how it is built](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/DEVELOPMENT.md#gene-id-event-table)) | Ensembl releases 76 to 116 | What happened to a retired ID |
| Gene release table ([how it is built](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/DEVELOPMENT.md#gene-release-interval-table)) | Ensembl releases 76 to 116 | Matching the declared gene annotation, and telling genes on alternate loci or patches apart from genes newer than the allowed gene set |

<!-- Maintainers: these versions are typed by hand, here and elsewhere in this
README (search for "v48", "114", "116" and "7.0.1", including the example
output). Update
them when cellxgene-schema is upgraded or either table is regenerated. -->

## Developing

Instructions for working on this package are in
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
