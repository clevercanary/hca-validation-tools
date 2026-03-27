"""End-to-end tests exercising all MCP tools through the FastMCP client."""

import json

import pytest
import pytest_asyncio
from fastmcp.client import Client

from hca_anndata_mcp.server import mcp


@pytest_asyncio.fixture
async def client():
    """Create a FastMCP client connected to the server."""
    async with Client(mcp) as c:
        yield c


async def _call(client, tool, args=None):
    """Call a tool and return the parsed JSON result."""
    result = await client.call_tool(tool, args or {})
    assert not result.is_error, f"{tool} returned error: {result.content}"
    text = result.content[0].text
    return json.loads(text)


@pytest.mark.asyncio
async def test_locate_files(client, sample_dir):
    data = await _call(client, "locate_files", {"directory": str(sample_dir)})
    assert data["total"] == 1
    assert data["h5ad"][0].endswith(".h5ad")


@pytest.mark.asyncio
async def test_get_summary(client, sample_h5ad):
    data = await _call(client, "get_summary", {"path": str(sample_h5ad)})
    assert data["n_obs"] == 50
    assert data["n_vars"] == 20
    obs_names = [c["name"] for c in data["obs_columns"]]
    assert "sex" in obs_names
    assert "cell_type" in obs_names
    obsm_keys = [k["key"] for k in data["obsm_keys"]]
    assert "X_umap" in obsm_keys
    assert "X_pca" in obsm_keys


@pytest.mark.asyncio
async def test_get_storage_info(client, sample_h5ad):
    data = await _call(client, "get_storage_info", {"path": str(sample_h5ad)})
    assert data["file_size_bytes"] > 0
    assert data["X"] is not None
    assert data["layers"]["raw_counts"] is not None


@pytest.mark.asyncio
async def test_get_descriptive_stats(client, sample_h5ad):
    data = await _call(client, "get_descriptive_stats", {
        "path": str(sample_h5ad),
        "attribute": "obs",
        "value_counts": True,
    })
    assert data["n_rows"] == 50
    assert data["columns"]["sex"]["type"] == "categorical"
    assert data["columns"]["sex"]["unique"] == 3
    assert "value_counts" in data["columns"]["sex"]
    assert data["columns"]["n_counts"]["type"] == "numeric"
    assert data["columns"]["n_counts"]["mean"] is not None


@pytest.mark.asyncio
async def test_get_descriptive_stats_with_filter(client, sample_h5ad):
    data = await _call(client, "get_descriptive_stats", {
        "path": str(sample_h5ad),
        "attribute": "obs",
        "filter_column": "sex",
        "filter_operator": "==",
        "filter_value": "female",
    })
    assert data["n_rows"] < 50


@pytest.mark.asyncio
async def test_view_data_obs(client, sample_h5ad):
    data = await _call(client, "view_data", {
        "path": str(sample_h5ad),
        "attribute": "obs",
        "row_end": 5,
    })
    assert data["type"] == "dataframe"
    assert data["slice_shape"] == [5, 4]
    assert data["full_shape"] == [50, 4]


@pytest.mark.asyncio
async def test_view_data_obsm(client, sample_h5ad):
    data = await _call(client, "view_data", {
        "path": str(sample_h5ad),
        "attribute": "obsm",
        "key": "X_umap",
        "row_end": 3,
    })
    assert data["type"] == "array"
    assert data["full_shape"] == [50, 2]
    assert data["slice_shape"] == [3, 2]


@pytest.mark.asyncio
async def test_view_data_uns(client, sample_h5ad):
    data = await _call(client, "view_data", {
        "path": str(sample_h5ad),
        "attribute": "uns",
    })
    assert data["type"] == "dict"
    assert data["data"]["title"] == "Test Dataset"


@pytest.mark.asyncio
async def test_get_cap_annotations(client, sample_h5ad):
    data = await _call(client, "get_cap_annotations", {"path": str(sample_h5ad)})
    assert data["has_cap_annotations"] is False
    assert data["annotation_sets"] == []


@pytest.mark.asyncio
async def test_plot_embedding(client, sample_h5ad):
    result = await client.call_tool("plot_embedding", {
        "path": str(sample_h5ad),
        "color": "cell_type",
        "embedding": "X_umap",
    })
    assert not result.is_error
    # plot_embedding returns ImageContent, not TextContent
    content = result.content[0]
    assert content.type == "image"
    assert content.mimeType == "image/png"
    assert len(content.data) > 100  # base64 PNG data


@pytest.mark.asyncio
async def test_error_handling(client):
    """Verify errors propagate cleanly through MCP."""
    data = await _call(client, "get_summary", {"path": "/nonexistent/file.h5ad"})
    assert "error" in data
