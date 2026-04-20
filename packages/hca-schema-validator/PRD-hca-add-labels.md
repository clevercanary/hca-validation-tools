# PRD: HCA Add-Labels

## Background

HCA producers ship integrated h5ad files with inconsistent var/obs layouts:

- Some use `gene_symbol` (gut-v1, breast); some use `feature_name` (adipose); some ship neither.
- Some pre-populate obs labels (gut-v1 has `tissue`, `assay`, `disease`, `organism`); others don't.
- Some carry `_ontology_term` (no `_id`) columns that aren't part of any public schema.
- Pre-populated labels drift from their `_ontology_term_id` source (gut-v1 myeloid: `disease` has 5 uniques vs `disease_ontology_term` 7).

Downstream consumers — CAP marker validation, CELLxGENE Explorer, `hca-schema-validator` — read the canonical post-labels layout: `var['feature_name']` for gene symbols, and bare `obs['tissue']` / `obs['cell_type']` / ... for ontology labels. Without a single labeling step each atlas needs per-file workarounds.

CELLxGENE's vendored `cellxgene-schema add-labels` almost does what we need but:

1. Is bound to the CELLxGENE schema (requires `uns['organism_ontology_term_id']`, injects `uns['schema_version']` / `uns['schema_reference']` that HCA does not want).
2. Raises `ValueError: None not supported` on any Ensembl ID it cannot map to a supported organism. We routinely see files with deprecated IDs (1,069 / 35,574 in gut-v1 myeloid).
3. Silently preserves pre-existing obs/var label columns, so producer drift is never corrected.

## Workflow positioning

**Recommendation:** run the HCA labeler before handing a file to CAP, as part of the post-curate, pre-handoff pass.

**Reasoning:**

1. CAP annotators search genes by symbol (e.g. `CD3E`) in their curation UI. The UI reads `var['feature_name']`. Without that column populated, annotators are stuck searching by Ensembl ID or relying on whatever custom column the producer chose (`gene_symbol`, none, ...). Running the labeler first gives every CAP user the same gene-symbol experience regardless of atlas.

2. When CAP returns the annotated file, `copy_cap_annotations` runs `validate_marker_genes` against `var['feature_name']`. `feature_name` must exist by that point anyway — generating it before CAP means annotator-provided marker symbols are matched against the exact same gene symbols CAP's UI showed during curation.

3. It establishes a single source of truth (`feature_name`) for symbols across all atlases before any downstream tool needs to read them, avoiding per-atlas fallback logic.

**Not strictly required.** CAP likely accepts files without `feature_name` (falling back to Ensembl IDs or producer-supplied `gene_symbol`), and the labeler could run after CAP return instead. The workflow placement above is a UX and consistency choice, not a schema requirement.

## Goals

1. Populate `var['feature_name']` + `feature_reference` / `feature_biotype` / `feature_length` / `feature_type` from the Ensembl IDs in `var.index`, using the GENCODE tables already vendored in `hca-schema-validator`.
2. Populate obs labels (`tissue`, `cell_type`, `assay`, `disease`, `sex`, `organism`, `development_stage`, `self_reported_ethnicity`) from their `_ontology_term_id` counterparts. Stale or drifted pre-existing values MUST be replaced.
3. Tolerate Ensembl IDs that GENCODE does not recognize — set the derived columns to NaN for those rows and continue.
4. Run as a minimal **patch over** the vendored CELLxGENE labeler. Do not edit the vendored code; subclass `AnnDataLabelAppender` from outside `_vendored/`.
5. Produce an HCA-clean file: do not inject CELLxGENE-only `uns` keys (`schema_version`, `schema_reference`).
6. Be callable from `/curate-h5ad` (via the MCP wrapper) as an approval-gated mechanical fix. The labeler itself is unconditional; the approval UX lives in the caller.

## Non-goals

- Bumping the bundled GENCODE release or supporting overlay updates for gene tables — out of scope for v0.
- IDTrack integration / remapping deprecated Ensembl IDs — out of scope.
- Generating `feature_is_filtered` from matrix sparsity. Required input; already validated. Producer sets it.
- Preserving prior values of overwritten columns in sidecar `<col>_original` columns. Dropped outright; when the labeler is invoked via the MCP wrapper, the MCP's edit-log entry captures the fact that an overwrite happened.

## Functional requirements

### R1. var labeling

- Read `var.index` as Ensembl feature IDs.
- For each ID:
  - If the ID is in vendored GENCODE → populate `feature_name`, `feature_reference`, `feature_biotype`, `feature_length`, `feature_type`.
  - If not → set all five columns to NaN for that row. No error.
- Mirror the same five columns to `raw.var` using the raw var index (matches CELLxGENE schema convention).
- If any of the five columns already exists: **overwrite** unconditionally.

### R2. obs labeling

- For each labeled field in the HCA schema (`cell_type`, `assay`, `disease`, `organism`, `sex`, `development_stage`, `self_reported_ethnicity`, `tissue`):
  - Read `obs['<field>_ontology_term_id']` (required input).
  - Write the human-readable label to `obs['<field>']` via `ONTOLOGY_PARSER`.
- If `obs['<field>']` already exists: **overwrite** unconditionally.
- If `obs['<field>_ontology_term_id']` is missing entirely, behavior depends on the field's `requirement_level` in `hca_schema_definition.yaml`:
  - **Default (required):** preflight raises `ValueError` (see R7) — the file is malformed.
  - **`optional` or `strongly_recommended`:** the labeler skips that field silently. The derived `obs['<field>']` column is not written. Currently only `cell_type_ontology_term_id` is marked optional.
- Write `obs['observation_joinid']` — a per-cell hash used for dataset deduplication at Discover ingest. Computed via `cellxgene_schema.utils.get_hash_digest_column(adata.obs)` from the vendored module (same source CELLxGENE uses). Overwrites if already present.

### R3. Scope: derived fields only

The labeler touches **only** the columns it derives:
- `var['feature_name']`, `var['feature_reference']`, `var['feature_biotype']`, `var['feature_length']`, `var['feature_type']` (and their `raw.var` mirrors)
- `obs['tissue']`, `obs['cell_type']`, `obs['assay']`, `obs['disease']`, `obs['sex']`, `obs['organism']`, `obs['development_stage']`, `obs['self_reported_ethnicity']`
- `obs['observation_joinid']`

All other columns and all `uns` keys are left untouched. The labeler does not write to `uns` at all. Decisions about extra/drift columns belong outside this tool.

### R4. uns handling

The labeler does **not** write to `uns` at all. It does not mirror organism from obs to uns, does not add CELLxGENE schema keys, and does not maintain any provenance entries.

- Edit-log / provenance is the MCP wrapper's responsibility (R6), triggered by `label_h5ad` — not the labeler's.
- If the caller needs `uns['organism_ontology_term_id']` populated for CELLxGENE-v7 tooling, the caller sets it before or after invoking the labeler. HCA canonical location is `obs`.

### R5. Overwrite behavior

The labeler overwrites the fields listed in R3 unconditionally. No bookkeeping, no approval hooks, no `plan_*` API — that coupling belongs in the caller, not the labeler.

Any UX around surfacing overwrites (showing the wrangler "these columns are about to change") is the caller's job. `/curate-h5ad` already knows the file state and the labeler's controlled field list (from this PRD), so it can render the diff on its own before invoking the labeler.

### R6. Entry points and package boundaries

The labeler lives entirely in `hca-schema-validator`. `hca-anndata-tools` is not modified. The MCP server (which depends on both packages) provides the edit-snapshot + provenance-logging wrapper.

| Layer | Owns | Knows about |
|---|---|---|
| `hca-schema-validator` | `HCALabeler` class (subclass of vendored `AnnDataLabelAppender`). Python API only. Returns a labeled `AnnData` or writes to an explicit output path. | Schema, GENCODE tables, vendored CELLxGENE labeler. Nothing about edit snapshots or `uns['provenance']`. |
| `hca-anndata-tools` | — (unchanged) | — |
| MCP server (`hca-anndata-mcp`) | `label_h5ad` tool: resolve latest input → call validator's labeler API → write edit snapshot (`<stem>-edit-<ts>.h5ad`) → append to `uns['provenance']['edit_history']`. | Edit-log + snapshot convention (via its existing dep on `hca-anndata-tools`). |

**Python API** — in `hca_schema_validator.labeler` (module name TBD). Sketch:

```python
class HCALabeler(AnnDataLabelAppender):
    def write_labels(self, out_path: str): ...   # overrides base; applies HCA behavior
```

No CLI. Invocation is via the MCP `label_h5ad` tool (interactive curation) or direct Python import (tests, ad-hoc scripts).

Rationale: keeps the validator package free of any dep on `hca-anndata-tools` (which would be a reverse layering). All user-visible labeling happens through the MCP tool, which owns the edit-log + snapshot conventions.

### R7. Preflight validation

Before any labeling work, `write_labels` runs a preflight that raises a single `ValueError` (aggregating all issues) if any of the following hold:

- A **required** obs column referenced by an `add_labels` directive in the HCA schema is missing — e.g. `obs['organism_ontology_term_id']` isn't present. Columns whose `requirement_level` is `optional` or `strongly_recommended` (currently just `cell_type_ontology_term_id`) are allowed to be absent; the labeler skips the corresponding derived field instead of failing.
- `uns['schema_version']` is present — signals the file has already been processed by `cellxgene-schema add-labels`; running HCALabeler on top would produce a mess.
- `uns['schema_reference']` is present — same reason.
- `obs['organism_ontology_term_id']` contains any value other than `NCBITaxon:9606` — HCALabeler supports only human (see R1 rationale). Adding another organism is a deliberate code change.

The labeler does not validate or modify `uns['organism_ontology_term_id']` or `uns['organism']` (label-form) — those keys are producer-owned. Similarly, the labeler does not scrub stale CELLxGENE keys beyond refusing to run; that cleanup belongs in upstream tooling or a separate utility.

## Design

### Patch, do not modify

The vendored CELLxGENE code lives at `packages/hca-schema-validator/src/hca_schema_validator/_vendored/cellxgene_schema/`. The labeler's entry class is `AnnDataLabelAppender` in `_vendored/cellxgene_schema/write_labels.py`.

Implementation strategy — subclass `AnnDataLabelAppender` from a **new** module outside `_vendored/` and override only what needs HCA behavior:

| Override / new | Reason |
|---|---|
| `__init__` | Load `hca_schema_definition.yaml` instead of CELLxGENE's schema definition. |
| `_get_mapping_dict_feature_id` | Wrap the GENCODE lookup so unknown-organism IDs yield NaN instead of raising. |
| `_get_mapping_dict_feature_reference` / `_biotype` / `_length` / `_type` | Same NaN-on-unknown behavior. |
| `_add_column` | Silently skip when the source column is absent from the target dataframe (handles optional `_ontology_term_id` columns like `cell_type`). Preflight catches required-missing before we get here. |
| `write_labels` | Skip the CELLxGENE-only `uns['schema_version']`, `uns['schema_reference']`, `uns['organism']` writes. Run `_preflight` first, then apply labels and the `observation_joinid` write (R2). No uns writes. |
| `_preflight` (new method) | Aggregated precondition check; see R7. |

The vendored code stays byte-identical. Future upstream bumps pull cleanly.

### Schema source

Use `hca_schema_definition.yaml` as-is. It already contains `add_labels` directives on the right fields (var index at lines 79, 110, and obs ontology fields at lines 203, 218, 245, 326, 467, 531, 708, 855). No YAML changes needed for v0.

### Edge cases

| Input state | Behavior |
|---|---|
| Ensembl ID in `var.index` not in GENCODE | All five `feature_*` columns NaN for that row. |
| `obs['<field>_ontology_term_id']` absent (required field) | Preflight raises `ValueError` (R7); nothing is written. |
| `obs['cell_type_ontology_term_id']` absent (optional field) | `obs['cell_type']` is not added; other labels are written normally. |
| `uns['schema_version']` or `uns['schema_reference']` already set | Preflight raises `ValueError` (R7); nothing is written. |
| `obs['organism_ontology_term_id']` contains any non-human value | Preflight raises `ValueError` (R7); nothing is written. |
| `var['feature_is_filtered']` absent | Do not generate. Existing `feature_is_filtered` validator catches this as a downstream error. |
| `raw.var` absent | Skip raw-var labeling. Label only `var`. |
| Existing `var['feature_name']` populated | Overwrite. |

## Open questions

_(none currently)_

## Success criteria

Running the HCA labeler on gut-v1 myeloid (post-curate) produces a file where:

- `var['feature_name']` is populated for 34,505 / 35,574 rows and NaN for the 1,069 deprecated IDs.
- `obs` labels (`tissue`, `cell_type`, `assay`, `disease`, `sex`, `organism`, `development_stage`, `self_reported_ethnicity`) are populated from their `_ontology_term_id` inputs, overwriting the producer-drifted versions.
- `obs['observation_joinid']` is present.
- `uns` is unchanged by the labeler. The labeler refuses to run on inputs that carry `uns['schema_version']` or `uns['schema_reference']` (preflight), but if those pass and any other `uns` keys exist on input they pass through untouched. The caller (or a subsequent tool) is responsible for any desired `uns['organism_ontology_term_id']` duplication for CELLxGENE-v7 tooling.
- Producer `*_ontology_term` drift columns and custom columns like `gene_symbol` are untouched (the labeler does not drop them; that decision lives in `/curate-h5ad`).
- `hca-schema-validator` introduces no new errors from labeling. The two pre-existing errors (`library_id` NaN, `library_preparation_batch` delimited lists) remain — they are independent Bucket C items unrelated to labeling.
- CAP marker validation finds 54 / 56 markers in `var['feature_name']` (matching what we observed in yesterday's scratch experiment).
