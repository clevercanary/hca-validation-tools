# HCA Schema Validator

Checks single-cell data files in h5ad format (the
[AnnData](https://anndata.readthedocs.io/) file format) against the Human Cell
Atlas (HCA) metadata schema.

- Built on the CELLxGENE schema validator by the Chan Zuckerberg Initiative
  (CZI). A copy of it ships inside this package, and its rules still run.
- Changes some CELLxGENE rules for HCA, and adds checks of its own. See
  [What this validator checks](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#what-this-validator-checks).
- Reports **errors**, which fail the file, and **warnings**, which are worth
  fixing but do not fail it.

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

This is a summary. The full list, with every rule, is in the
[check inventory](https://github.com/clevercanary/hca-validation-tools/blob/main/docs/dataset-validator-checks.md).

Terms used below:

- **`obs`**: the table of cells and their metadata
- **`var`** and **`raw.var`**: the tables of genes
- **`uns`**: metadata for the whole file
- **`X`**: the normalized expression matrix
- **`raw.X`**: the raw count matrix
- **`obsm`**: cell embeddings, such as UMAP coordinates

### Checks from CELLxGENE

CELLxGENE is CZI's single-cell data portal, and its schema says what a file must
contain to be accepted there. Its validator (`cellxgene-schema` 7.0.1), included
in this package, checks the groups below. Groups marked "Changed for HCA" are
covered in the next section.

- **File format**: the h5ad encoding version, unique column names, and no
  reserved or deprecated columns.
  *[Changed for HCA](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#where-hca-changes-cellxgenes-rules).*
- **Cell metadata (`obs`)**: required columns are present, values have the right
  type, and nothing is blank. Ontology terms must be valid for cell type, tissue,
  assay, disease, development stage, sex and organism.
  *[Changed for HCA](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#where-hca-changes-cellxgenes-rules).*
- **Gene metadata (`var`, `raw.var`)**: gene IDs are unique and appear in the
  organism's gene list.
  *[Changed for HCA](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#where-hca-changes-cellxgenes-rules).*
- **File metadata (`uns`)**: title, batch condition, default embedding, and
  plot colors.
- **Matrices (`X`, `raw.X`)**: values are stored as 32-bit floats, either as a
  dense matrix or in CSR (compressed sparse row) format, and CSR is required
  when most values are zero. Raw counts are whole positive numbers. Every cell has at
  least one count, and `X` and `raw.X` cover the same cells and genes.
  *[Changed for HCA](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#where-hca-changes-cellxgenes-rules).*
- **Embeddings (`obsm`)**: at least one embedding, with the right shape and no
  infinite values.
- **Spatial data**: image and spot rules for Visium and Slide-seqV2.
- **Duplicate cells**: no two cells have identical raw counts.

Details: [CELLxGENE checks](https://github.com/clevercanary/hca-validation-tools/blob/main/docs/dataset-validator-checks.md#5-vendored-cellxgene_schema-checks-shared-by-cxg-and-hca-validators).

### Where HCA changes CELLxGENE's rules

- **HCA's schema replaces CELLxGENE's** (`hca_schema_definition.yaml`):
  - Organism is recorded on each cell in `obs`, not once in `uns`. CELLxGENE
    rejects that `obs` column as deprecated; HCA requires it.
  - Fields can be **optional** (checked only when present), **strongly
    recommended** (a warning when missing, not an error) or **forbidden** (an
    error when present, such as self-reported ethnicity, to protect donor
    privacy).
  - Some fields must match a set format.
  - List fields must hold non-empty text.
- **Label columns are allowed.** CELLxGENE reserves columns such as `cell_type`
  and `tissue` for labels it adds itself, and rejects files that already have
  them. HCA files keep these columns, and HCA checks their values instead (see
  below).
- **Gene ID warnings are reworded.** Each one names the gene list version, for
  example "not found in GENCODE v48 (Ensembl 114)", and all of them are listed
  after the other warnings.
- **The raw count checks run even when there are other errors.** CELLxGENE
  skips them when a file already has errors. HCA runs them anyway, as long as
  `obs` has `assay_ontology_term_id`, so one pass shows more problems.
- **Extra cell metadata columns are left alone.** Columns in `obs` that are not
  in the schema, such as ones a curator added, are not checked.

Details: [HCA changes](https://github.com/clevercanary/hca-validation-tools/blob/main/docs/dataset-validator-checks.md#4-hca-schema-validator-hcavalidator).

### Checks added by HCA

- **Expression matrices**: `X` must be `raw.X`, or the ambient-RNA-corrected
  counts in `layers['desouped_counts']` when those exist, normalized per cell and
  log-transformed. The check finds an `X` that holds raw counts, was never
  normalized, or came from a different matrix.
  [Details](https://github.com/clevercanary/hca-validation-tools/blob/main/docs/dataset-validator-checks.md#41-expression-matrix-contract-check_x_normalization).
- **Cell metadata labels**: a text label column such as `tissue` must sit next to
  its ontology term ID column (`tissue_ontology_term_id`), and each label must
  match that term's official name.
  [Details](https://github.com/clevercanary/hca-validation-tools/blob/main/docs/dataset-validator-checks.md#4-hca-schema-validator-hcavalidator).
- **Donor metadata**: all cells from one `donor_id` must agree on organism, sex
  and manner of death. Different development stages or diseases for one donor
  are a warning only.
  [Details](https://github.com/clevercanary/hca-validation-tools/blob/main/docs/dataset-validator-checks.md#42-donor-level-consistency-check_donor_consistency).
- **Declared gene annotation**: the annotation version a file declares in
  `obs['gene_annotation_version']` is compared with the genes the file actually
  contains, and with `obs['reference_genome']`. Warnings only.
  [Details](https://github.com/clevercanary/hca-validation-tools/blob/main/docs/dataset-validator-checks.md#43-declared-gene-annotation-vs-the-files-genes-check_gene_annotation_version).
- **Outdated gene IDs**: human gene IDs that are not in the allowed gene set
  are grouped by what happened to them, each with a suggested action. See
  [Gene IDs](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#gene-ids).
  [Details](https://github.com/clevercanary/hca-validation-tools/blob/main/docs/dataset-validator-checks.md#44-retired-feature-identifiers-check_retired_feature_ids).

## Gene IDs

The **allowed gene set** is the fixed list of human gene IDs a file is checked
against: **GENCODE v48 (Ensembl release 114), primary assembly only**. That
means every gene on the chromosomes and on the unplaced and unlocalized
scaffolds, **minus the genes on alternate (alt) and patch contigs**. The
validator's output uses this name, and so does this README. The terms are
explained below.

The rules behind this output, and the reasons for them, are in the
[gene ID contract](https://github.com/clevercanary/hca-validation-tools/blob/main/docs/gene-id-contract.md).

### Background

- **Ensembl** is the public genome annotation database run by EMBL-EBI (the
  European Bioinformatics Institute). It gives each gene a stable ID, such as
  `ENSG00000141510`, and publishes a numbered release a few times a year.
- Between releases, Ensembl may rename, merge, split or remove genes. An ID that
  was valid when a file was made can be outdated later.
- **GENCODE** is the human gene annotation project. Its gene set is the one
  Ensembl publishes, but GENCODE uses its own version numbers: GENCODE v48 is
  Ensembl release 114.
- **Primary assembly** is the main human genome sequence (GRCh38): the
  chromosomes, plus small pieces of sequence whose chromosome or position on it
  is not yet known. It leaves out the "patch" and "alternate" sequences that
  describe variant versions of some regions.

### The allowed gene set

- It is CELLxGENE's own gene set, copied from `cellxgene-schema`, so any ID it
  rejects, CELLxGENE rejects too.
- Here, an ID that is not in the allowed gene set is a **warning**. At CELLxGENE it is an
  **error**, so these IDs must be fixed before a file can go there.

### Reading the output

All of the outdated human IDs are reported together as one block with four
parts:

- **Headline**: how many IDs are not in the allowed gene set
- **`Summary:`**: one line per group, with the count, what happened, and a tag
- **`Actions:`**: what each tag in this file means
- **`Details:`**: one line per ID, with the old ID, the new ID (if there is one),
  what happened, and the tag

Example:

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

Things to know:

- Each ID appears once, even when it is in both `var` and `raw.var`.
- An ID listed under `Details:` does not also get its own
  `Feature ID '…' not found` warning, because the Details line already says
  that, and more.
- Any `Feature ID '…' not found` warnings that remain are for features this
  report does not cover: anything that is not a human Ensembl gene ID, such as
  other species' genes, spike-ins, transgenes or custom features.
- Ensembl's history is followed through every step: if A became B and B later
  became C, the new ID shown is C.

### What each tag means

| Tag | When you see it | What to do |
|---|---|---|
| `[rename]` | Ensembl replaced the gene with one new gene, which is in the allowed gene set and not already in the file | Replace the old ID with the new one |
| `[review]` | The new gene is already in the file, or several IDs in the file lead to the same new gene, or the file spells the same gene more than one way (with and without a version suffix, or with two different suffixes) | Decide whether to combine them. The counts may not be independent, and adding them can double-count. The decision belongs with whoever produced the data. |
| `[drop]` | The gene was removed with no replacement; or its replacement was removed later; or its replacement is not in the allowed gene set; or the gene is on a patch or alternate sequence | Remove the gene. Its counts cannot be moved to another ID. |
| `[drop or re-align]` | Ensembl split the gene into several genes | Remove the gene, or re-run alignment against a newer annotation to get counts for the new genes |
| `[strip suffix]` | The ID has a version suffix, such as `.17` | Remove the suffix. This alone does not make the ID valid; check its line for anything else. |
| `[none]` | The gene is newer than the allowed gene set | Nothing. The file is correct; the allowed gene set is older than the file. |
| `[ask]` | Ensembl has no record of what happened to the ID, for example because it was removed before release 76 | Ask the data producer which gene annotation the file was built with |

The same tags, with each case listed separately, are in the
[check inventory](https://github.com/clevercanary/hca-validation-tools/blob/main/docs/dataset-validator-checks.md#44-retired-feature-identifiers-check_retired_feature_ids).

Some `Details:` lines end with a note on where the old and new genes sit on the
genome:

- **No note**: the new gene covers the old one. This is the usual case.
- **`old contains new`**: the new gene is inside the old one.
- **`overlap`**: they share some positions, but neither covers the other.
- **`disjoint`**: they share no positions, or are on a different chromosome or
  strand.

A note does not mean the replacement is wrong. It means the line is worth a
closer look before renaming.

### Which versions are used

Three gene data sources are used. They are updated separately, so their versions
can differ:

| Data | Version | Used for |
|---|---|---|
| Allowed gene set | GENCODE v48 (Ensembl release 114) | Whether an ID is valid |
| Gene history ([gene ID event table](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#gene-id-event-table)) | Ensembl releases 76 to 116 | What happened to an outdated ID |
| Gene presence by release ([gene release interval table](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#gene-release-interval-table)) | Ensembl releases 76 to 116 | Checking the declared gene annotation, and telling genes on patch or alternate sequences apart from genes newer than the allowed gene set |

A gene Ensembl added after the allowed gene set was made is in Ensembl but not
in the allowed gene set. That is the `[none]` case.

<!-- Maintainers: these versions are typed by hand, here and elsewhere in this
README (search for "v48", "114" and "116", including the example output). Update
them when cellxgene-schema is upgraded or either table is regenerated. -->

## Testing

From the repository root:

```bash
cd packages/hca-schema-validator
uv run pytest tests/
```

## Project Structure

```
hca_schema_validator/
├── src/
│   └── hca_schema_validator/
│       ├── __init__.py       # Package exports
│       ├── validator.py      # HCAValidator and the HCA-specific checks
│       ├── ontology_data/    # Ontology overlay files (see below)
│       ├── gene_release_intervals.csv.gz  # Gene presence per Ensembl release (see below)
│       └── gene_id_events.csv.gz          # What became of each retired gene ID (see below)
├── tests/
│   └── test_validator.py # Unit tests
├── pyproject.toml        # uv/PEP 621 configuration & dependencies
└── README.md            # This file
```

## Ontology Data Overlay

The validator depends on `cellxgene-ontology-guide` for ontology term lookups. When that
package is missing terms we need (e.g., newly added CL or EFO terms), we generate updated
ontology data files and overlay them at runtime.

### How it works

`_vendored/cellxgene_schema/ontology_parser.py` monkey-patches two functions from
`cellxgene_ontology_guide.supported_versions`:

- `load_supported_versions()` loads upstream version data and patches only the ontology
  versions listed in `_ONTOLOGY_VERSION_OVERRIDES` — all other ontologies and any new
  entries added by future package releases are preserved unchanged.
- `load_ontology_file(file_name)` checks `ontology_data/` first for a `.json.zst` file,
  falling back to the package's bundled data.

### Current overlays

| Ontology | Overlay Version | Bundled Version | Why |
|----------|----------------|-----------------|-----|
| CL       | v2025-12-17    | v2025-07-30     | Missing salivary gland cell types (CL:4052065-4052069) |

### How to add/update an ontology overlay

Prerequisites: Python 3.10+, Docker, ~1GB disk for OWL files.

1. **Clone CZI's ontology-guide repo** (contains the build pipeline):
   ```bash
   cd /tmp && mkdir ontology-guide-build && cd ontology-guide-build
   git clone --depth 1 https://github.com/chanzuckerberg/cellxgene-ontology-guide.git
   ```

2. **Set up build environment**:
   ```bash
   python3 -m venv venv && source venv/bin/activate
   pip install owlready2==0.48 zstandard jsonschema semantic-version referencing cellxgene-ontology-guide
   docker pull obolibrary/robot:v1.9.8
   ```

3. **Create a targeted ontology_info JSON** with only the ontology to build.
   Save as `cellxgene-ontology-guide/ontology-assets/ontology_info_custom.json`:
   ```json
   {
     "7.0.0": {
       "ontologies": {
         "EFO": {
           "version": "v3.86.0",
           "source": "https://github.com/EBISPOT/efo/releases/download/{version}/{filename}",
           "filename": "efo.owl"
         }
       }
     }
   }
   ```
   Find the latest release version on the ontology's GitHub releases page (e.g.,
   [CL releases](https://github.com/obophenotype/cell-ontology/releases),
   [EFO releases](https://github.com/EBISPOT/efo/releases)).

   Copy the ontology entry from the existing `ontology_info.json` in
   `ontology-assets/` and update the `version` field. Keep `source`, `filename`,
   and any other fields (like `cross_ontology_mapping`) the same.

4. **Run the build script**:
   ```python
   #!/usr/bin/env python3
   import json, logging, os, sys
   logging.basicConfig(level=logging.INFO)

   REPO_DIR = "/tmp/ontology-guide-build/cellxgene-ontology-guide"
   sys.path.insert(0, os.path.join(REPO_DIR, "tools/ontology-builder/src"))
   import env
   env.ONTOLOGY_INFO_FILE = os.path.join(REPO_DIR, "ontology-assets/ontology_info_custom.json")
   env.ONTOLOGY_ASSETS_DIR = os.path.join(REPO_DIR, "ontology-assets")

   from all_ontology_generator import _download_ontologies, _parse_ontologies, get_ontology_info_file
   onto_info = get_ontology_info_file(env.ONTOLOGY_INFO_FILE)["7.0.0"]["ontologies"]
   _download_ontologies(onto_info)
   for f in _parse_ontologies(onto_info):
       logging.info(f"Generated: {f}")
   ```

5. **Copy the `.json.zst` output** into `src/hca_schema_validator/ontology_data/`.

6. **Add an entry to `_ONTOLOGY_VERSION_OVERRIDES`** in `ontology_parser.py`:
   ```python
   _ONTOLOGY_VERSION_OVERRIDES = {
       ("7.0.0", "CL"): "v2025-12-17",
       ("7.0.0", "EFO"): "v3.86.0",  # new
   }
   ```

7. **Verify and test**:
   ```bash
   uv run python -c "
   from hca_schema_validator._vendored.cellxgene_schema.ontology_parser import ONTOLOGY_PARSER
   print(ONTOLOGY_PARSER.is_valid_term_id('CL:4052065'))  # True
   "
   uv run pytest tests/ -v
   ```

8. **Clean up**: `rm -rf /tmp/ontology-guide-build`

### Removing the overlay

Once `cellxgene-ontology-guide` publishes a version that includes all the terms we need:

1. Delete the overlay files from `ontology_data/` (keep only `__init__.py`)
2. Revert `ontology_parser.py` to its original form:
   ```python
   from cellxgene_ontology_guide.ontology_parser import OntologyParser
   ONTOLOGY_PARSER = OntologyParser(schema_version="v7.0.0")
   ```
3. Bump `cellxgene-ontology-guide` version in `pyproject.toml`

## Gene Release Interval Table

`check_gene_annotation_version` compares the annotation a file declares in
`obs['gene_annotation_version']` against the genes the file actually contains. To
do that it needs to know which Ensembl releases each gene existed in, which is
what `src/hca_schema_validator/gene_release_intervals.csv.gz` records.

### How it works

One row per gene per contiguous run of releases it was present in:

```
# ensembl GRCh38 gene presence, releases 76-116
gene_id,first_release,last_release
ENSG00000000003,76,116
```

Intervals rather than a single `(first, last)` pair because genes are
occasionally **resurrected** — `ENSG00000288593` is retired at r105 and returns
at r109, and a flat pair would claim it existed at r106–r108. Two genes in the
shipped range have more than one interval.

The table is sized by genes, not releases, so covering the whole GRCh38 history
costs no more than covering a handful of releases.

### Current table

| | |
|---|---|
| Ensembl releases covered | **r76 – r116** (r76 is the first GRCh38 core database) |
| Genes | 93,543 |
| Intervals | 93,545 |
| File size | 249 KB gzipped |

### When to regenerate

**The validator tells you.** When a file declares a release newer than the table
covers, the check says so rather than failing the file:

> `obs['gene_annotation_version']` is `'v117'`, which is newer than this
> reference data covers (through r116), so the genes in this file were not
> checked against it.

That warning is the trigger. Regenerate when you see it, or when Ensembl ships a
release you want to date against.

The table also sets the ceiling on the Ensembl/GENCODE ambiguity: a number below
r76 could be either scheme, and the boundary is this table's last release minus
GENCODE's offset of 66 — so regenerating the table moves it. It is **not** read
from the vendored `gencode_files/gene_info.yml`, which records the GENCODE
version `cellxgene-schema` pinned rather than what GENCODE has issued, and so
lags: it says 48 while this table reaches r116, which is GENCODE 50.

### How to regenerate

Ensembl keeps a core database per release on its public MySQL server, so the
whole history is one query per release rather than a download. Needs outbound
MySQL to `ensembldb.ensembl.org:3306` (user `anonymous`, no password).

1. Run the generator **from the repository root** -- the script lives there, not
   in this package. About two seconds per release, so roughly 90 seconds for the
   full GRCh38 range:

   ```bash
   cd ../..   # repository root, if you are in packages/hca-schema-validator
   uv run --no-project --with pymysql python scripts/build_gene_release_intervals.py
   ```

   It writes `packages/hca-schema-validator/src/hca_schema_validator/gene_release_intervals.csv.gz`
   by default; `--out` writes elsewhere. The verification commands below are
   relative to this package, so return here first.

2. Check the header records the range you expect, and that the gene and interval
   counts moved in the direction you expect:

   ```bash
   gzip -dc src/hca_schema_validator/gene_release_intervals.csv.gz | head -3
   gzip -dc src/hca_schema_validator/gene_release_intervals.csv.gz | tail -n +3 | wc -l
   ```

3. Run the tests. `test_resurrected_gene_is_absent_between_its_runs` pins the
   resurrection behaviour against a known gene, so a regeneration that flattened
   intervals would fail there:

   ```bash
   uv run pytest tests/ -q
   ```

4. Commit the regenerated file, and update the **Current table** above and the
   [versions table](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#which-versions-are-used) under Gene IDs.

### Why not `stable_id_event`

Ensembl's `stable_id_event` table is the right source for *retirement history* —
it is what the [gene ID event table](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#gene-id-event-table) below is built from —
but it cannot answer presence at a given release. Self-mappings are not recorded
exhaustively: at r116 TP53 has 24 rows across the 74 sessions, so an identifier's absence
from a session says nothing about whether it existed then. Presence has to come
from each release's own `gene` table, which is what this generator queries.

This section used to give a second reason, that `mapping_session` stops at r99.
That was wrong. `old_release` and `new_release` are `varchar`, so `MAX()`
compares them lexically and `'99'` beats `'116'`; cast numerically and the
sessions run continuously to r116.

## Gene ID Event Table

`check_retired_feature_ids` produces the outdated gene ID report described in
[Gene IDs](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#gene-ids). `src/hca_schema_validator/gene_id_events.csv.gz` records
what Ensembl says became of each retired ID, and the report is built from it.

### How it works

One row per retired identifier per successor:

```
# ensembl GRCh38 retired gene ids, sessions r76-r116, successor coordinates from r116
old_id,new_id,event,old_chrom,old_start,old_end,old_strand,old_release,new_chrom,new_start,new_end,new_strand
ENSG00000002079,,retired,7,99238829,99306809,1,113,,,,
```

`event` is derived from Ensembl's bookkeeping and nothing else -- how many
successors `stable_id_event` records, how many retired identifiers name each
one, and whether the successor already existed in the release the old
identifier was last in -- so every class is a statement a curator can go and
check:

| `event` | Meaning |
|---|---|
| `retired` | no successor |
| `renamed` | one successor, first issued at that session, which no other retired identifier names: a new name for the same gene |
| `merged` | one successor that was already there (the surviving gene absorbed this one), or that other retired identifiers also name |
| `split` | several successors, one row each |

`old_release` is the last release that still carried the identifier, and the old
coordinates are that release's. Per-gene rather than one release for the whole
table: breast's sources declare `v75`, `v87` **and** `v98`, and comparing
everything against a single old release leaves genes that existed in neither end
of the comparison unexplainable.

**Chains are not resolved here.** Ensembl may replace A with B and later B with
C; every hop is a row, and the validator walks them. Keeping the table a
transcription means any row can be checked against the server it came from.

**`score` is deliberately absent.** Of the gene events carrying a successor since
r98, 1,202 fall in 0.9–0.999 and 2 sit at exactly 1.0, so a threshold in that
band separates nothing — and the column is `float NOT NULL DEFAULT '0'`, so an
exact zero cannot be told apart from "never scored", which is precisely the rows
one would want to treat as suspicious.

### Current table

| | |
|---|---|
| Ensembl sessions covered | **r76 → r116** (30 sessions, GRCh38 on both sides) |
| Retired identifiers | 7,132 — 5,768 retired, 21 renamed, 1,249 merged, 94 split |
| Rows | 7,494 |
| Still in the allowed set | 40 of the 7,132 (retired at r115 or r116, after GENCODE v48); the validator never classifies them |
| Successor coordinates | from r116; 39 successors have been retired themselves and have none |
| File size | 122 KB gzipped |

Old-release spans on patch contigs are in that release's own coordinate system
(the same gene reads `CHR_HG2290_PATCH:88,992,415` in one release and
`HG2290_PATCH:135,997` in another), so a patch gene's old and new spans are not
comparable. The validator never compares them: rows whose successor is off the allowed
gene set carry no geometry flag.

### When to regenerate

When Ensembl ships a release. Nothing in the validator detects staleness here —
unlike the interval table, which says when a file declares a release it does not
cover — because a missing recent event looks exactly like an identifier that was
never retired. Regenerating alongside the interval table keeps the two in step.

### How to regenerate

Needs outbound MySQL to `ensembldb.ensembl.org:3306` (user `anonymous`, no
password). About four minutes, mostly the per-release coordinate queries.

1. Run the generator **from the repository root** — the script lives there, not
   in this package:

   ```bash
   cd ../..   # repository root, if you are in packages/hca-schema-validator
   uv run --no-project --with pymysql python scripts/build_gene_id_events.py
   ```

   It writes `packages/hca-schema-validator/src/hca_schema_validator/gene_id_events.csv.gz`
   by default; `--out` writes elsewhere. The commands below are relative to this
   package, so return here first: `cd packages/hca-schema-validator`.

2. Read what it printed. It names the sessions it used, every gap in the session
   chain and the gene build it held that gap against, and the class counts. A
   gap with a gene build inside it is refused rather than reported — see below.

3. Check the event classes are present and plausible:

   ```bash
   gzip -dc src/hca_schema_validator/gene_id_events.csv.gz | head -3
   uv run python -c "import pandas as pd; d = pd.read_csv('src/hca_schema_validator/gene_id_events.csv.gz', comment='#'); print(d.event.value_counts())"
   ```

4. Run the tests. They pin real identifiers from this table — a rename, a merge,
   a split, a chain, and a replacement the coordinates refute — so a regeneration
   that lost any of those shapes fails here:

   ```bash
   uv run pytest tests/ -q
   ```

5. Commit the regenerated file, and update the **Current table** above and the
   [versions table](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#which-versions-are-used) under Gene IDs.

### The session chain is not contiguous, and that is correct

Ensembl creates a mapping session when the **gene set is rebuilt**, not when a
release is issued. In the early GRCh38 range releases came out faster than gene
builds did, so ten of the forty release boundaries between r76 and r116 have
no session (thirty do):
r78 ships r77's gene set unchanged, down to every stable id, version and span,
and r78's own database records no 77→78 session either.

The generator therefore does not refuse a gap. It holds each one against
`genebuild.last_geneset_update` from the two bounding releases, and refuses only
when they differ — which would mean a session is genuinely missing from the
archive, and with it every identifier changed across it.

## Acknowledgements

- **The CELLxGENE team at the Chan Zuckerberg Initiative (CZI).** This package
  is built on their schema validator, `cellxgene-schema`, from
  [chanzuckerberg/single-cell-curation](https://github.com/chanzuckerberg/single-cell-curation).
  A copy is included here under the MIT License and extended for HCA. Every
  CELLxGENE check listed above, and the allowed gene set, comes from
  their work. See [`NOTICE`](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/NOTICE).
- **`cellxgene-ontology-guide`**, also by the CZI CELLxGENE team, which supplies
  the ontology data the validator checks terms against, and the build pipeline
  the [ontology overlay](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/README.md#ontology-data-overlay) uses.
- **[GENCODE](https://www.gencodegenes.org/)**, the human gene annotation behind
  the allowed gene set.
- **[Ensembl](https://www.ensembl.org/)** at EMBL-EBI, whose public database the
  two gene tables in this package are built from.

## License

MIT
