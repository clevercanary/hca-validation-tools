"""The gate on its own: who holds it, in what order, and what cancellation gives back."""

from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import anyio
import pytest
from anyio import wait_all_tasks_blocked
from anyio.abc import TaskGroup

from hca_anndata_mcp.scheduling import Gate


class Holders:
    """Start tasks that take the gate, record when they get it, and hold it until released."""

    def __init__(self, tg: TaskGroup) -> None:
        self.tg = tg
        self.log: list[str] = []
        self.releases: dict[str, anyio.Event] = {}
        self.scopes: dict[str, anyio.CancelScope] = {}

    async def start(self, name: str, take: Callable[[], AbstractAsyncContextManager[None]]) -> None:
        self.releases[name] = anyio.Event()
        self.scopes[name] = anyio.CancelScope()
        self.tg.start_soon(self._hold, name, take)
        await wait_all_tasks_blocked()

    async def release(self, name: str) -> None:
        self.releases[name].set()
        await wait_all_tasks_blocked()

    async def cancel(self, name: str) -> None:
        self.scopes[name].cancel()
        await wait_all_tasks_blocked()

    async def _hold(self, name: str, take: Callable[[], AbstractAsyncContextManager[None]]) -> None:
        with self.scopes[name]:
            async with take():
                self.log.append(name)
                await self.releases[name].wait()


@asynccontextmanager
async def holders() -> AsyncGenerator[Holders, None]:
    """Holders for one test; leaving cancels every task still holding or waiting."""
    async with anyio.create_task_group() as tg:
        yield Holders(tg)
        tg.cancel_scope.cancel()


@pytest.mark.asyncio
async def test_reads_share_the_gate():
    gate = Gate()
    async with holders() as h:
        await h.start("r1", gate.read)
        await h.start("r2", gate.read)
        assert h.log == ["r1", "r2"]


@pytest.mark.asyncio
async def test_write_waits_for_running_reads():
    gate = Gate()
    async with holders() as h:
        await h.start("r1", gate.read)
        await h.start("w", gate.write)
        assert h.log == ["r1"]
        await h.release("r1")
        assert h.log == ["r1", "w"]


@pytest.mark.asyncio
async def test_read_arriving_while_a_write_waits_runs_after_it():
    gate = Gate()
    async with holders() as h:
        await h.start("r1", gate.read)
        await h.start("w", gate.write)
        await h.start("r2", gate.read)
        assert h.log == ["r1"]
        await h.release("r1")
        assert h.log == ["r1", "w"]
        await h.release("w")
        assert h.log == ["r1", "w", "r2"]


@pytest.mark.asyncio
async def test_reads_waiting_when_a_write_finishes_run_before_the_next_write():
    gate = Gate()
    async with holders() as h:
        await h.start("w1", gate.write)
        await h.start("r1", gate.read)
        await h.start("w2", gate.write)
        await h.start("r2", gate.read)
        await h.release("w1")
        assert h.log == ["w1", "r1", "r2"]
        await h.start("r3", gate.read)
        await h.release("r1")
        await h.release("r2")
        assert h.log == ["w1", "r1", "r2", "w2"]
        await h.release("w2")
        assert h.log == ["w1", "r1", "r2", "w2", "r3"]


@pytest.mark.asyncio
async def test_writes_start_in_arrival_order():
    gate = Gate()
    async with holders() as h:
        for name in ("w1", "w2", "w3"):
            await h.start(name, gate.write)
        for name in ("w1", "w2", "w3"):
            await h.release(name)
        assert h.log == ["w1", "w2", "w3"]


@pytest.mark.asyncio
async def test_cancelled_waiting_write_lets_the_reads_behind_it_in():
    gate = Gate()
    async with holders() as h:
        await h.start("r1", gate.read)
        await h.start("w", gate.write)
        await h.start("r2", gate.read)
        await h.cancel("w")
        assert h.log == ["r1", "r2"]
        await h.release("r1")
        await h.release("r2")
        await h.start("w2", gate.write)
        assert h.log == ["r1", "r2", "w2"]


@pytest.mark.asyncio
async def test_cancelled_waiting_read_does_not_hold_the_gate():
    gate = Gate()
    async with holders() as h:
        await h.start("w1", gate.write)
        await h.start("r", gate.read)
        await h.cancel("r")
        await h.release("w1")
        await h.start("w2", gate.write)
        assert h.log == ["w1", "w2"]


@pytest.mark.asyncio
async def test_cancelled_holders_release_the_gate():
    gate = Gate()
    async with holders() as h:
        await h.start("r", gate.read)
        await h.cancel("r")
        await h.start("w1", gate.write)
        await h.cancel("w1")
        await h.start("w2", gate.write)
        assert h.log == ["r", "w1", "w2"]


@pytest.mark.asyncio
async def test_write_admitted_and_cancelled_at_once_passes_the_gate_on():
    gate = Gate()
    async with holders() as h:
        await h.start("r1", gate.read)
        await h.start("w", gate.write)
        await h.start("r2", gate.read)
        # Grant and cancel land before the waiting write runs again.
        h.releases["r1"].set()
        h.scopes["w"].cancel()
        await wait_all_tasks_blocked()
        assert h.log == ["r1", "r2"]


@pytest.mark.asyncio
async def test_cancelled_waiting_write_keeps_reads_out_while_another_write_waits():
    gate = Gate()
    async with holders() as h:
        await h.start("r1", gate.read)
        await h.start("w1", gate.write)
        await h.start("w2", gate.write)
        await h.start("r2", gate.read)
        await h.cancel("w1")
        assert h.log == ["r1"]
        await h.release("r1")
        assert h.log == ["r1", "w2"]
        await h.release("w2")
        assert h.log == ["r1", "w2", "r2"]
