"""CLI entry point for the MCP server."""

import os


def run():
    # Read workers start as `python -m`, which puts the working directory first on
    # their sys.path; a module there would run in place of anyio or the standard library.
    os.environ["PYTHONSAFEPATH"] = "1"
    # Imported here, not at module level: anyio re-runs this entry script in every
    # read worker, and a worker needs only the tools it runs, not the server.
    from hca_anndata_mcp.server import mcp

    mcp.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    run()
