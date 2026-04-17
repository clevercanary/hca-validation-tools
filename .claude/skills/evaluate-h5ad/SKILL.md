---
name: evaluate-h5ad
description: Evaluate an h5ad file for HCA readiness — checks metadata, compression, embeddings, CAP annotations, and edit history.
argument-hint: <absolute-path-to-h5ad-file>
---

# Evaluate H5AD File

Evaluate the h5ad file at absolute path: `$ARGUMENTS`

Pass an absolute path to the `.h5ad` file. Relative paths are resolved against the MCP server's working directory, which may not match the user's, so they can silently evaluate the wrong file.

Run all of the following MCP tool calls in parallel to gather data:

1. **get_summary** — cell/gene counts, obs/var columns, uns keys, layers, obsm
2. **get_storage_info** — compression, chunking, sparse format, file size
3. **check_schema_type** — report CellxGENE vs HCA layout and schema version
4. **check_x_normalization** — classify X as raw_counts / normalized / indeterminate
5. **list_uns_fields** — HCA schema field completeness (required vs set vs missing)
6. **get_cap_annotations** — CAP cell annotation sets, if present
7. **get_descriptive_stats** with `columns: ["cell_type_ontology_term_id", "author_cell_type", "cell_type"]` and `value_counts: true` — cell type annotation distributions
8. **view_edit_log** — read `uns/provenance/edit_history` so edit history is already in hand when synthesizing the report

Then synthesize the results into a report covering:

## 1. File Overview
- Cell count, gene count, file size
- Organism, title
- Schema type + version (from `check_schema_type`: CellxGENE or HCA)
- X matrix verdict (from `check_x_normalization`: raw_counts / normalized / indeterminate, and whether raw.X is present)

## 2. HCA Metadata Readiness
- How many required HCA uns fields are set vs missing?
- List each missing required field by name
- Note any bionetwork-only fields that are missing
- Flag any extra uns keys not in the HCA schema

## 3. Storage & Compression
- Is X compressed? What codec and compression level?
- Is raw/X present and compressed?
- Are chunks reasonable for the matrix dimensions?
- Flag any uncompressed datasets in a large file

## 4. Embeddings
- Which obsm keys exist (UMAP, PCA, scVI, etc.)?
- Is `default_embedding` set in uns? Does it match an obsm key?

## 5. CAP Annotations
- Are CAP annotation sets present?
- If yes: how many sets, how many cell labels, do they have ontology mappings?
- If no: note that CAP annotations are missing

## 6. Cell Type Annotation Concordance
- Build a table mapping each `cell_type_ontology_term_id` to its `cell_type` (ontology label) and `author_cell_type` values, with cell counts
- **Flag any mismatches** where the author cell type is semantically inconsistent with the ontology term — e.g. a vascular cell type mapped to an epithelial ontology term, or vice versa
- Note where author types are more specific than the ontology (this is normal and fine)
- Note where multiple author types map to the same ontology term (may indicate the ontology term is too broad)
- If any columns are missing, note which are absent and skip this section

## 7. Edit History
- Use the `view_edit_log` result fetched in Step 1.
- If entries are present: summarize recent edits (who/what/when)
- If absent: note that no edit history exists (file hasn't been edited through hca-anndata-tools)

## 8. Summary & Recommendations
- Overall HCA readiness: ready / needs work / not started
- Prioritized list of what to fix, most important first
- If `check_schema_type` reported `cellxgene`, recommend `convert_cellxgene_to_hca` as the first fix.
