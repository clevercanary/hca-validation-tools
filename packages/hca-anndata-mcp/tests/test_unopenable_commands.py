"""Every registered MCP command refuses a file anndata cannot open (#661).

The library suite proves this for ``hca_anndata_tools``. This one asks the
question at the surface a user actually reaches — the tools registered on the
MCP server — which is where two gaps live that the library roster cannot see.

Most commands here *are* the library functions: ``server.get_storage_info is
hca_anndata_tools.get_storage_info``, because the ``tools/*.py`` modules are
pure re-exports. Re-running the library's assertions against the same object
proves nothing, so the behavioural check below covers only the commands whose
code differs — today ``plot_embedding_mcp``, ``validate_schema``,
``validate_cell_annotation``, ``label_h5ad`` and ``populate_labels``. The
identity test is mechanical, so a re-export that later grows a wrapper starts
being checked here automatically.

The roster comes from the running server rather than from a list here, so a
command registered and forgotten still has to answer for itself.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

import hca_anndata_tools
from hca_anndata_mcp import server
from hca_anndata_tools._io import GATED_PATH_PARAMS
from hca_anndata_tools.testing import create_sample_h5ad, create_truncated_h5ad

# Commands that take a path but open no h5ad, with the reason each is exempt.
OMISSIONS = {
    "locate_files": "takes a directory to scan; opens no h5ad",
}


def _registered() -> dict[str, object]:
    """Every command the server actually registered, by name.

    Asked of the server rather than parsed out of its source: a registration
    written any other way (a decorator, a loop, an alias) still counts.
    """
    tools = asyncio.run(server.mcp.get_tools())
    assert tools, "the server registered no tools"
    # Resolved through the tool's own callable, not getattr on the module: a
    # command can be registered under a name that is not its attribute name
    # (plot_embedding_mcp registers as "plot_embedding"), and a getattr lookup
    # drops exactly those silently.
    return {name: tool.fn for name, tool in tools.items()}


def _path_params(fn) -> set[str]:
    return {p for p in inspect.signature(fn).parameters if p in GATED_PATH_PARAMS}


def _mcp_only() -> list[tuple[str, object]]:
    """Registered commands whose code is not simply a library function."""
    return sorted(
        (name, fn)
        for name, fn in _registered().items()
        if name not in OMISSIONS and _path_params(fn) and getattr(hca_anndata_tools, name, None) is not fn
    )


MCP_ONLY = _mcp_only()


@pytest.fixture
def truncated(tmp_path) -> str:
    return str(create_truncated_h5ad(tmp_path / "truncated.h5ad"))


@pytest.fixture
def good(tmp_path) -> str:
    return str(create_sample_h5ad(tmp_path / "good.h5ad"))


@pytest.mark.parametrize(("name", "fn"), MCP_ONLY, ids=[n for n, _ in MCP_ONLY])
def test_mcp_only_command_refuses_a_truncated_file(name, fn, truncated, good):
    """No command of our own reports success on a file anndata cannot open.

    Two shapes count as a refusal. Most commands return ``{"error": ...}``.
    ``validate_schema`` and ``validate_cell_annotation`` delegate to
    ``hca_schema_validator``, whose verdict shape is its own and out of scope
    for #661 — an unreadable file comes back as ``is_valid: False`` carrying
    the read failure, which is a refusal by any reading that matters.
    """
    for param in sorted(_path_params(fn)):
        kwargs = dict.fromkeys(_path_params(fn), good) | {param: truncated}
        result = fn(**kwargs)

        assert isinstance(result, dict), f"{name} did not return the command error shape"
        refused = "error" in result or result.get("is_valid") is False
        assert refused, f"{name} accepted an unopenable file as {param}: {result}"


def test_every_registered_path_command_is_accounted_for():
    """The roster is the running server's, and every path command is on it.

    Deliberately not derived from the same predicate it checks: ``covered``
    is the union of the MCP-only cases above and the names the library suite
    proves, so a command that is neither — a new wrapper, or a re-export of
    something the library never gated — makes this fail.
    """
    library_gated = {name for name in hca_anndata_tools.__all__ if callable(getattr(hca_anndata_tools, name, None))}
    covered = {name for name, _ in MCP_ONLY} | library_gated | set(OMISSIONS)

    uncovered = {name for name, fn in _registered().items() if name not in covered and _path_params(fn)}
    assert not uncovered, f"registered commands with an unchecked path: {uncovered}"


def test_exemptions_still_exist():
    """A stale exemption is a hole nobody is watching."""
    registered = set(_registered())
    assert set(OMISSIONS) <= registered, f"exempted but not registered: {set(OMISSIONS) - registered}"
