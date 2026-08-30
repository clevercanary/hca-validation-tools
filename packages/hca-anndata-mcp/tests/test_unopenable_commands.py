"""Every registered MCP command refuses a file anndata cannot open (#661).

The library suite proves this for ``hca_anndata_tools``. This one asks the
question at the surface a user actually reaches — the tools registered on the
MCP server — which sees two things the library roster cannot: commands that
exist only here, and re-exports that later grow a wrapper of their own.

Most commands *are* the library functions: ``server.get_storage_info is
hca_anndata_tools.get_storage_info``, because the ``tools/*.py`` modules are
pure re-exports. Re-running the library's assertions against the same object
proves nothing, so the behavioural check below covers only the commands whose
code differs. The test is by identity, so a re-export that stops being one
starts being checked here automatically.

The roster comes from the running server rather than a list here, so a command
registered and forgotten still has to answer for itself.
"""

from __future__ import annotations

import asyncio
import functools
import inspect

import pytest

import hca_anndata_tools
from hca_anndata_mcp import server
from hca_anndata_tools.testing import create_truncated_h5ad


@functools.cache
def _registered() -> dict[str, object]:
    """Every command the server actually registered, by name.

    Asked of the server rather than parsed out of its source, so a
    registration written any other way still counts. Resolved through the
    tool's own callable, not ``getattr`` on the module: a command can be
    registered under a name that is not its attribute name
    (``plot_embedding_mcp`` registers as ``plot_embedding``), and a getattr
    lookup drops exactly those silently.
    """
    tools = asyncio.run(server.mcp.get_tools())
    assert tools, "the server registered no tools"
    return {name: tool.fn for name, tool in tools.items()}


def _path_params(fn) -> set[str]:
    """Parameters that look like a file path, by name alone.

    Deliberately not ``GATED_PATH_PARAMS``: selecting with the same constant
    the gate selects with would let a command declaring ``h5ad_path`` be
    defined out of existence rather than flagged. Same argument as
    ``test_unopenable.py::test_every_public_path_is_gated_or_named``.
    """
    return {p for p in inspect.signature(fn).parameters if "path" in p.lower()}


def _mcp_only() -> list[tuple[str, object]]:
    """Registered commands whose code is not simply a library function."""
    return sorted(
        (name, fn)
        for name, fn in _registered().items()
        if _path_params(fn) and getattr(hca_anndata_tools, name, None) is not fn
    )


MCP_ONLY = _mcp_only()


@pytest.fixture
def truncated(tmp_path) -> str:
    return str(create_truncated_h5ad(tmp_path / "truncated.h5ad"))


@pytest.mark.parametrize(("name", "fn"), MCP_ONLY, ids=[n for n, _ in MCP_ONLY])
def test_mcp_only_command_refuses_a_truncated_file(name, fn, truncated):
    """No command of our own reports success on a file anndata cannot open.

    Two shapes count as a refusal. Most commands return ``{"error": ...}``.
    ``validate_schema`` and ``validate_cell_annotation`` delegate to
    ``hca_schema_validator``, whose verdict shape is its own and out of scope
    for #661 — an unreadable file comes back as ``is_valid: False`` carrying
    the read failure, which is a refusal by any reading that matters.
    """
    result = fn(path=truncated)

    assert isinstance(result, dict), f"{name} did not return the command error shape"
    refused = "error" in result or result.get("is_valid") is False
    assert refused, f"{name} accepted a file anndata cannot open: {result}"


def test_every_registered_path_command_is_accounted_for():
    """The roster is the running server's, and every path command is on it.

    ``covered`` is the union of the cases above and the names that come from
    the library, whose own suite governs them — so a command that is neither,
    a new wrapper or a path-taking command from nowhere, makes this fail.
    """
    library_names = set(hca_anndata_tools.__all__)
    covered = {name for name, _ in MCP_ONLY} | library_names

    uncovered = {name for name, fn in _registered().items() if name not in covered and _path_params(fn)}
    assert not uncovered, f"registered commands with an unchecked path: {uncovered}"
