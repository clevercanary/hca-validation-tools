"""CLI entry point for the MCP server."""

from hca_anndata_mcp.server import mcp


def run():
    mcp.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    run()
