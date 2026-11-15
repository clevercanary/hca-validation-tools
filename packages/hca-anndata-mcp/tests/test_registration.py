"""Every tool is labelled, and the label changes nothing a client sees."""

import pytest
from fastmcp.tools.tool import FunctionTool

from hca_anndata_mcp.server import mcp, registrar

WRITES = {
    "set_uns",
    "set_producer_uns",
    "convert_cellxgene_to_hca",
    "strip_forbidden_obs_columns",
    "drop_obs_columns",
    "merge_obs_categories",
    "rename_obs_column",
    "rename_cell_ids",
    "backfill_obs_from_source",
    "copy_cap_annotations",
    "strip_cap_annotations",
    "replace_placeholder_values",
    "compress_h5ad",
    "normalize_raw",
    "set_source_dataset",
    "label_h5ad",
    "populate_labels",
}


@pytest.mark.asyncio
async def test_every_registered_tool_is_labelled():
    assert set(registrar.tools) == set(await mcp.get_tools())
    assert len(registrar.tools) == 39


def test_write_set_is_the_seventeen_writes():
    assert {name for name, tool in registrar.tools.items() if tool.kind == "write"} == WRITES


@pytest.mark.asyncio
async def test_wrapped_tools_list_as_the_bare_functions_do():
    for name, tool in (await mcp.get_tools()).items():
        bare = FunctionTool.from_function(registrar.tools[name].fn)
        assert tool.to_mcp_tool().model_dump() == bare.to_mcp_tool().model_dump(), name
