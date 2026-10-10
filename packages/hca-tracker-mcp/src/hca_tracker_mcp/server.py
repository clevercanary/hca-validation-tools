"""FastMCP server definition and tool registration."""

from fastmcp import FastMCP

from hca_tracker_mcp.tools import (
    cancel_download,
    check_environment,
    delete_download,
    download_status,
    get_atlas,
    get_validation_report,
    list_atlases,
    list_downloads,
    list_integrated_objects,
    list_source_datasets,
    plan_upload,
    start_download,
    start_upload,
    upload_status,
)

mcp = FastMCP(
    name="hca-tracker-mcp",
    instructions=(
        "Find, download, upload and report on atlas files from the HCA Atlas Tracker. "
        "Every atlas-scoped tool needs both network and atlas (the slug); find the pair with list_atlases, "
        "never guess it — the same slug can exist in several networks. "
        "list_integrated_objects and list_source_datasets list an atlas version's files with each file's "
        "validation summary, CAP ingest status and HCA Tier 1 status "
        "(default: newest revision of the highest generation; pass generation or published to choose). "
        "get_atlas gives the atlas record: status, integration leads with their tracker account and last login, "
        "counts, ingestion tasks. get_validation_report gives one file's validator error and warning messages, "
        "capped per list; it takes the entry_id and kind from the file's list row. "
        "start_download checks, then starts a background download and returns a job_id at once; "
        "poll download_status for progress — downloads can take hours and continue after this session. "
        "Downloaded files are local paths that hca-anndata-mcp tools can open. "
        "To put a curated file back: stage it in a folder of its own, plan_upload to see what would go where "
        "(no side effects), start_upload to run it in a detached job, upload_status until done; the tracker "
        "then ingests it from the bucket and lists it with a new wip_number, and get_validation_report gives "
        "its verdict. environment defaults to dev and must match the configured tracker; the AWS profile comes "
        "from hca-smart-sync's own settings. "
        "check_environment diagnoses setup problems (aria2c, cache folder, token, s5cmd/aws, AWS profile, bucket)."
    ),
)

mcp.tool()(list_atlases)
mcp.tool()(list_integrated_objects)
mcp.tool()(list_source_datasets)
mcp.tool()(get_atlas)
mcp.tool()(get_validation_report)
mcp.tool()(start_download)
mcp.tool()(download_status)
mcp.tool()(cancel_download)
mcp.tool()(list_downloads)
mcp.tool()(delete_download)
mcp.tool()(plan_upload)
mcp.tool()(start_upload)
mcp.tool()(upload_status)
mcp.tool()(check_environment)
