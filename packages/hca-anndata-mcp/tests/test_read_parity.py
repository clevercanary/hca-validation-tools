"""Each read tool returns the same result through a worker process as called in this one."""

import json

import pytest
from pydantic_core import to_jsonable_python

from hca_anndata_mcp.server import mcp, registrar


def _read_args(sample_h5ad, sample_dir) -> dict[str, dict]:
    path = str(sample_h5ad)
    args: dict[str, dict[str, object]] = {
        name: {"path": path} for name, kind in registrar.kinds.items() if kind == "read"
    }
    args["locate_files"] = {"directory": str(sample_dir)}
    args["check_cap_currency"] = {"path": path, "cap_url": "https://celltype.info/project/1"}
    args["validate_schema"] = {"path": path, "object_kind": "integrated"}
    args["get_descriptive_stats"] = {"path": path, "attribute": "obs", "value_counts": True}
    return args


def _canonical(result) -> str:
    return json.dumps(to_jsonable_python(result), sort_keys=True)


@pytest.mark.asyncio
async def test_reads_return_the_same_through_a_worker(sample_h5ad, sample_dir):
    # On this file validate_marker_genes, find_source_datasets, check_cap_currency
    # and check_source_obs return only an error, so for them this compares errors.
    tools = await mcp.get_tools()
    args = _read_args(sample_h5ad, sample_dir)
    assert len(args) == 22
    for name, kwargs in args.items():
        fn = tools[name].fn
        direct = fn.__wrapped__(**kwargs)
        through_worker = await fn(**kwargs)
        assert _canonical(through_worker) == _canonical(direct), name
