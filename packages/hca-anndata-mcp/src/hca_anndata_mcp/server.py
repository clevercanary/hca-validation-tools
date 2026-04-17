"""FastMCP server definition and tool registration."""

from fastmcp import FastMCP
from hca_anndata_tools import (
    compress_h5ad,
    convert_cellxgene_to_hca,
    copy_cap_annotations,
    get_cap_annotations,
    get_descriptive_stats,
    get_storage_info,
    get_summary,
    check_x_normalization,
    list_uns_fields,
    locate_files,
    normalize_raw,
    replace_placeholder_values,
    set_uns,
    validate_marker_genes,
    view_data,
    view_edit_log,
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
        "set_uns to update HCA dataset metadata fields with schema validation, "
        "convert_cellxgene_to_hca to convert CellxGENE files to HCA format, "
        "validate_marker_genes to check CAP marker genes against var, "
        "copy_cap_annotations to copy CAP annotations from a source into an HCA target file, "
        "replace_placeholder_values to replace banned placeholder values with NaN in obs columns, "
        "compress_h5ad to rewrite a file with HDF5 gzip compression applied, "
        "normalize_raw to move raw counts from X to raw.X and normalize X "
        "(normalize_total + log1p), "
        "check_x_normalization to classify X as raw-counts / normalized / indeterminate, "
        "and view_edit_log to inspect the edit history recorded in a file."
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
mcp.tool()(convert_cellxgene_to_hca)
mcp.tool()(validate_marker_genes)
mcp.tool()(copy_cap_annotations)
mcp.tool()(replace_placeholder_values)
mcp.tool()(compress_h5ad)
mcp.tool()(normalize_raw)
mcp.tool()(view_edit_log)
mcp.tool()(check_x_normalization)
