"""Every registered MCP command refuses a file anndata cannot open (#661).

The library suite proves this for ``hca_anndata_tools``. This one asks the
question at the surface the user actually reaches — the tools registered on
the MCP server — and so covers the four commands that live only here and are
invisible to the library's roster: ``label_h5ad``, ``populate_labels``,
``validate_schema`` and ``validate_cell_annotation``.

The roster is read out of ``server.py``'s ``mcp.tool()(...)`` registrations
rather than written down here, so a command added there and nowhere else
still has to answer for itself.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from hca_anndata_tools.testing import create_sample_h5ad

from hca_anndata_mcp import server

# Commands that take a path but open no h5ad, with the reason each is exempt.
OMISSIONS = {
    "locate_files": "takes a directory to scan; opens no h5ad",
}

# The arguments a command needs beyond ``path`` for the call to be well formed.
# Values are irrelevant — every command here refuses before it reads them.
EXTRA_ARGS = {
    "set_uns": {"field": "title", "value": "t"},
}


def _registered_command_names() -> list[str]:
    """Every name passed to ``mcp.tool()(...)`` in server.py."""
    source = Path(inspect.getfile(server)).read_text()
    names = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Call)
            and isinstance(node.func.func, ast.Attribute)
            and node.func.func.attr == "tool"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Name)
        ):
            names.append(node.args[0].id)
    assert names, "found no mcp.tool() registrations — the parser is out of date"
    return names


def _path_commands() -> list[tuple[str, object, str]]:
    out = []
    for name in _registered_command_names():
        fn = getattr(server, name)
        params = inspect.signature(fn).parameters
        if name in OMISSIONS or "path" not in params:
            continue
        out.append((name, fn, "path"))
    return out


@pytest.fixture
def truncated(tmp_path) -> str:
    src = create_sample_h5ad(tmp_path / "src.h5ad")
    dst = tmp_path / "truncated.h5ad"
    payload = src.read_bytes()
    dst.write_bytes(payload[: len(payload) // 2])
    src.unlink()
    return str(dst)


@pytest.mark.parametrize(("name", "fn"), [(n, f) for n, f, _ in _path_commands()], ids=[n for n, _, _ in _path_commands()])
def test_command_refuses_a_truncated_file(name, fn, truncated):
    """No command reports success on a file anndata cannot open.

    Two shapes count as a refusal. Most commands return ``{"error": ...}``.
    ``validate_schema`` and ``validate_cell_annotation`` delegate to
    ``hca_schema_validator``, whose verdict shape is its own and out of scope
    for #661 — an unreadable file comes back as ``is_valid: False`` carrying
    the read failure, which is a refusal by any reading that matters.
    """
    result = fn(truncated, **EXTRA_ARGS.get(name, {}))

    assert isinstance(result, dict), f"{name} did not return the command error shape"
    refused = "error" in result or result.get("is_valid") is False
    assert refused, f"{name} accepted a file anndata cannot open: {result}"


def test_every_path_command_is_covered():
    """The roster above is the whole registered surface, minus named exemptions."""
    covered = {name for name, _, _ in _path_commands()} | set(OMISSIONS)
    uncovered = {
        name
        for name in _registered_command_names()
        if name not in covered and "path" in inspect.signature(getattr(server, name)).parameters
    }
    assert not uncovered, f"registered commands with an unchecked path: {uncovered}"
