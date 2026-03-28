# PRD: H5AD File Editing via MCP Server

**Status:** Draft
**Date:** 2026-03-27

## Problem

When curating h5ad files for HCA submission, wranglers need to make targeted edits (fix ontology terms, rename columns, drop invalid obs, etc.). Today this means writing ad-hoc Python scripts. We want the MCP server to support editing so Claude can make changes interactively — but we need safe file handling and change tracking.

## Goals

1. **Never modify the original file** — always write to a new timestamped copy
2. **Track what changed** — store a changelog inside the h5ad so the file is self-documenting
3. **Simple naming convention** — output filenames make it obvious which file is latest and what the lineage is

## File Naming Convention

**Rule:** Strip any existing timestamp suffix, append current UTC timestamp at write time.

```
Input:  AlZaim_2024_reprocessed-r1-wip-5.h5ad
Output: AlZaim_2024_reprocessed-r1-wip-5-2026-03-27-13-54-26.h5ad

Input:  AlZaim_2024_reprocessed-r1-wip-5-2026-03-27-13-54-26.h5ad
Output: AlZaim_2024_reprocessed-r1-wip-5-2026-03-27-14-22-11.h5ad
```

- Timestamp is **UTC** (avoids timezone encoding complexity)
- Format: `YYYY-MM-DD-HH-MM-SS`
- Regex to strip existing suffix: `-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}(?=\.h5ad$)`
- Base name is stable across edits — you always know the lineage

## Changelog in `uns`

### Why track changes inside the file?

There is no community standard for changelog/provenance in AnnData (see [scanpy#472](https://github.com/scverse/scanpy/issues/472), open since 2019). Scanpy stores per-function params in `uns` but not a history log. CAP/CAS stores structured annotation provenance. LaminDB tracks lineage externally. We want something lightweight and self-contained.

### Context: what cellxgene already stores in `uns`

Cellxgene schema reserves these `uns` fields (set by the system post-upload, not by submitters):
- `schema_version`, `schema_reference`, `citation`

User-provided required fields: `title` (both cellxgene and HCA), `study_pi` (HCA only).

Cellxgene does **not** store filename, dataset_id, or file hash in `uns` — those live in their external catalog. Our edit log fills a gap that doesn't conflict with existing conventions.

### Proposed structure: `uns['hca_edit_log']`

A list of edit entries stored in `uns['hca_edit_log']`. Each entry is a dict:

```python
{
    "timestamp": "2026-03-27T13:54:26Z",       # UTC ISO 8601
    "tool": "hca-anndata-mcp",                  # What performed the edit
    "tool_version": "0.1.0",                    # Version of the tool
    "operation": "set_obs",                      # Operation type
    "description": "Fix disease_ontology_term_id for 23 obs from MONDO:0000001 to MONDO:0005015",
    "details": {                                 # Operation-specific structured data
        "column": "disease_ontology_term_id",
        "old_value": "MONDO:0000001",
        "new_value": "MONDO:0005015",
        "affected_rows": 23
    },
    "source_file": "AlZaim_2024_reprocessed-r1-wip-5.h5ad",
    "source_sha256": "a1b2c3d4..."               # SHA-256 hash of source file
}
```

### Design decisions

- **Append-only log**: Each write appends new entries. Previous entries from the source file are preserved.
- **Source identity**: Each entry records the source filename and its SHA-256 hash for traceability.
- **Serialization**: `uns` values must be JSON-serializable for h5ad storage. Lists of dicts work (anndata stores them as JSON strings in HDF5).
- **No external sidecar files**: The log lives in the h5ad so it travels with the file. If someone copies the file, they get the history.
- **Not a replacement for git**: This tracks data-level edits to the h5ad contents, not code changes.
- **No rollback**: To undo, re-edit from an earlier timestamped file. Every version is preserved on disk.
- **Log size**: Not a concern — even hundreds of entries are tiny compared to expression matrices.

## Architecture

### Write path (single method)

All edit operations flow through one `write_h5ad()` function in `hca-anndata-tools`:

```python
def write_h5ad(
    adata: AnnData,
    source_path: str,
    edit_entries: list[dict],
    output_dir: str | None = None,  # defaults to same dir as source
) -> dict:
    """
    Write adata to a new timestamped file. Appends edit_entries to uns['hca_edit_log'].

    Returns dict with 'output_path' on success, or 'error' on failure.
    """
```

1. Compute SHA-256 of source file on disk
2. Strip existing timestamp suffix from source filename
3. Generate new UTC timestamp
4. Populate `source_file` and `source_sha256` on each edit entry
5. Append `edit_entries` to `adata.uns['hca_edit_log']` (create if missing)
6. Write to `{base}-{timestamp}.h5ad`
7. Return the output path

### Edit tools (MCP layer)

Each edit tool in the MCP server:
1. Opens the file (read into memory — backed mode is read-only)
2. Performs the edit on the in-memory AnnData
3. Builds edit log entry(s) describing what changed
4. Calls `write_h5ad()` to persist

### Initial edit tool: `set_obs`

A single tool to update values in obs columns. Covers the most common curation task (fixing ontology terms, correcting metadata values). Additional edit tools can be added later as needed.

### `view_edit_log` tool

Read and return `uns['hca_edit_log']` for a given file. Useful for inspecting what edits have been applied.

## Tickets

- **write_h5ad**: Core write function with timestamped naming + edit log
- **set_obs**: MCP tool to update obs column values
- **view_edit_log**: MCP tool to inspect edit history
