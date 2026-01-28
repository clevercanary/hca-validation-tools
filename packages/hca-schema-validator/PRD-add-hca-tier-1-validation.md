# PRD: HCA Schema Validator — HCA-Specific Field Validation

## Goal

Extend the HCA schema validator to enforce HCA-specific required fields, enum constraints, and regex pattern constraints on `.h5ad` uns and obs, beyond what the base cellxgene schema validates.

## Fields

### uns — required presence + list type

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `study_pi` | `list` of strings | Yes | "Last, First" format. At least one entry. |

### obs — required presence (free-text string, no enum/pattern)

| Field | Type | Required |
|-------|------|----------|
| `sample_id` | string | Yes |
| `library_id` | string | Yes |
| `institute` | string | Yes |
| `library_preparation_batch` | string | Yes |
| `library_sequencing_run` | string | Yes |
| `alignment_software` | string | Yes |

### obs — required enum

| Field | Allowed Values |
|-------|---------------|
| `manner_of_death` | `0`, `1`, `2`, `3`, `4`, `unknown`, `not applicable` |
| `sample_source` | `surgical donor`, `postmortem donor`, `living organ donor` |
| `sample_collection_method` | `brush`, `scraping`, `biopsy`, `surgical resection`, `blood draw`, `body fluid`, `other` |
| `sampled_site_condition` | `healthy`, `diseased`, `adjacent` |
| `sample_preservation_method` | `fresh`, `ambient temperature`, `cut slide`, `paraffin block`, `frozen at -70C`, `frozen at -80C`, `frozen at -150C`, `frozen in liquid nitrogen`, `frozen in vapor phase`, `RNAlater at 4C`, `RNAlater at 25C`, `RNAlater at -20C`, `other` |
| `sequenced_fragment` | `3 prime tag`, `5 prime tag`, `full length`, `probe-based` |
| `reference_genome` | `GRCh38`, `GRCh37`, `GRCm39`, `GRCm38`, `GRCm37`, `not applicable` |

### obs — required pattern (regex)

| Field | Pattern | Examples |
|-------|---------|----------|
| `cell_enrichment` | `^(CL:\d{7}(\+\|-)|(na))$` | `CL:0000540+`, `CL:0000236-`, `na` |
| `gene_annotation_version` | `^(v(7[5-9]\|[8-9][0-9]\|10[0-9]\|11[01])\|GCF_000001405\.(2[5-9]\|3[0-9]\|40))$` | `v75`, `v111`, `GCF_000001405.40` |

## Implementation Gap Analysis

What the existing schema YAML + vendored validator already supports vs what needs code changes:

| Capability | Schema YAML support | Vendored Python support | Gap? |
|---|---|---|---|
| obs required string column | Yes (`type: string`, `required: True`) | Yes (`_validate_dataframe`) | None |
| obs enum column | Yes (`enum: [...]`) | Yes (line 745-751) | None |
| obs regex pattern column | **No** — no `pattern` key in schema YAML | **No** — no generic regex validation for obs columns | **New feature needed** |
| uns `type: list` with `element_type: string` | Partially — `type: list` exists but only `element_type: match_obs_columns` | `_validate_list()` only handles `match_obs_columns` (line 921) | **Code change needed** — add `element_type: string` handling |

## Changes Required

1. **`hca_schema_definition.yaml`** — Add all fields to the `uns.keys` and `obs.columns` sections using existing schema patterns where possible (string, enum). Use new `pattern` key for regex fields.

2. **`HCAValidator` in `src/hca_schema_validator/validator.py`** — Override `_validate_list()` to add an `element_type: string` branch that validates each element is a non-empty string.

3. **`HCAValidator` in `src/hca_schema_validator/validator.py`** — Override `_validate_column()` to add handling for a `pattern` key in column definitions: run `re.fullmatch(pattern, value)` against all unique values in the column and report invalids.

4. **Tests** — Add test cases for each new field covering valid data, missing columns, invalid enum values, and regex mismatches.
