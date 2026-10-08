"""FastMCP server definition and tool registration."""

from fastmcp import FastMCP

from hca_tracker_mcp.tools import (
    cancel_download,
    check_environment,
    delete_download,
    download_status,
    list_atlases,
    list_downloads,
    list_integrated_objects,
    list_source_datasets,
    start_download,
)

mcp = FastMCP(
    name="hca-tracker-mcp",
    instructions=(
        "Find and download atlas files from the HCA Atlas Tracker (read-only). "
        "Every atlas-scoped tool needs both network and atlas (the slug); find the pair with list_atlases, "
        "never guess it — the same slug can exist in several networks. "
        "list_integrated_objects and list_source_datasets list an atlas version's files "
        "(default: newest revision of the highest generation; pass generation or published to choose). "
        "start_download checks, then starts a background download and returns a job_id at once; "
        "poll download_status for progress — downloads can take hours and continue after this session. "
        "Files above the size threshold need confirm=true: show the user the size and free space first. "
        "Downloaded files are local paths that hca-anndata-mcp tools can open. "
        "check_environment diagnoses setup problems (aria2c, cache folder, token)."
    ),
)

mcp.tool()(list_atlases)
mcp.tool()(list_integrated_objects)
mcp.tool()(list_source_datasets)
mcp.tool()(start_download)
mcp.tool()(download_status)
mcp.tool()(cancel_download)
mcp.tool()(list_downloads)
mcp.tool()(delete_download)
mcp.tool()(check_environment)
