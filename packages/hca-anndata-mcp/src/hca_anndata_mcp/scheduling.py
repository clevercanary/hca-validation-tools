"""Run read tools in parallel worker processes and write tools one at a time.

The rules are in ``docs/anndata-mcp-concurrency-contract.md``.
"""

import functools
import math
import os
import pickle
import re
from collections import deque
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Literal

import anyio
from anyio import BrokenWorkerProcess, to_process
from fastmcp import FastMCP

Kind = Literal["read", "write"]

READ_WORKERS_VAR = "HCA_ANNDATA_MCP_READ_WORKERS"
DEFAULT_READ_WORKERS = 6


def read_workers(environ: Mapping[str, str]) -> int:
    """The read-worker count from ``HCA_ANNDATA_MCP_READ_WORKERS``, or 6 when it is unset.

    Raises:
        ValueError: the variable is set to anything but a positive integer.
    """
    raw = environ.get(READ_WORKERS_VAR)
    if raw is None:
        return DEFAULT_READ_WORKERS
    if not re.fullmatch(r"[0-9]+", raw) or int(raw) < 1:
        raise ValueError(f"{READ_WORKERS_VAR} must be a positive integer, got {raw!r}")
    return int(raw)


@dataclass(eq=False)
class _Waiter:
    event: anyio.Event = field(default_factory=anyio.Event)
    admitted: bool = False


class Gate:
    """A readers-writer lock: reads share it, a write holds it alone.

    A waiting write keeps new reads out. When a write releases the gate,
    every read waiting at that moment takes it before the next write.
    Writes start in the order they arrived.
    """

    def __init__(self) -> None:
        self._readers = 0
        self._writing = False
        self._writers: deque[_Waiter] = deque()
        self._queued_reads: list[_Waiter] = []

    @asynccontextmanager
    async def read(self) -> AsyncGenerator[None, None]:
        if self._writing or self._writers:
            await self._wait(self._queued_reads, self._withdraw_read, self._release_read)
        else:
            self._readers += 1
        try:
            yield
        finally:
            self._release_read()

    @asynccontextmanager
    async def write(self) -> AsyncGenerator[None, None]:
        if self._writing or self._readers or self._writers:
            await self._wait(self._writers, self._withdraw_write, self._release_write)
        else:
            self._writing = True
        try:
            yield
        finally:
            self._release_write()

    async def _wait(
        self,
        queue: deque[_Waiter] | list[_Waiter],
        withdraw: Callable[[_Waiter], None],
        release: Callable[[], None],
    ) -> None:
        waiter = _Waiter()
        queue.append(waiter)
        try:
            await waiter.event.wait()
        except BaseException:
            # Cancelled: give back the place, or the grant if it arrived at the same moment.
            if waiter.admitted:
                release()
            else:
                withdraw(waiter)
            raise

    def _admit_reads(self) -> None:
        for waiter in self._queued_reads:
            waiter.admitted = True
            waiter.event.set()
        self._readers += len(self._queued_reads)
        self._queued_reads.clear()

    def _admit_writer(self) -> None:
        waiter = self._writers.popleft()
        waiter.admitted = True
        self._writing = True
        waiter.event.set()

    def _release_read(self) -> None:
        self._readers -= 1
        if not self._readers and self._writers:
            self._admit_writer()

    def _release_write(self) -> None:
        self._writing = False
        if self._queued_reads:
            self._admit_reads()
        elif self._writers:
            self._admit_writer()

    def _withdraw_read(self, waiter: _Waiter) -> None:
        self._queued_reads.remove(waiter)

    def _withdraw_write(self, waiter: _Waiter) -> None:
        self._writers.remove(waiter)
        if not self._writers and not self._writing:
            self._admit_reads()


def _round_trips(exc: BaseException) -> bool:
    try:
        pickle.loads(pickle.dumps(exc))
    except Exception:
        return False
    return True


def call_rebuildable(fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    """Call ``fn``, so that whatever it raises can be pickled and rebuilt in another process.

    Raises:
        RuntimeError: ``fn`` raised an exception that cannot be rebuilt; the
            message names the original type and its message.
    """
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        if _round_trips(exc):
            raise
        raise RuntimeError(f"{type(exc).__name__}: {exc}") from None


def run_in_worker(fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    """Call ``fn`` inside a worker process through :func:`call_rebuildable`.

    Points file descriptor 2 at ``/dev/null`` first: anyio connects it to a
    pipe nobody reads, so output there would fill the pipe and hang the worker.
    """
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 2)
    os.close(devnull)
    return call_rebuildable(fn, args, kwargs)


def worker_died(tool_name: str) -> dict[str, str]:
    """The result of a read whose worker process died."""
    return {"error": f"{tool_name}: the worker process died (killed, or out of memory); nothing was written"}


class Registrar:
    """Registers tools on one server, each labelled read or write, all sharing one gate."""

    def __init__(self, mcp: FastMCP, read_workers: int) -> None:
        self._mcp = mcp
        self._gate = Gate()
        self._slots = anyio.CapacityLimiter(read_workers)
        self._unbounded = anyio.CapacityLimiter(math.inf)
        self.kinds: dict[str, Kind] = {}

    def register(self, fn: Callable[..., Any], *, kind: Kind) -> None:
        """Register ``fn`` as a tool: a read runs in a worker process, a write in this one."""
        wrap = {"read": self._read, "write": self._write}[kind]
        self._mcp.tool()(wrap(fn))
        self.kinds[fn.__name__] = kind

    def _read(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        async def read(*args: Any, **kwargs: Any) -> Any:
            async with self._slots, self._gate.read():
                try:
                    return await to_process.run_sync(
                        run_in_worker, fn, args, kwargs, cancellable=True, limiter=self._unbounded
                    )
                except BrokenWorkerProcess:
                    return worker_died(fn.__name__)

        return read

    def _write(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        async def write(*args: Any, **kwargs: Any) -> Any:
            async with self._gate.write():
                return fn(*args, **kwargs)

        return write
