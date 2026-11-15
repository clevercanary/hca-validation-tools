"""Reads in worker processes: parallelism, cancellation, dead workers, and the worker-count setting."""

import os
import subprocess
import sys

import anyio
import pytest
from anyio import wait_all_tasks_blocked
from fastmcp import FastMCP

from hca_anndata_mcp.scheduling import READ_WORKERS_VAR, Registrar, call_rebuildable, read_workers, worker_died
from tests import worker_fixtures as fx

READS = (fx.rendezvous, fx.pid, fx.die, fx.flood_stderr, fx.raise_two_arg_error, fx.raise_value_error)


async def _server(n: int) -> tuple[FastMCP, Registrar]:
    mcp = FastMCP("worker-tests")
    registrar = Registrar(mcp, n)
    for fn in READS:
        registrar.register(fn, kind="read")
    registrar.register(fx.write_marker, kind="write")
    return mcp, registrar


async def _fn(mcp: FastMCP, name: str):
    return (await mcp.get_tool(name)).fn


@pytest.mark.asyncio
async def test_two_reads_run_at_once_in_different_processes(tmp_path):
    mcp, _ = await _server(2)
    fifo = tmp_path / "barrier"
    os.mkfifo(fifo)
    rendezvous = await _fn(mcp, "rendezvous")
    results = {}

    async def call(end):
        results[end] = await rendezvous(fifo=str(fifo), end=end)

    with anyio.fail_after(60):
        async with anyio.create_task_group() as tg:
            tg.start_soon(call, "write")
            tg.start_soon(call, "read")
    assert results["write"]["pid"] != results["read"]["pid"] != os.getpid()


@pytest.mark.asyncio
async def test_cancelled_read_releases_the_gate_and_a_write_runs(tmp_path):
    mcp, _ = await _server(1)
    fifo = tmp_path / "never-opened"
    os.mkfifo(fifo)
    rendezvous = await _fn(mcp, "rendezvous")
    with anyio.fail_after(60):
        with anyio.move_on_after(5) as scope:
            await rendezvous(fifo=str(fifo), end="read")
        assert scope.cancelled_caught
        assert await (await _fn(mcp, "write_marker"))() == {"written": True, "pid": os.getpid()}
        assert (await (await _fn(mcp, "pid"))())["pid"] != os.getpid()


@pytest.mark.asyncio
async def test_read_cancelled_before_the_gate_gives_back_its_slot():
    mcp, registrar = await _server(1)
    pid = await _fn(mcp, "pid")
    with anyio.fail_after(60):
        async with anyio.create_task_group() as tg:
            write_held = anyio.Event()
            write_done = anyio.Event()

            async def hold_write():
                async with registrar._gate.write():
                    write_held.set()
                    await write_done.wait()

            read_scope = anyio.CancelScope()

            async def cancelled_read():
                with read_scope:
                    await pid()

            tg.start_soon(hold_write)
            await write_held.wait()
            tg.start_soon(cancelled_read)
            await wait_all_tasks_blocked()
            assert registrar._slots.borrowed_tokens == 1
            read_scope.cancel()
            await wait_all_tasks_blocked()
            assert registrar._slots.borrowed_tokens == 0
            write_done.set()
        assert "pid" in await pid()


@pytest.mark.asyncio
async def test_dead_worker_fails_only_its_own_call():
    mcp, _ = await _server(2)
    with anyio.fail_after(60):
        assert await (await _fn(mcp, "die"))() == worker_died("die")
        assert "pid" in await (await _fn(mcp, "pid"))()
        assert (await (await _fn(mcp, "write_marker"))())["written"]


@pytest.mark.asyncio
async def test_output_on_file_descriptor_2_does_not_hang_the_worker():
    mcp, _ = await _server(1)
    flood = await _fn(mcp, "flood_stderr")
    with anyio.fail_after(60):
        assert await flood() == {"flooded": True}
        assert await flood() == {"flooded": True}


@pytest.mark.asyncio
async def test_exception_that_cannot_be_rebuilt_arrives_as_runtime_error():
    mcp, _ = await _server(1)
    with anyio.fail_after(60):
        with pytest.raises(RuntimeError, match=r"^TwoArgError: 7: cannot be rebuilt$"):
            await (await _fn(mcp, "raise_two_arg_error"))()
        with pytest.raises(ValueError, match=r"^bad value$"):
            await (await _fn(mcp, "raise_value_error"))()


def test_read_workers_defaults_to_six():
    assert read_workers({}) == 6


def test_read_workers_reads_the_variable():
    assert read_workers({READ_WORKERS_VAR: "3"}) == 3


@pytest.mark.parametrize("raw", ["0", "abc", "", "-1", " 2", "1.5"])
def test_read_workers_refuses_anything_but_a_positive_integer(raw):
    with pytest.raises(ValueError, match=READ_WORKERS_VAR):
        read_workers({READ_WORKERS_VAR: raw})


@pytest.mark.parametrize("raw", ["0", "abc"])
def test_server_does_not_start_with_a_bad_worker_count(raw):
    proc = subprocess.run(
        [sys.executable, "-c", "import hca_anndata_mcp.main"],
        env={**os.environ, READ_WORKERS_VAR: raw},
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert f"ValueError: {READ_WORKERS_VAR} must be a positive integer, got {raw!r}" in proc.stderr


def test_call_rebuildable_passes_results_and_rebuildable_exceptions_through():
    assert call_rebuildable(fx.pid, (), {}) == {"pid": os.getpid()}
    with pytest.raises(ValueError, match=r"^bad value$"):
        call_rebuildable(fx.raise_value_error, (), {})


def test_call_rebuildable_turns_an_exception_that_cannot_be_rebuilt_into_runtime_error():
    with pytest.raises(RuntimeError, match=r"^TwoArgError: 7: cannot be rebuilt$"):
        call_rebuildable(fx.raise_two_arg_error, (), {})
