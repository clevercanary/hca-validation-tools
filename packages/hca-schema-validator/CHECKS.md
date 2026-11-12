# What hca-schema-validator checks

The full list of checks the HCA schema validator makes on an h5ad file. The
[README](README.md) has a short overview and shows how to run the validator.

The checks fall into three groups:

- **Core CELLxGENE checks.** This package extends the CELLxGENE schema validator
  from the Chan Zuckerberg Initiative (CZI). A copy of the CELLxGENE validator
  (`cellxgene-schema` 7.0.0) ships with the package and runs on every h5ad file.
- **HCA overrides.** HCA replaces some CELLxGENE rules with its own.
- **HCA extensions.** HCA adds checks that CELLxGENE does not have.

Each numbered item describes what a valid h5ad file looks like. An h5ad file that
breaks an item gets an error, unless the item says it is a warning.

An h5ad file stores one AnnData object. The checks refer to the parts of that
object:

- **`obs`**: the table of cells and their metadata
- **`var`** and **`raw.var`**: the tables of genes
- **`uns`**: metadata that applies to all cells
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
the schema version that `cellxgene-schema` 7.0.0 checks. HCA changes some of
these rules. [HCA overrides](#hca-overrides) lists the changes and the
reason for each.

### File structure validations

1. Column names in `obs`, `var` and `raw.var` are unique.
2. No column name starts with `__`, which is reserved.
3. Deprecated columns are absent.
4. No array stored in `obsm`, `obsp`, `varm` or `varp` is empty.

### Cell metadata validations (`obs`)

1. `obs` exists, and every cell ID is unique.
2. Every required column is present (the
   [HCA schema](src/hca_schema_validator/schema_definitions/hca_schema_definition.yaml)
   lists them).
3. Category columns are stored as categories, and true/false columns as
   booleans. A category column holds one kind of value and no empty text
   (`""`), except `manner_of_death`, which may be empty text. Unused categories
   are a warning.
4. Values are only missing where the schema allows.
5. Columns marked unique hold no repeated values.
6. Columns with a fixed list of allowed values hold only those values.
7. A cell with several values in one column lists them sorted, with no repeats.

### Ontology term validations (`obs`)

Each term must come from the right ontology, must not be deprecated, and in
some columns must sit below a given parent term. Every validation failure here
is an error.

1. **Cell type**: the Cell Ontology (CL). Cell lines have their own rules.
2. **Tissue**: depends on `obs['tissue_type']`:
   - `tissue` or `organoid`: UBERON (the Uber-anatomy Ontology)
   - `primary cell culture`: a cell type term, following the cell type rules
   - `cell line`: a Cellosaurus (CVCL) term
3. **Assay**: EFO (the Experimental Factor Ontology).
4. **Disease**: MONDO (the Mondo Disease Ontology), or `PATO:0000461` (normal)
   for healthy samples.
5. **Development stage**: HsapDv (Human Developmental Stages).
6. **Sex**: PATO (the Phenotype And Trait Ontology).
7. **Organism**: an allowed term from the NCBI Taxonomy, the organism list of
   the US National Center for Biotechnology Information.

### Gene validations (`var`, `raw.var`)

1. `var` exists, and every gene ID is unique.
2. Each column holds one type of value: text such as `"5"` and numbers such as
   `5` cannot share a column.
3. Fewer than 20,000 genes in `var` is a warning, because `var` may have been
   filtered to fewer genes.
4. Every gene ID belongs to a supported organism (human, mouse, SARS-CoV-2, ERCC
   spike-ins, and several model organisms and primates) and appears in that
   organism's gene list. CELLxGENE reports an ID missing from the list as an
   error.
5. `var['feature_is_filtered']` is true/false, and is all false when there is
   no raw matrix. `raw.var` must not have this column.

### `uns` validations

1. `uns` exists.
2. `title` is not empty and has no leading, trailing or double spaces.
3. `batch_condition` lists `obs` column names.
4. `default_embedding` names an embedding in `obsm`.
5. `X_approximate_distribution` is `count` or `normal`.
6. No value is empty, and the text fields the schema defines have no leading,
   trailing or double spaces.
7. Color lists (`<column>_colors`) belong to an existing category column, have
   at least one color per category, and are all hex codes or all CSS color names.

### Matrix validations (`X`, `raw.X`, `layers`)

1. Every matrix, including each layer, is dense or CSR (compressed sparse row).
   CSR is required when more than half the values are zero.
2. The raw matrix (`raw.X`, or `X` when there is no `raw.X`) holds raw counts.
   These checks are skipped for ATAC-seq and methylation assays
   ([Raw count checks](#hca-overrides)):
   - The raw matrix is stored as 32-bit floats.
   - Non-zero values are whole positive numbers.
   - Every cell has at least one raw count.
3. RNA-seq data has a raw matrix. If `X` holds raw counts and there is no
   `raw.X`, validation gives a warning that normalized data is strongly
   recommended.
4. A gene marked filtered (`feature_is_filtered`) should be all zeros in `X`,
   and a gene that is all zeros in `X` should be marked filtered or be all zeros
   in `raw.X` too. Both are warnings.
5. `X` and `raw.X` hold the same cells and genes, in the same order.
6. No two cells have identical raw counts.

### Embedding validations (`obsm`)

1. `obsm` has at least one embedding named `X_…`.
2. Embedding names start with a letter and use only letters, digits, `_`, `.`
   and `-`. For a name starting with `X_`, the rule applies to the part after
   `X_`: `X_umap` is accepted, `X_1` and `X__umap` are not.
3. An embedding not named `X_…` gets a warning, because the
   CELLxGENE Explorer will not show it.
4. Every embedding is a numeric array with one row per cell, at least two
   dimensions and no infinite values, and is not entirely missing. `X_…`
   embeddings have at least two columns. For an embedding not named `X_…`, a
   non-numeric type, infinite values or an entirely missing embedding is a
   warning, not an error.

## HCA overrides

HCA changes these CELLxGENE rules:

1. **Schema.** HCA uses its own schema, the
   [HCA Tier 1 metadata schema](https://data.humancellatlas.org/metadata/tier-1)
   ([`hca_schema_definition.yaml`](src/hca_schema_validator/schema_definitions/hca_schema_definition.yaml))
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
2. **Reserved and label columns.** CELLxGENE rejects h5ad files that already
   carry names the portal fills in itself: reserved names such as `citation` in
   `uns` and `observation_joinid` in `obs`, and label columns such as
   `cell_type` and `tissue`. With `HCAValidator`'s default `ignore_labels=True`,
   HCA does not reject these names. Passing `ignore_labels=False` rejects them
   as CELLxGENE does. Either way, HCA checks each label against its ontology
   term ([Cell metadata labels](#cell-metadata-labels)).
3. **Gene ID warnings.** CELLxGENE reports a gene ID missing from its gene list,
   or from a different organism than the one in `obs`, as an error. HCA reports
   both as warnings, so that outdated gene IDs, which are common in HCA data, do
   not stop validation from reporting other problems. Each
   `Feature ID '…' not found` warning names the gene set version, for example
   "not found in GENCODE v48 (Ensembl 114)", and these warnings are listed after
   all other warnings. Human Ensembl gene IDs do not get this warning. They are
   listed in one gene ID report instead
   ([Gene IDs outside the allowed gene set](#gene-ids-outside-the-allowed-gene-set)).
4. **Raw count checks.** CELLxGENE skips the raw count checks when validation has
   already found errors. HCA runs them anyway, as long as `obs` has
   `assay_ontology_term_id` and the assay needs raw counts (ATAC-seq and
   methylation assays are exempt), so one pass shows more problems.
5. **Missing or malformed assay and organism values.** A missing or malformed
   value in `assay_ontology_term_id` or `organism_ontology_term_id` is reported
   by the `obs` column checks, and the rest of validation still runs. The organism
   used in gene ID warnings is the first valid NCBI Taxonomy term in the column.
6. **Extra `obs` columns.** Curators often add columns of their own, such as an
   original cell type. Columns that are not in the schema skip the per-column
   type and value checks, so warnings about columns the schema says nothing about
   do not bury the real findings.

## HCA extensions

### Expression matrices

HCA expects up to three matrices in an h5ad file, and the validator checks that
they agree with each other.

| Matrix | Expected | Holds |
|---|---|---|
| `raw.X` | Yes | Raw counts as 32-bit floats, with only empty droplets removed |
| `layers['desouped_counts']` | When ambient RNA was removed | The counts left after ambient RNA removal |
| `X` | Yes | Normalized per cell, then transformed with `log1p` (the natural log of 1 plus the value), made from `desouped_counts` if `layers` has it, otherwise from `raw.X` |

About these matrices:

- `desouped_counts` is required whenever ambient RNA was removed, because that
  step has settings and is often random, so it cannot be repeated exactly.
  Without the layer, nobody can check how `X` was made. The validator looks for
  this exact name, whichever tool removed the ambient RNA (SoupX, CellBender,
  DecontX or another). The h5ad file does not record whether ambient RNA was
  removed, so the validator reports a missing layer only when `X` shows it
  (check 7).
- The total each cell is normalized to is not fixed. The checks compare each
  cell's profile, where the total cancels out, so any target works.

Checks 1 to 4 look at the whole of `X`, and checks 5 to 9 look only at the first
200 cells (the checked cells). The validator validates that:

1. **Normalization ran.** `X` is not identical to `raw.X`.
2. **`X` holds expression values.** It has no missing (NaN) or infinite values.
3. **`X` was log-transformed.** No value is above about 20. A higher value is
   too high for `log1p` data, so `X` holds raw counts or was never
   log-transformed.
4. **`X` is not all zero.** At least one value in `X` is positive.
5. **`layers['desouped_counts']` holds usable counts.** It has no missing,
   infinite or negative values, and is not all zero.
6. **`layers['desouped_counts']` is a corrected version of `raw.X`.** In the
   checked cells, no value is larger than the matching value in `raw.X`.
7. **`X` was made from its required source.** In each checked cell, once the
   `log1p` is undone, every gene's share of the cell's total matches its share
   in the source. Only genes with a non-zero value in `X` are compared, so genes
   marked filtered are not counted as mismatches. The source is:
   - **If `layers` has `desouped_counts`**, that layer.
   - **If it does not**, `raw.X`.

   When `X` does not match its source, the check fails. If the source is
   `raw.X`, the error also names the likely cause
   ([Why `X` does not match `raw.X`](#why-x-does-not-match-rawx)).

8. **`X` and its source can be compared.** At least one checked cell has values
   in `X` and counts in its source for the same genes. Without one, checks 7 and 9
   would compare nothing and pass without checking anything.
9. **`X` was normalized per cell.** To determine whether `X` is a normalized
   version of its required source, the validator undoes the `log1p` and adds up
   each checked cell's values. Normalizing divides each cell's counts by that
   cell's total count and multiplies them by a target total that is the same for
   every cell, so in a normalized `X` each sum is that shared target. If, for more
   than half of the checked cells, the sum equals the cell's own total count in
   the source instead, `X` was log-transformed without being normalized.

   The check asserts that, for at most half of the checked cells that can be
   compared,

   ```
   sum(expm1(X[cell])) / sum(source[cell]) = 1   (within 0.1%)
   ```

   where both sums run over the genes with a non-zero value in `X`.

Failure of any of these checks is reported as an error. None of these checks
run when there is no `raw.X`.

#### Why `X` does not match `raw.X`

When check 7 (`X` was made from its required source) fails and the required
source is `raw.X`, the validator works out which counts `X` was made from, to
determine the likely cause of the error.

To do this, it undoes the normalization: it reverses the `log1p`, then divides
each cell by its scale factor, which it reads from the cell's smallest non-zero
value (almost always a gene with a count of 1). For an `X` made from
whole-number counts, this gives back those counts: the recovered counts listed
in the table below. Checked cells with fewer than 30 non-zero genes in `X` are
skipped, because their smallest value is not reliably a count of 1.

No processing step adds counts: filtering, quality control and ambient RNA
removal only take them away. So how the recovered counts compare with `raw.X`
points to the cause:

| Recovered counts | Error message | Meaning | What to do |
|---|---|---|---|
| Not whole numbers | `X is not a normalization of any count matrix: …` | `X` was not made by scaling whole-number counts per cell and applying `log1p`. For example, it used a different transform such as SCTransform or TPM, or the counts it was made from were not whole numbers | If `X` was made from counts after ambient RNA removal, add those counts as `layers['desouped_counts']`. Otherwise, rebuild `X` by normalizing and log-transforming `raw.X` |
| Whole numbers, some higher than `raw.X` and none lower | `X was normalized from a different matrix than raw.X: …` | `X` was made from a different matrix | Rebuild `X` from `raw.X`, or replace `raw.X` with the raw counts `X` was made from |
| Whole numbers, some lower than `raw.X` and none higher | `X appears to be normalized from desouped counts, but layers['desouped_counts'] is missing. …` | Counts were removed before `X` was made, most likely by ambient RNA removal, and `layers['desouped_counts']` is missing | Add the counts left after ambient RNA removal as `layers['desouped_counts']` |
| Whole numbers, some higher and some lower | `X was normalized from a different matrix than raw.X. …` | `X` was made from a different count matrix than `raw.X` | Store the counts `X` was made from in `raw.X`. If those were counts after ambient RNA removal, store them as `layers['desouped_counts']` instead, and keep the counts they were removed from in `raw.X` |
| Whole numbers that match `raw.X`, or no checked cell has at least 30 non-zero genes in `X` | `X is not a normalization of raw.X: …` | The validator cannot name a cause. The error gives how far `X` is from `raw.X` | Rebuild `X` by normalizing and log-transforming `raw.X` |

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

1. **Each label matches its term ID.** A label matches the official ontology
   name of the term ID on the same row.
2. **Each label has a term ID.** A row with a label also has a term ID in the
   matching term ID column.
3. **Each label column has its term ID column.** A label column such as `tissue`
   comes with `tissue_ontology_term_id`. A label column without one is a
   warning, not an error, if it holds any labels, because its labels cannot be
   checked.

### Donor metadata

Cells with the same `donor_id` are treated as one person, even when they come
from different source datasets in an integrated object. A `donor_id` must name
the same person in every cell.

| Column | Cells of one donor hold two or more different values | Cells of one donor hold one value plus an unknown |
|---|---|---|
| Organism, sex, manner of death | Error: either the `donor_id` covers two people, or the value is wrong in some cells | Warning: the unknown can be filled in from the donor's other cells |
| Development stage, disease | Warning, because these can legitimately differ between a donor's cells, for example over time or between a tumor and nearby tissue | Warning: the unknown can be filled in from the donor's other cells |

- `unknown`, `na` and empty strings count as unknown. `not applicable` counts
  as a real value. Missing values (NaN) are ignored.
- Donors named `pooled`, `unknown`, `na` or empty are skipped, because none of
  those names one person.

## HCA extensions: gene annotation validations

A gene annotation is the set of genes the counts in `raw.X` were made against.
These checks compare the human Ensembl gene IDs in `var` with Ensembl's history:

1. **Which annotation the counts were made with.** The validator works out which
   Ensembl releases the gene IDs fit, and compares them with the declared
   `gene_annotation_version`
   ([Declared gene annotation](#declared-gene-annotation)).
2. **Which gene IDs are outdated.** The validator lists every gene ID that is
   not in GENCODE v48 (Ensembl release 114), the gene set `cellxgene-schema`
   7.0.0 requires, and says what happened to each, for example renamed, merged
   with another gene, split into several genes or retired
   ([Gene IDs outside the allowed gene set](#gene-ids-outside-the-allowed-gene-set)).

### Gene annotation terms

These are the terms Ensembl, GENCODE and the Genome Reference Consortium use.

- **Gene annotation**: the genes and transcripts of a genome, with their
  positions on a genome assembly, usually published as a GTF file. Counts are
  made against one gene annotation.
- **Ensembl**: the genome database run by EMBL-EBI (the European Bioinformatics
  Institute). Ensembl publishes a gene annotation in numbered **Ensembl
  releases**, a few times a year. Messages about the declared release write
  release 114 as `r114`.
- **Ensembl stable ID**: the identifier Ensembl gives a gene, transcript or
  protein. A human **Ensembl gene ID** has the form `ENSG00000141510`, and can
  carry a version after a dot (`ENSG00000141510.18`). Stable IDs are meant to
  stay the same across releases, but between releases a gene ID can be retired,
  or replaced by one or more new IDs, so an ID that was valid when the counts were
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
genes in `var` and `obs['reference_genome']`. Every finding here is a warning.
Only the data producer (the lab or team that made the h5ad file) can correct the
value.

Two comparisons:

1. **Declared release against `obs['reference_genome']`.** Each Ensembl
   release is built on one genome assembly: releases 55 to 75 on GRCh37, and
   release 76 and later on GRCh38. For each combination of
   `gene_annotation_version` and `reference_genome` found in the cells, the
   validator checks that `reference_genome` names the declared release's
   assembly. An integrated atlas can hold cells aligned to different assemblies,
   so each combination is checked on its own. The comparison runs only when
   every cell's organism is human.
2. **Declared release against the genes.** The validator works out which Ensembl
   releases are compatible with the human Ensembl gene IDs in `var`, and warns
   when the declared release is not one of them. The gene release table stops at
   release 116, so a newer declared release is not checked. The rules are in
   [docs/gene-id-contract.md](../../docs/gene-id-contract.md).

#### When no version is declared

An h5ad file with no `obs['gene_annotation_version']` column, or only missing
values such as `nan` or `unknown`, fails validation, because the schema requires
the field. The genes are still matched against each release, and a warning names
the releases they fit, for example
`This file's gene set is consistent with r105 to r110.`

### Gene IDs outside the allowed gene set

The **allowed gene set** is the list of human gene IDs that `var` is checked
against: **GENCODE v48 (Ensembl release 114), primary assembly only**, meaning
every gene on the chromosomes and on the unlocalized and unplaced sequences,
**minus the genes on alternate loci and patches**. The allowed gene set is
CELLxGENE's own, copied from `cellxgene-schema`.

A gene ID missing from the allowed gene set is a **warning**. The missing IDs
are grouped by what happened to each gene
([Reading the gene ID report](#reading-the-gene-id-report)).

#### Why alternate loci and patches are left out

- At Ensembl release 114, Ensembl lists 86,364 human genes and the allowed gene
  set holds 78,894. Every one of the 7,470 missing genes sits on an alternate
  locus or a patch.
- Aligners count reads against the primary assembly for the same reason. If a
  region and its alternate locus were both included, reads would map to both. A
  gene annotated only on a patch is real in Ensembl, but a pipeline that aligns
  to the primary assembly never counts it.
- Many patch genes in `var` mean the counts were aligned against a reference
  genome that includes patches. Almost no pipeline does that, and such counts
  are hard to compare with other data.

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
- **Shared**: two or more IDs in `var` lead to the same successor.
- **Feature**: a row of `var`, usually a gene.
- Each ID is listed once, even when the ID appears in both `var` and `raw.var`.
- Ensembl's history is followed to the end: if A became B and B later became C,
  the new ID shown is C.

#### Tags

| Tag | When you see it | What to do |
|---|---|---|
| `[rename]` | Ensembl replaced the gene with one new gene, which is in the allowed gene set and not yet in `var`. | Replace the old ID with the new one. |
| `[review]` | <ul><li>Ensembl replaced the gene with a new gene that is already in `var`.</li><li>Ensembl replaced several gene IDs in `var` with the same new gene, for example because it merged them, or because `var` lists one replaced gene both with and without a version suffix.</li><li>`var` lists a gene both with and without a version suffix. The suffixed ID is `[review]`, and so is the bare ID if Ensembl replaced the gene. Otherwise the bare ID keeps the tag it would have on its own.</li><li>`var` lists a gene with two different version suffixes. Both are `[review]`.</li></ul>Exception: the version suffix rules do not apply to a gene Ensembl retired with no single replacement in the allowed gene set, such as a gene removed with no replacement or split into several genes. Each spelling of that gene keeps its own tag, for example `[drop]` for both. | Decide whether to combine the columns. Their counts may not be independent, so adding them can double-count. |
| `[drop]` | <ul><li>Ensembl removed the gene with no replacement.</li><li>Ensembl replaced the gene, and later removed the replacement too.</li><li>Ensembl replaced the gene, but no replacement is in the allowed gene set.</li><li>The gene is on an alternate locus or a patch.</li></ul> | Remove the gene. There is no replacement in the allowed gene set to move its counts to. |
| `[drop or re-align]` | Ensembl split the gene into several genes, and at least one of them is in the allowed gene set. | Remove the gene, or re-run alignment against a newer annotation to get counts for the new genes. |
| `[strip suffix]` | The ID has a version suffix, such as `.17`, and without the suffix it is in the allowed gene set or newer than it. Two more rules for IDs with a version suffix:<ul><li>Any other ID with a version suffix gets the tag it would get without the suffix, and its `Details:` line says "version suffix".</li><li>When `var` also lists the gene under another spelling, the `[review]` row applies instead.</li></ul> | Remove the suffix. |
| `[none]` | The gene is newer than the allowed gene set. | Nothing to fix. |
| `[ask]` | Neither gene table (Ensembl releases 76 to 116) has a record of the ID, for example because the gene was removed before release 76. | Ask the data producer which gene annotation the counts were made with. |

#### Gene location notes

Gene location notes help decide how to treat `[rename]` and `[review]` IDs. When
Ensembl replaced an old gene with one new gene in the allowed gene set, the
validator compares where the two genes sit on the genome, to show whether the
old gene's counts can be moved to the new gene. The note is added to the ID's
`Details:` line, for example:

```
ENSG00000280867 -> ENSG00000283490  merged; old contains new  [rename]
```

The possible notes:

| Note | Meaning |
|---|---|
| None | The new gene covers the old one, which is the usual case |
| `old contains new` | The new gene lies inside the old one |
| `overlap` | The two genes share some positions, but neither covers the other |
| `disjoint` | The two genes share no positions, or sit on different chromosomes or strands |

`old contains new`, `overlap` and `disjoint` mean the new gene does not cover all
of the old one, so some of the old gene's counts may come from positions the new
gene does not include. Check the gene IDs with one of these notes before renaming
or combining them.

#### Gene data sources

The gene ID checks use three data sources. Each is updated on its own schedule,
so their versions can differ.

| Data | Version | Used for |
|---|---|---|
| Allowed gene set | GENCODE v48 (Ensembl release 114) | Whether an ID is valid |
| Gene history table ([how it is built](DEVELOPMENT.md#gene-id-event-table)) | Ensembl releases 76 to 116 | What happened to a retired ID |
| Gene release table ([how it is built](DEVELOPMENT.md#gene-release-interval-table)) | Ensembl releases 76 to 116 | Matching the declared gene annotation, and telling genes on alternate loci or patches apart from genes newer than the allowed gene set |

<!-- Maintainers: these versions are typed by hand, here, elsewhere in this
file and in README.md (search for "v48", "114", "116" and "7.0.0", including the example
output). Update
them when cellxgene-schema is upgraded or either table is regenerated. -->
