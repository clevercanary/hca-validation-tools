"""FastMCP server definition and tool registration."""

from fastmcp import FastMCP

from hca_anndata_tools import (
    get_summary,
    get_descriptive_stats,
    view_data,
    locate_files,
    get_storage_info,
    get_cap_annotations,
    set_uns,
    list_uns_fields,
)
from hca_anndata_mcp.tools.plot import plot_embedding_mcp

mcp = FastMCP(
    name="hca-anndata-mcp",
    instructions=(
        "Explore AnnData h5ad files interactively. "
        "Use locate_files to find files, get_summary for an overview, "
        "get_storage_info for HDF5 compression/chunk details, "
        "get_descriptive_stats for distributions, view_data to inspect raw values, "
        "plot_embedding to visualize UMAP/PCA embeddings, "
        "get_cap_annotations to inspect CAP cell annotation metadata, "
        "list_uns_fields to see HCA dataset metadata and what's missing, "
        "and set_uns to update HCA dataset metadata fields with schema validation."
    ),
)

mcp.tool()(get_summary)
mcp.tool()(get_storage_info)
mcp.tool()(get_descriptive_stats)
mcp.tool()(view_data)
mcp.tool()(locate_files)
mcp.tool()(plot_embedding_mcp)
mcp.tool()(get_cap_annotations)
mcp.tool()(list_uns_fields)
mcp.tool()(set_uns)
