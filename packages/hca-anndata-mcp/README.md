# hca-anndata-mcp

MCP server for interactive exploration of AnnData h5ad files.

## Usage

```bash
# Run the MCP server
hca-anndata-mcp

# Or via poetry
poetry run hca-anndata-mcp
```

## Tools

- **locate_files** — Find all .h5ad files in a directory
- **get_summary** — Structural overview: cell/gene counts, columns, embeddings, layers
- **get_storage_info** — HDF5 compression, chunking, sparse format details
- **get_descriptive_stats** — Descriptive statistics and value counts for obs/var columns
- **view_data** — View slices of any attribute (obs, var, X, obsm, uns, etc.)
- **plot_embedding** — UMAP/PCA scatter plots colored by obs column or gene
- **get_cap_annotations** — Inspect CAP cell annotation metadata, marker genes, rationale
