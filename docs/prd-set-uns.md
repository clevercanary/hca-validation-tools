# PRD: `set_uns` — Schema-Aware Dataset Metadata Editing

**Status:** Draft
**Date:** 2026-03-28
**Issue:** #229

## Problem

When preparing h5ad files for HCA submission, wranglers need to set dataset-level metadata in `uns` — things like `title`, `study_pi`, `ambient_count_correction`, etc. Today this requires:

1. Knowing which fields exist and where they go
2. Looking up valid values (enums, ontology constraints)
3. Writing Python to set them
4. Manually checking you didn't typo a field name or use an invalid value

This is error-prone and slow, especially for wranglers who aren't Python-fluent.

## Goals

1. **Schema-aware** — the tool knows the HCA tier 1 uns fields, their types, and valid values
2. **Validates before writing** — rejects unknown fields, invalid enum values, wrong types
3. **Cross-validates** — `batch_condition` values must be real obs columns, `default_embedding` must be a real obsm key
4. **Logged** — every edit tracked via `write_h5ad()` provenance system

## HCA Tier 1 `uns` Fields

Source: `shared/src/hca_validation/schema/slots.yaml`, `shared/src/hca_validation/schema/dataset.yaml`, `data_dictionaries/core_data_dictionary.json`

| Field | Required | Type | Validation |
|-------|----------|------|------------|
| `title` | No* | string | Non-empty |
| `description` | Yes | string | Non-empty |
| `study_pi` | Yes | list[string] | Non-empty list, each element non-empty |
| `batch_condition` | No | list[string] | Each value must be a column in `obs` |
| `default_embedding` | No | string | Must be a key in `obsm` |
| `comments` | No | string | Free text |
| `ambient_count_correction` | Yes | string | Free text (common: none, soupx, cellbender) |
| `doublet_detection` | Yes | string | Free text (common: none, doublet_finder, manual) |

*`title` is required by cellxgene schema but marked optional in the HCA data dictionary.

**Not settable via this tool** (reserved, set by cellxgene post-upload):
- `schema_version`, `schema_reference`, `citation`

**Not in scope** (not stored in uns):
- `dataset_id`, `contact_email`, `publication_doi` — these live in the entry sheet / external catalog, not in the h5ad

## API

### `set_uns(path, field, value)`

**Parameters:**
- `path: str` — path to h5ad file
- `field: str` — uns field name (must be a known HCA uns field)
- `value: str | list[str]` — value to set

**Returns:** Dict with `output_path`, `editing`, `wrote`, `field`, `old_value`, `new_value` on success, or `error` on failure. See implementation for exact shape.

### Validation rules

1. **Unknown field** → error listing valid field names
2. **Type mismatch** — passing a string to a list field or vice versa → error
4. **`batch_condition`** — each value checked against `adata.obs.columns`; unknown columns → error listing valid columns
5. **`default_embedding`** — value checked against `adata.obsm.keys()`; unknown key → error listing valid keys
6. **Empty required field** — setting a required field to empty string/list → error

### `list_uns_fields(path)`

A companion read-only tool that shows the current state of all HCA uns fields for a file — what's set, what's missing, and cross-reference targets (obs columns, obsm keys). See implementation for exact response shape.

## Example Workflow

```
User: "Set up the dataset metadata for this file"

Claude: [calls list_uns_fields] → sees title is set but study_pi,
        ambient_count_correction, doublet_detection are missing

Claude: "The file has title='My Dataset' but is missing three required
        fields: study_pi, ambient_count_correction, doublet_detection.
        Who are the study PIs?"

User: "Teichmann, Sarah A and Haniffa, Muzlifah"

Claude: [calls set_uns(path, "study_pi", ["Teichmann,Sarah,A", "Haniffa,Muzlifah"])]
Claude: [calls set_uns(output_path, "ambient_count_correction", "cellbender")]
Claude: [calls set_uns(output_path, "doublet_detection", "none")]
```

## Where the Schema Lives

The canonical field definitions live in `shared/`:
- **LinkML schemas**: `shared/src/hca_validation/schema/` — `dataset.yaml`, `slots.yaml`, etc.
- **Data dictionary**: `data_dictionaries/core_data_dictionary.json` — generated from LinkML, has `annDataLocation` annotations
- **Generated Pydantic models**: `shared/src/hca_validation/schema/generated/core.py`

The edit tools should read from these sources, not duplicate them. This means:
- `hca-anndata-tools` gains a dependency on `shared/` (or on the data dictionary JSON)
- Edit validation and post-hoc validation agree by construction — same schema, no drift
- When obs editing comes later (#236), the same schema drives both uns and obs validation
- These validation functions could also be used in a standalone h5ad validation step, independent of the vendored cellxgene validator

### Dependency approach: bundled generated Pydantic models

Bundle a copy of the generated Pydantic models file (`shared/src/hca_validation/schema/generated/core.py`) into `hca-anndata-tools`. This gives us real Pydantic validation for free — type checking, enum validation, required/optional — without depending on the full `shared/` package (which drags in LinkML, gspread, Google API client, etc.).

- **Self-contained** — publishable to PyPI, only adds `pydantic` as a dep (lightweight)
- **Real validation** — Pydantic models have typed fields, enums, `extra="forbid"`, `validate_assignment=True`
- **Kept in sync** — copy step when `make gen-schema` regenerates models from LinkML
- **Schema-aware introspection** — field metadata includes `annDataLocation` (uns vs obs), examples, descriptions — everything the tool needs to list fields and validate values

The generated `core.py` only imports `pydantic` and stdlib. No LinkML runtime needed.

**Note:** `ambient_count_correction` and `doublet_detection` live on bionetwork subclasses (`AdiposeDataset`, `GutDataset`, `MusculoskeletalDataset`), not base `Dataset`. The tool collects uns fields from base `Dataset` and all bionetwork subclasses, marking subclass-only fields as `bionetwork_only` in the registry.

## Architecture

- **Bundled schema**: `packages/hca-anndata-tools/src/hca_anndata_tools/schema/core.py` — copy of generated Pydantic models from `shared/`
- **Schema helpers**: `packages/hca-anndata-tools/src/hca_anndata_tools/schema/helpers.py` — introspect models to list uns fields, extract validation rules, check annDataLocation
- **Edit logic**: `packages/hca-anndata-tools/src/hca_anndata_tools/edit.py` — `set_uns()` and `list_uns_fields()` functions
- **MCP registration**: `packages/hca-anndata-mcp/src/hca_anndata_mcp/server.py`
- **Write path**: Uses existing `write_h5ad()` from `write.py`
