"""FastMCP server definition and tool registration."""

from fastmcp import FastMCP

from hca_anndata_mcp.tools.summary import get_summary
from hca_anndata_mcp.tools.stats import get_descriptive_stats
from hca_anndata_mcp.tools.view import view_data
from hca_anndata_mcp.tools.files import locate_files
from hca_anndata_mcp.tools.storage import get_storage_info
from hca_anndata_mcp.tools.plot import plot_embedding
from hca_anndata_mcp.tools.cap import get_cap_annotations

mcp = FastMCP(
    name="hca-anndata-mcp",
    instructions=(
        "Explore AnnData h5ad files interactively. "
        "Use locate_files to find files, get_summary for an overview, "
        "get_storage_info for HDF5 compression/chunk details, "
        "get_descriptive_stats for distributions, view_data to inspect raw values, "
        "plot_embedding to visualize UMAP/PCA embeddings, "
        "and get_cap_annotations to inspect CAP cell annotation metadata."
    ),
)

mcp.tool()(get_summary)
mcp.tool()(get_storage_info)
mcp.tool()(get_descriptive_stats)
mcp.tool()(view_data)
mcp.tool()(locate_files)
mcp.tool()(plot_embedding)
mcp.tool()(get_cap_annotations)
