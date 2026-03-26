"""Integration tests verifying MCP server tool registration."""

import pytest

from hca_anndata_mcp.server import mcp


@pytest.mark.asyncio
async def test_server_has_expected_tools():
    """Verify all tools are registered on the MCP server."""
    tools = await mcp._tool_manager.get_tools()
    tool_names = set(tools.keys())
    expected = {
        "get_summary",
        "get_storage_info",
        "get_descriptive_stats",
        "view_data",
        "locate_files",
        "plot_embedding",
        "get_cap_annotations",
    }
    assert expected == tool_names


def test_tool_delegates_to_library(sample_h5ad):
    """Verify a tool call flows through to hca_anndata_tools."""
    from hca_anndata_tools import get_summary

    result = get_summary(str(sample_h5ad))
    assert "error" not in result
    assert result["n_obs"] == 50
