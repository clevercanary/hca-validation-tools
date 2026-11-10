# HCA Schema Validator

Validates single-cell data files in h5ad format (the
[AnnData](https://anndata.readthedocs.io/) file format) against the
[Human Cell Atlas (HCA) Tier 1 metadata schema](https://data.humancellatlas.org/metadata/tier-1).

## Installation

Requires Python 3.10 or later.

```bash
pip install hca-schema-validator
```

## What it checks

- **Inherited CELLxGENE checks.** Checks inherited from the CELLxGENE
  validator (`cellxgene-schema` 7.0.1) on the h5ad file's structure, cell and shared
  metadata, ontology terms, gene IDs, matrices and embeddings
  ([Core CELLxGENE checks](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/CHECKS.md#core-cellxgene-checks)).
- **HCA Tier 1 schema.** Required fields are present, strongly recommended fields are
  flagged when missing, and values have the right form. HCA replaces some
  CELLxGENE rules with its own ([HCA overrides](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/CHECKS.md#hca-overrides)).
- **Expression matrices.** `X` is a normalized, log-transformed version of the
  raw counts in `raw.X` ([Expression matrices](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/CHECKS.md#expression-matrices)).
- **Cell metadata labels.** Any label a team fills in, such as `tissue`, matches
  the ontology name of its term ID
  ([Cell metadata labels](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/CHECKS.md#cell-metadata-labels)).
- **Donors.** One `donor_id` names one person, with one organism, sex and
  manner of death
  ([Donor metadata](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/CHECKS.md#donor-metadata)).
- **Declared gene annotation.** `gene_annotation_version` fits the genes in `var`
  and `reference_genome`
  ([Declared gene annotation](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/CHECKS.md#declared-gene-annotation)).
- **Gene IDs.** Human gene IDs missing from the allowed gene set (GENCODE v48,
  Ensembl 114, primary assembly only) are listed in one gene ID report, with a
  tag saying what to do about each
  ([Gene IDs outside the allowed gene set](https://github.com/clevercanary/hca-validation-tools/blob/main/packages/hca-schema-validator/CHECKS.md#gene-ids-outside-the-allowed-gene-set)).

The validator reports two kinds of finding:

- **Errors**: the h5ad file does not meet the schema.
- **Warnings**: something to review or fix. A missing **strongly recommended**
  field is a warning, not an error.

## Usage

The validator runs from Python. It validates two kinds of h5ad file, and the two
kinds have different validation requirements:

- **Source dataset** (`object_kind="source"`): holds data from a single study.
- **Integrated object** (`object_kind="integrated"`): holds data from several
  source datasets integrated into an atlas.

```python
# Validate a source dataset.
from hca_schema_validator import HCAValidator

# object_kind is required: "source" or "integrated". Leaving it out raises a
# TypeError.
validator = HCAValidator(object_kind="source")

# Validate an h5ad file. The result is False when there are errors.
is_valid = validator.validate_adata("path/to/file.h5ad")

print("✅ No errors" if is_valid else "❌ Errors:")
for error in validator.errors:
    print(f"  - {error}")

# An h5ad file with no errors can still have warnings to review or fix,
# including the gene ID report.
for warning in validator.warnings:
    print(f"  ! {warning}")
```

Pass the `object_kind` that matches the h5ad file.

Validate a source dataset:

```python
validator = HCAValidator(object_kind="source")
is_valid = validator.validate_adata("path/to/file.h5ad")
```

Validate an integrated object:

```python
validator = HCAValidator(object_kind="integrated")
is_valid = validator.validate_adata("path/to/atlas.h5ad")
```

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
