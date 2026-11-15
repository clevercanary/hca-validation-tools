"""The gate under random arrivals, releases and cancellations, checked after every step."""

import random
from dataclasses import dataclass, field
from typing import Literal

import anyio
import pytest
from anyio import wait_all_tasks_blocked
from anyio.abc import TaskGroup
from anyio.lowlevel import checkpoint

from hca_anndata_mcp.scheduling import Gate

SEEDS = range(500)
STEPS = 60


async def settle() -> None:
    # A few yields first: anyio's check sleeps 100 ms on asyncio whenever a task is still runnable.
    for _ in range(8):
        await checkpoint()
    await wait_all_tasks_blocked()


@dataclass(eq=False)
class Call:
    kind: Literal["read", "write"]
    state: Literal["waiting", "holding", "done"] = "waiting"
    release: anyio.Event = field(default_factory=anyio.Event)
    scope: anyio.CancelScope = field(default_factory=anyio.CancelScope)


class Run:
    def __init__(self, gate: Gate, tg: TaskGroup, rng: random.Random) -> None:
        self.gate = gate
        self.tg = tg
        self.rng = rng
        self.calls: list[Call] = []
        self.write_starts: list[Call] = []

    def having(self, state: str, kind: str | None = None) -> list[Call]:
        return [c for c in self.calls if c.state == state and kind in (None, c.kind)]

    async def _hold(self, call: Call) -> None:
        with call.scope:
            try:
                async with self.gate.read() if call.kind == "read" else self.gate.write():
                    call.state = "holding"
                    if call.kind == "write":
                        self.write_starts.append(call)
                    await call.release.wait()
            finally:
                call.state = "done"

    async def arrive(self, kind: Literal["read", "write"]) -> None:
        writes_ahead = self.having("waiting", "write") or self.having("holding", "write")
        call = Call(kind)
        self.calls.append(call)
        self.tg.start_soon(self._hold, call)
        await settle()
        if kind == "read" and writes_ahead:
            assert call.state == "waiting", "a read went straight in while a write was waiting or running"

    async def end(self, ending: list[Call], cancelling: list[Call]) -> None:
        """End holders and cancel waiters in one tick, then check who the gate let in."""
        write_ends = any(c.kind == "write" for c in ending)
        reads_waiting = [c for c in self.having("waiting", "read") if c not in cancelling]
        for call in ending:
            call.release.set() if self.rng.random() < 0.5 else call.scope.cancel()
        for call in cancelling:
            call.scope.cancel()
        await settle()
        if write_ends:
            assert all(c.state == "holding" for c in reads_waiting), "a waiting read missed its turn after a write"

    def check(self) -> None:
        reads, writes = self.having("holding", "read"), self.having("holding", "write")
        assert len(writes) <= 1 and not (writes and reads), "a write overlapped another call"
        if self.having("waiting", "write"):
            assert reads or writes, "a write waits while nothing holds the gate"
        if self.having("waiting", "read"):
            assert writes or self.having("waiting", "write"), "a read waits with no write ahead of it"
        started = [c for c in self.calls if c in self.write_starts]
        assert self.write_starts == started, "writes started out of arrival order"

    async def step(self) -> None:
        holding, waiting = self.having("holding"), self.having("waiting")
        roll = self.rng.random()
        if not (holding or waiting):
            await self.arrive(self.rng.choice(["read", "write"]))
        elif roll < 0.35:
            await self.arrive("read")
        elif roll < 0.55:
            await self.arrive("write")
        elif roll < 0.8 and holding:
            await self.end([self.rng.choice(holding)], [])
        elif roll < 0.9 and waiting:
            await self.end([], [self.rng.choice(waiting)])
        elif holding and waiting:
            await self.end([self.rng.choice(holding)], [self.rng.choice(waiting)])
        self.check()

    async def drain(self) -> None:
        while holding := self.having("holding"):
            await self.end(holding, [])
            self.check()
        assert not self.having("waiting"), "a call was left waiting after every holder finished"


async def play(seed: int) -> None:
    """One random schedule; a broken rule raises ``AssertionError`` naming the seed that replays it."""
    failure = None
    async with anyio.create_task_group() as tg:
        run = Run(Gate(), tg, random.Random(seed))
        try:
            for _ in range(STEPS):
                await run.step()
            await run.drain()
        except AssertionError as exc:
            failure = exc
            tg.cancel_scope.cancel()
    if failure:
        raise AssertionError(f"seed {seed}: {failure}") from failure


@pytest.mark.asyncio
async def test_gate_keeps_its_rules_under_random_schedules():
    for seed in SEEDS:
        await play(seed)
