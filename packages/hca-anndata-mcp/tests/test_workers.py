"""Reads in worker processes: parallelism, cancellation, dead workers, and the worker-count setting."""

import functools
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import anyio
import pytest
from anyio import BrokenWorkerProcess, wait_all_tasks_blocked
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StdioTransport

from hca_anndata_mcp.scheduling import (
    READ_WORKERS_VAR,
    Registrar,
    call_rebuildable,
    find_live_worker,
    raise_if_start_failed,
    read_workers,
)
from tests import worker_fixtures as fx

READS = (fx.rendezvous, fx.block, fx.pid, fx.die, fx.flood_stderr, fx.raise_two_arg_error, fx.raise_value_error)


def _server(n: int) -> tuple[FastMCP, Registrar]:
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
    mcp, _ = _server(2)
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
    pids = {results["write"]["pid"], results["read"]["pid"]}
    assert len(pids) == 2
    assert os.getpid() not in pids


def _open_and_close(path: Path) -> None:
    with path.open("r"):
        pass


@pytest.mark.asyncio
async def test_cancelled_read_releases_the_gate_and_a_write_runs(tmp_path):
    mcp, _ = _server(1)
    started, never = tmp_path / "started", tmp_path / "never-opened"
    os.mkfifo(started)
    os.mkfifo(never)
    block = await _fn(mcp, "block")
    with anyio.fail_after(60):
        async with anyio.create_task_group() as tg:
            tg.start_soon(functools.partial(block, started=str(started), never=str(never)))
            await anyio.to_thread.run_sync(_open_and_close, started, abandon_on_cancel=True)
            tg.cancel_scope.cancel()
        assert await (await _fn(mcp, "write_marker"))() == {"written": True, "pid": os.getpid()}
        assert (await (await _fn(mcp, "pid"))())["pid"] != os.getpid()


@pytest.mark.asyncio
async def test_read_cancelled_before_the_gate_gives_back_its_slot():
    mcp, registrar = _server(1)
    pid = await _fn(mcp, "pid")
    with anyio.fail_after(60):
        async with registrar._gate.write():
            async with anyio.create_task_group() as tg:
                tg.start_soon(pid)
                await wait_all_tasks_blocked()
                assert registrar._slots.borrowed_tokens == 1
                assert len(registrar._gate._queued_reads) == 1
                tg.cancel_scope.cancel()
            assert registrar._slots.borrowed_tokens == 0
        assert "pid" in await pid()


@pytest.mark.asyncio
async def test_write_waits_for_a_running_read():
    mcp, registrar = _server(1)
    write_marker = await _fn(mcp, "write_marker")
    results = []

    async def write():
        results.append(await write_marker())

    with anyio.fail_after(60):
        async with anyio.create_task_group() as tg, registrar._gate.read():
            tg.start_soon(write)
            await wait_all_tasks_blocked()
            assert len(registrar._gate._writers) == 1
            assert results == []
        assert results == [{"written": True, "pid": os.getpid()}]


@pytest.mark.asyncio
async def test_dead_worker_fails_only_its_own_call():
    mcp, _ = _server(2)
    with anyio.fail_after(60):
        assert await (await _fn(mcp, "die"))() == {
            "error": "die: the worker process died (killed, or out of memory); nothing was written"
        }
        assert "pid" in await (await _fn(mcp, "pid"))()
        assert (await (await _fn(mcp, "write_marker"))())["written"]


@pytest.mark.asyncio
async def test_read_sent_straight_after_its_idle_workers_died_runs_in_a_new_one(tmp_path):
    mcp, _ = _server(2)
    fifo = tmp_path / "barrier"
    os.mkfifo(fifo)
    rendezvous, pid = await _fn(mcp, "rendezvous"), await _fn(mcp, "pid")
    victims = set()

    async def call(end):
        victims.add((await rendezvous(fifo=str(fifo), end=end))["pid"])

    with anyio.fail_after(60):
        async with anyio.create_task_group() as tg:
            tg.start_soon(call, "write")
            tg.start_soon(call, "read")
        assert len(victims) == 2
        for victim in victims:
            os.kill(victim, signal.SIGKILL)
        # No yield in between: the event loop has not yet seen either exit.
        result = await pid()
    assert "error" not in result
    assert result["pid"] not in victims


@pytest.mark.asyncio
async def test_output_on_file_descriptor_2_does_not_hang_the_worker():
    mcp, _ = _server(1)
    flood = await _fn(mcp, "flood_stderr")
    with anyio.fail_after(60):
        assert await flood() == {"flooded": True}
        assert await flood() == {"flooded": True}


@pytest.mark.asyncio
async def test_exception_that_cannot_be_rebuilt_arrives_as_runtime_error():
    mcp, _ = _server(1)
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


def test_server_does_not_start_with_a_bad_worker_count():
    proc = subprocess.run(
        [sys.executable, "-c", "from hca_anndata_mcp.main import run; run()"],
        env={**os.environ, READ_WORKERS_VAR: "abc"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode != 0
    assert f"ValueError: {READ_WORKERS_VAR} must be a positive integer, got 'abc'" in proc.stderr


def test_a_read_a_worker_cannot_find_is_refused_at_registration():
    @functools.wraps(fx.pid)
    def misnamed() -> dict:
        return {}

    with pytest.raises(TypeError, match="a worker cannot find it"):
        Registrar(FastMCP("refuses"), 1).register(misnamed, kind="read")


def test_call_rebuildable_passes_results_and_rebuildable_exceptions_through():
    assert call_rebuildable(fx.pid) == {"pid": os.getpid()}
    with pytest.raises(ValueError, match=r"^bad value$"):
        call_rebuildable(fx.raise_value_error)


def test_call_rebuildable_turns_an_exception_that_cannot_be_rebuilt_into_runtime_error():
    with pytest.raises(RuntimeError, match=r"^TwoArgError: 7: cannot be rebuilt$"):
        call_rebuildable(fx.raise_two_arg_error)


@pytest.mark.skipif(sys.version_info < (3, 11), reason="Python 3.10 ignores PYTHONSAFEPATH (contract rule 20)")
@pytest.mark.asyncio
async def test_worker_ignores_a_module_planted_in_the_servers_working_directory(tmp_path):
    marker = tmp_path / "planted-ran"
    (tmp_path / "anyio").mkdir()
    (tmp_path / "anyio" / "__init__.py").write_text(f"open({str(marker)!r}, 'w').close()\n")
    server = StdioTransport(command=str(Path(sys.executable).parent / "hca-anndata-mcp"), args=[], cwd=str(tmp_path))
    with anyio.fail_after(60):
        async with Client(server) as client:
            result = await client.call_tool("locate_files", {"directory": str(tmp_path)})
    assert json.loads(result.content[0].text) == {"h5ad": [], "total": 0}
    assert not marker.exists()


class Pings:
    """A stand-in ping: fails its first ``failures`` calls with ``error``, then answers."""

    def __init__(self, failures: int, error: BaseException) -> None:
        self.failures = failures
        self.error = error
        self.calls = 0

    async def __call__(self) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error


@pytest.mark.asyncio
async def test_find_live_worker_stops_at_the_first_ping_that_answers():
    pings = Pings(failures=2, error=BrokenWorkerProcess())
    await find_live_worker(pings, tries=5)
    assert pings.calls == 3


@pytest.mark.asyncio
async def test_find_live_worker_gives_up_after_its_tries_and_lets_the_read_go():
    pings = Pings(failures=10, error=BrokenWorkerProcess())
    await find_live_worker(pings, tries=3)
    assert pings.calls == 3


@pytest.mark.asyncio
async def test_find_live_worker_stops_at_an_error_that_is_not_a_dead_worker():
    pings = Pings(failures=10, error=RuntimeError("a read worker could not start: IndexError: planted"))
    with pytest.raises(RuntimeError, match="could not start"):
        await find_live_worker(pings, tries=3)
    assert pings.calls == 1


def test_start_up_failure_is_raised_with_its_cause_and_a_later_death_is_not():
    error = BrokenWorkerProcess("Error during worker process initialization")
    error.__cause__ = IndexError("list index out of range")
    with pytest.raises(RuntimeError, match=r"^a read worker could not start: IndexError: list index out of range$"):
        raise_if_start_failed(error)
    raise_if_start_failed(BrokenWorkerProcess())


START_FAILS = """
import anyio
from fastmcp import FastMCP
from hca_anndata_mcp.scheduling import Registrar
from hca_anndata_tools import locate_files

if __name__ != "__main__":
    raise IndexError("planted start-up failure")


async def main():
    mcp = FastMCP("start-fails")
    Registrar(mcp, 2).register(locate_files, kind="read")
    read = (await mcp.get_tool("locate_files")).fn
    try:
        await read(directory=".")
    except RuntimeError as exc:
        print(exc)


anyio.run(main)
"""


def test_read_whose_worker_cannot_start_raises_with_the_cause(tmp_path):
    # anyio re-runs the parent's entry script in each new worker, so this script fails there.
    script = tmp_path / "start_fails.py"
    script.write_text(START_FAILS)
    proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert proc.stdout.strip() == "a read worker could not start: IndexError: planted start-up failure", proc.stderr
