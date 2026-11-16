"""Reads in worker processes: lanes, parallelism, cancellation, dead and retired workers, and the settings."""

import collections
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
    RETIRE_GIB_VAR,
    SLOW_WORKERS_VAR,
    Raised,
    Registrar,
    Returned,
    Settings,
    call_rebuildable,
    find_live_worker,
    held_bytes,
    raise_if_start_failed,
    retire,
    run_in_worker,
    settings,
)
from tests import worker_fixtures as fx

FAST = (fx.rendezvous, fx.pid, fx.die, fx.flood_stderr, fx.raise_two_arg_error, fx.raise_value_error)
SLOW = (fx.block, fx.hold, fx.hold_then_raise, fx.hold_until)
MIB = 2**20
RETIRE_MIB = 256  # above an idle test worker, below what `hold` takes in these tests
OVER_LIMIT_MIB = RETIRE_MIB + 64


def _server(fast: int = 1, slow: int = 1, retire_bytes: int = RETIRE_MIB * MIB) -> tuple[FastMCP, Registrar]:
    mcp = FastMCP("worker-tests")
    registrar = Registrar(mcp, Settings(fast + slow, slow, retire_bytes))
    for fn in FAST:
        registrar.register(fn, kind="fast")
    for fn in SLOW:
        registrar.register(fn, kind="slow")
    registrar.register(fx.write_marker, kind="write")
    return mcp, registrar


async def _fn(mcp: FastMCP, name: str):
    return (await mcp.get_tool(name)).fn


@pytest.mark.asyncio
async def test_two_reads_run_at_once_in_different_processes(tmp_path):
    mcp, _ = _server(fast=2)
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


def _open_and_close(path: Path, mode: str = "r") -> None:
    with path.open(mode):
        pass


@pytest.mark.asyncio
async def test_cancelled_read_releases_the_gate_and_a_write_runs(tmp_path):
    mcp, _ = _server()
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
    mcp, registrar = _server()
    pid = await _fn(mcp, "pid")
    with anyio.fail_after(60):
        async with registrar._gate.write():
            async with anyio.create_task_group() as tg:
                tg.start_soon(pid)
                await wait_all_tasks_blocked()
                assert registrar._lanes["fast"].borrowed_tokens == 1
                assert len(registrar._gate._queued_reads) == 1
                tg.cancel_scope.cancel()
            assert registrar._lanes["fast"].borrowed_tokens == 0
        assert "pid" in await pid()


@pytest.mark.asyncio
async def test_write_waits_for_a_running_read():
    mcp, registrar = _server()
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
    mcp, _ = _server(fast=2)
    with anyio.fail_after(60):
        assert await (await _fn(mcp, "die"))() == {
            "error": "die: the worker process died (killed, or out of memory); nothing was written"
        }
        assert "pid" in await (await _fn(mcp, "pid"))()
        assert (await (await _fn(mcp, "write_marker"))())["written"]


@pytest.mark.asyncio
async def test_read_sent_straight_after_its_idle_workers_died_runs_in_a_new_one(tmp_path):
    mcp, _ = _server(fast=2)
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
    mcp, _ = _server()
    flood = await _fn(mcp, "flood_stderr")
    with anyio.fail_after(60):
        assert await flood() == {"flooded": True}
        assert await flood() == {"flooded": True}


@pytest.mark.asyncio
async def test_exception_that_cannot_be_rebuilt_arrives_as_runtime_error():
    mcp, _ = _server()
    with anyio.fail_after(60):
        with pytest.raises(RuntimeError, match=r"^TwoArgError: 7: cannot be rebuilt$"):
            await (await _fn(mcp, "raise_two_arg_error"))()
        with pytest.raises(ValueError, match=r"^bad value$"):
            await (await _fn(mcp, "raise_value_error"))()


def test_settings_default_to_sixteen_workers_half_slow_and_three_gib():
    assert settings({}) == Settings(16, 8, 3 * 2**30)


@pytest.mark.parametrize(("n", "slow"), [("6", 3), ("3", 1), ("2", 1)])
def test_slow_workers_default_to_half_the_read_workers_rounded_down(n, slow):
    assert settings({READ_WORKERS_VAR: n}).slow_workers == slow


def test_settings_read_the_variables():
    environ = {READ_WORKERS_VAR: "10", SLOW_WORKERS_VAR: "3", RETIRE_GIB_VAR: "1.5"}
    assert settings(environ) == Settings(10, 3, int(1.5 * 2**30))


@pytest.mark.parametrize("var", [READ_WORKERS_VAR, SLOW_WORKERS_VAR])
@pytest.mark.parametrize("raw", ["0", "abc", "", "-1", " 2", "1.5"])
def test_settings_refuse_a_worker_count_that_is_not_a_positive_integer(var, raw):
    with pytest.raises(ValueError, match=f"^{var} must be a positive integer, got {raw!r}$"):
        settings({var: raw})


def test_settings_refuse_one_read_worker():
    with pytest.raises(ValueError, match=f"^{READ_WORKERS_VAR} must be at least 2"):
        settings({READ_WORKERS_VAR: "1"})


@pytest.mark.parametrize("slow", ["16", "17"])
def test_settings_refuse_as_many_slow_workers_as_read_workers(slow):
    with pytest.raises(ValueError, match=f"^{SLOW_WORKERS_VAR} must be less than {READ_WORKERS_VAR} \\(16\\)"):
        settings({SLOW_WORKERS_VAR: slow})


@pytest.mark.parametrize("raw", ["0", "0.0", "abc", "", "-1", "1e3", " 2"])
def test_settings_refuse_a_retire_limit_that_is_not_a_positive_number(raw):
    with pytest.raises(ValueError, match=f"^{RETIRE_GIB_VAR} must be a positive number of GiB"):
        settings({RETIRE_GIB_VAR: raw})


@pytest.mark.parametrize("var", [READ_WORKERS_VAR, SLOW_WORKERS_VAR])
def test_server_does_not_start_with_a_bad_setting(var):
    proc = subprocess.run(
        [sys.executable, "-c", "from hca_anndata_mcp.main import run; run()"],
        env={**os.environ, var: "abc"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode != 0
    assert f"ValueError: {var} must be a positive integer, got 'abc'" in proc.stderr


def test_a_read_a_worker_cannot_find_is_refused_at_registration():
    @functools.wraps(fx.pid)
    def misnamed() -> dict:
        return {}

    with pytest.raises(TypeError, match="a worker cannot find it"):
        Registrar(FastMCP("refuses"), Settings(2, 1, 2**30)).register(misnamed, kind="fast")


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


@pytest.mark.asyncio
async def test_read_pings_n_plus_one_times_before_it_runs(monkeypatch):
    # N idle workers can all be dead; N + 1 pings get past every one of them.
    mcp, registrar = _server()
    pings = Pings(failures=10, error=BrokenWorkerProcess())
    calls = []

    async def in_worker(call):
        calls.append(call)
        return Returned("ran", os.getpid(), 0)

    monkeypatch.setattr(registrar, "_ping", pings)
    monkeypatch.setattr(registrar, "_in_worker", in_worker)
    assert await (await _fn(mcp, "pid"))() == "ran"
    assert (pings.calls, len(calls)) == (3, 1)


def test_start_up_failure_is_raised_with_its_cause_and_a_later_death_is_not():
    error = BrokenWorkerProcess("Error during worker process initialization")
    error.__cause__ = IndexError("list index out of range")
    with pytest.raises(RuntimeError, match=r"^a read worker could not start: IndexError: list index out of range$"):
        raise_if_start_failed(error)
    # anyio's 20 s start-up limit gives a cause with no text.
    error.__cause__ = TimeoutError()
    with pytest.raises(RuntimeError, match=r"^a read worker could not start: TimeoutError$"):
        raise_if_start_failed(error)
    # A worker that prints before `READY` fails with anyio's own message and no cause.
    with pytest.raises(RuntimeError, match=r"^a read worker could not start: .*unexpected response: b'hello\\n'$"):
        raise_if_start_failed(BrokenWorkerProcess("Worker process returned unexpected response: b'hello\\n'"))
    raise_if_start_failed(BrokenWorkerProcess())


START_FAILS = """
import anyio
from fastmcp import FastMCP
from hca_anndata_mcp.scheduling import Registrar, Settings
from hca_anndata_tools import locate_files

if __name__ != "__main__":
    with open("starts.log", "a") as log:
        log.write("start\\n")
    raise IndexError("planted start-up failure")


async def main():
    mcp = FastMCP("start-fails")
    Registrar(mcp, Settings(2, 1, 2**30)).register(locate_files, kind="fast")
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
    # The first ping's failure ends the read: no further pings, and no worker for the read itself.
    assert (tmp_path / "starts.log").read_text() == "start\n"


def _pool_pids() -> tuple[set[int], list[int]]:
    # anyio's own pool state: every worker it knows, and the idle ones in the order it reuses them.
    workers = {p.pid for p in anyio.to_process._process_pool_workers.get()}
    return workers, [p.pid for p, _ in anyio.to_process._process_pool_idle_workers.get()]


@pytest.mark.asyncio
async def test_a_fast_read_returns_while_the_slow_lane_is_full_and_a_slow_read_waits(tmp_path):
    # Two workers, one slow: a scan holds the slow slot and a second scan waits for it. With
    # one lane of two slots, as before, the two scans would fill it and the fast read would wait.
    mcp, registrar = _server(fast=1, slow=1)
    started, never = tmp_path / "started", tmp_path / "never-opened"
    os.mkfifo(started)
    os.mkfifo(never)
    block, hold, pid = await _fn(mcp, "block"), await _fn(mcp, "hold"), await _fn(mcp, "pid")
    order = []

    async def second_scan():
        await hold(mib=0)
        order.append("second scan")

    with anyio.fail_after(60):
        async with anyio.create_task_group() as tg:
            tg.start_soon(functools.partial(block, started=str(started), never=str(never)))
            await anyio.to_thread.run_sync(_open_and_close, started, abandon_on_cancel=True)
            tg.start_soon(second_scan)
            await wait_all_tasks_blocked()
            assert registrar._lanes["slow"].statistics().tasks_waiting == 1
            assert "pid" in await pid()
            order.append("fast read")
            tg.cancel_scope.cancel()
        assert order == ["fast read"]
        await second_scan()
    assert order == ["fast read", "second scan"]


@pytest.mark.asyncio
async def test_a_worker_left_holding_more_than_the_limit_leaves_the_pool():
    mcp, _ = _server()
    with anyio.fail_after(60):
        held = (await (await _fn(mcp, "hold"))(mib=OVER_LIMIT_MIB))["pid"]
    assert _pool_pids() == (set(), [])
    with pytest.raises(ProcessLookupError):
        os.kill(held, 0)


@pytest.mark.asyncio
async def test_a_worker_below_the_limit_stays_idle_in_the_pool():
    mcp, _ = _server()
    with anyio.fail_after(60):
        kept = (await (await _fn(mcp, "hold"))(mib=16))["pid"]
    assert _pool_pids() == ({kept}, [kept])


@pytest.mark.asyncio
async def test_a_read_that_raises_after_passing_the_limit_still_retires_its_worker():
    mcp, _ = _server()
    with anyio.fail_after(60), pytest.raises(ValueError, match=r"^held, then failed$"):
        await (await _fn(mcp, "hold_then_raise"))(mib=OVER_LIMIT_MIB)
    assert _pool_pids() == (set(), [])


@pytest.mark.asyncio
async def test_the_read_waiting_for_a_retired_workers_slot_runs_in_a_live_new_worker(tmp_path):
    mcp, registrar = _server(fast=1, slow=1)
    release = tmp_path / "release"
    os.mkfifo(release)
    hold_until, hold = await _fn(mcp, "hold_until"), await _fn(mcp, "hold")
    results = {}

    async def call(name, fn, **kwargs):
        results[name] = (await fn(**kwargs))["pid"]

    with anyio.fail_after(60):
        async with anyio.create_task_group() as tg:
            tg.start_soon(functools.partial(call, "retired", hold_until, mib=OVER_LIMIT_MIB, release=str(release)))
            tg.start_soon(functools.partial(call, "next", hold, mib=0))
            await wait_all_tasks_blocked()
            assert registrar._lanes["slow"].statistics().tasks_waiting == 1
            await anyio.to_thread.run_sync(_open_and_close, release, "w", abandon_on_cancel=True)
    assert results["next"] != results["retired"]
    assert _pool_pids() == ({results["next"]}, [results["next"]])


def _children() -> int:
    out = subprocess.run(["ps", "-Ao", "ppid="], capture_output=True, text=True, check=True).stdout
    return sum(int(ppid) == os.getpid() for ppid in out.split())


def _open_files() -> int:
    return len(list(Path("/dev/fd").iterdir()))


@pytest.mark.asyncio
async def test_fifty_retirements_leave_no_processes_or_open_files_behind():
    mcp, _ = _server(retire_bytes=0)  # every worker holds more than nothing, so every call retires one
    pid = await _fn(mcp, "pid")
    with anyio.fail_after(120):
        await pid()
        before = (_children(), _open_files())
        for _ in range(50):
            await pid()
    assert (_children(), _open_files()) == before
    assert _pool_pids() == (set(), [])


@pytest.mark.asyncio
async def test_anyio_keeps_the_pool_where_retiring_a_worker_looks_for_it():
    # `retire` reaches into anyio's private pool state; this fails if an anyio release moves it.
    mcp, _ = _server()
    with anyio.fail_after(60):
        await (await _fn(mcp, "pid"))()
    workers = anyio.to_process._process_pool_workers.get()
    idle = anyio.to_process._process_pool_idle_workers.get()
    assert isinstance(workers, set)
    assert isinstance(idle, collections.deque)
    process, _ = idle[-1]
    assert process in workers
    assert isinstance(process.pid, int)


def test_held_bytes_counts_memory_this_process_touches():
    before = held_bytes()
    buf = fx.touched(64)
    assert held_bytes() - before >= 60 * MIB
    del buf


@pytest.fixture
def keep_fd_2():
    # `run_in_worker` points descriptor 2 at /dev/null, as it does in a worker; put it back.
    saved = os.dup(2)
    yield
    os.dup2(saved, 2)
    os.close(saved)


def test_run_in_worker_returns_the_value_with_its_pid_and_held_memory(keep_fd_2):
    done = run_in_worker(fx.pid)
    assert isinstance(done, Returned)
    assert (done.value, done.pid) == ({"pid": os.getpid()}, os.getpid())
    assert done.held_bytes > 0


def test_run_in_worker_returns_the_exception_without_its_traceback(keep_fd_2):
    done = run_in_worker(fx.raise_two_arg_error)
    assert isinstance(done, Raised)
    assert (type(done.error), str(done.error), done.pid) == (
        RuntimeError,
        "TwoArgError: 7: cannot be rebuilt",
        os.getpid(),
    )
    assert (done.error.__traceback__, done.error.__context__) == (None, None)


@pytest.mark.asyncio
async def test_retire_refuses_a_worker_that_is_not_the_last_idle_one():
    mcp, _ = _server()
    with anyio.fail_after(60):
        kept = (await (await _fn(mcp, "pid"))())["pid"]
        with pytest.raises(RuntimeError, match=f"^cannot retire worker {kept + 1}: it is not the last idle worker$"):
            await retire(kept + 1)
    assert _pool_pids() == ({kept}, [kept])


def test_held_bytes_is_not_measured_on_other_platforms(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(NotImplementedError, match="^held memory is not measured on win32$"):
        held_bytes()
