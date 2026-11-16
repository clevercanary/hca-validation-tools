# hca-anndata-mcp

MCP server for interactive exploration of AnnData h5ad files.

## Usage

```bash
# Run the MCP server
hca-anndata-mcp
```

Point an MCP client at the venv binary directly, not at a wrapper command:

```json
{
  "mcpServers": {
    "hca-anndata-mcp": {
      "command": "/abs/path/to/packages/hca-anndata-mcp/.venv/bin/hca-anndata-mcp"
    }
  }
}
```

`uv run hca-anndata-mcp` (like `poetry run` before it) does not work here. An MCP
client needs a stable executable to spawn, and a wrapper command that resolves
and syncs an environment first is not one.

### Parallel reads

Read tools run in worker processes, in two lanes, so a quick read never waits
behind a read that takes minutes. Three settings, checked at startup:

| Variable | Default | Meaning |
| --- | --- | --- |
| `HCA_ANNDATA_MCP_READ_WORKERS` | `16` | N, the reads that run at once; at least 2 |
| `HCA_ANNDATA_MCP_SLOW_WORKERS` | N ÷ 2, rounded down | S, how many of them may be slow reads (whole-file loads, full matrix passes and folder scans); 1 to N - 1 |
| `HCA_ANNDATA_MCP_RETIRE_GIB` | `3` | a worker left holding more than this many GiB after a read exits |

Each slow read can hold a whole file in memory, so size S to the machine.
Write tools run one at a time, and never while a read in the same server is
running. The rules, and which tools are slow, are in
`docs/anndata-mcp-concurrency-contract.md`.

## Tools

- **locate_files** — Find all .h5ad files in a directory
- **get_summary** — Structural overview: cell/gene counts, columns, embeddings, layers
- **get_storage_info** — HDF5 compression, chunking, sparse format details
- **get_descriptive_stats** — Descriptive statistics and value counts for obs/var columns
- **view_data** — View slices of any attribute (obs, var, X, obsm, uns, etc.)
- **plot_embedding** — UMAP/PCA scatter plots colored by obs column or gene
- **get_cap_annotations** — Inspect CAP cell annotation metadata, marker genes, rationale
