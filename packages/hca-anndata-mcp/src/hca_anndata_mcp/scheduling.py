"""Run read tools in parallel worker processes and write tools one at a time.

The rules are in ``docs/anndata-mcp-concurrency-contract.md``.
"""

from __future__ import annotations

import functools
import math
import os
import pickle
import re
from collections import deque
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import anyio
from anyio import BrokenWorkerProcess, to_process

if TYPE_CHECKING:
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


class Gate:
    """A readers-writer lock: reads share it, a write holds it alone.

    A waiting write keeps new reads out. When a write releases the gate,
    every read waiting at that moment takes it before the next write.
    Writes start in the order they arrived.
    """

    def __init__(self) -> None:
        self._readers = 0
        self._writing = False
        self._writers: deque[anyio.Event] = deque()
        self._queued_reads: deque[anyio.Event] = deque()

    @asynccontextmanager
    async def read(self) -> AsyncGenerator[None, None]:
        if self._writing or self._writers:
            await self._wait(self._queued_reads, self._release_read)
        else:
            self._readers += 1
        try:
            yield
        finally:
            self._release_read()

    @asynccontextmanager
    async def write(self) -> AsyncGenerator[None, None]:
        if self._writing or self._readers or self._writers:
            await self._wait(self._writers, self._release_write)
        else:
            self._writing = True
        try:
            yield
        finally:
            self._release_write()

    async def _wait(self, queue: deque[anyio.Event], release: Callable[[], None]) -> None:
        admitted = anyio.Event()
        queue.append(admitted)
        try:
            await admitted.wait()
        except BaseException:
            # Cancelled: give back the grant if it arrived at the same moment, else the place.
            if admitted.is_set():
                release()
            else:
                queue.remove(admitted)
                if not self._writing and not self._writers:
                    self._admit_reads()
            raise

    def _admit_reads(self) -> None:
        self._readers += len(self._queued_reads)
        while self._queued_reads:
            self._queued_reads.popleft().set()

    def _admit_writer(self) -> None:
        self._writing = True
        self._writers.popleft().set()

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


def _round_trips(exc: BaseException) -> bool:
    try:
        pickle.loads(pickle.dumps(exc))
    except Exception:
        return False
    return True


def call_rebuildable(fn: Callable[..., Any], /, **kwargs: Any) -> Any:
    """Call ``fn``, so that whatever it raises can be pickled and rebuilt in another process.

    Raises:
        RuntimeError: ``fn`` raised an exception that cannot be rebuilt; the
            message names the original type and its message.
    """
    try:
        return fn(**kwargs)
    except Exception as exc:
        if _round_trips(exc):
            raise
        raise RuntimeError(f"{type(exc).__name__}: {exc}") from None


def run_in_worker(fn: Callable[..., Any], /, **kwargs: Any) -> Any:
    """Call ``fn`` inside a worker process through :func:`call_rebuildable`.

    Points file descriptor 2 at ``/dev/null`` first: anyio connects it to a
    pipe nobody reads, so output there would fill the pipe and hang the worker.
    """
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 2)
    os.close(devnull)
    return call_rebuildable(fn, **kwargs)


def worker_died(tool_name: str) -> dict[str, str]:
    """The result of a read whose worker process died."""
    return {"error": f"{tool_name}: the worker process died (killed, or out of memory); nothing was written"}


@dataclass(frozen=True)
class Registered:
    """A registered tool: the function as written, and its label."""

    fn: Callable[..., Any]
    kind: Kind


class Registrar:
    """Registers tools on one server, each labelled read or write, all sharing one gate."""

    def __init__(self, mcp: FastMCP, read_workers: int) -> None:
        self._mcp = mcp
        self._gate = Gate()
        self._slots = anyio.CapacityLimiter(read_workers)
        self._unbounded = anyio.CapacityLimiter(math.inf)
        self._pings = read_workers + 1
        self.tools: dict[str, Registered] = {}

    def register(self, fn: Callable[..., Any], *, kind: Kind) -> None:
        """Register ``fn`` as a tool: a read runs in a worker process, a write in this one.

        Raises:
            TypeError: ``fn`` is a read that a worker cannot find by its
                ``__module__`` and ``__qualname__``.
        """
        if kind == "read" and not _pickles_by_reference(fn):
            raise TypeError(f"{fn.__name__}: a worker cannot find it by its __module__ and __qualname__")
        wrap = {"read": self._read, "write": self._write}[kind]
        self._mcp.tool()(wrap(fn))
        self.tools[fn.__name__] = Registered(fn, kind)

    def _read(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        async def read(**kwargs: Any) -> Any:
            async with self._slots, self._gate.read():
                await self._find_live_worker()
                try:
                    return await to_process.run_sync(
                        functools.partial(run_in_worker, fn, **kwargs), cancellable=True, limiter=self._unbounded
                    )
                except BrokenWorkerProcess:
                    return worker_died(fn.__name__)

        return read

    async def _find_live_worker(self) -> None:
        # anyio hands a call to an idle worker that has died until the event loop sees
        # the exit. A ping runs nothing, so unlike a read it is safe to repeat, and each
        # failed ping discards one dead worker; the read then reuses the worker that answered.
        for _ in range(self._pings):
            try:
                await to_process.run_sync(os.getpid, cancellable=True, limiter=self._unbounded)
                return
            except BrokenWorkerProcess:
                continue

    def _write(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        async def write(**kwargs: Any) -> Any:
            async with self._gate.write():
                return fn(**kwargs)

        return write


def _pickles_by_reference(fn: Callable[..., Any]) -> bool:
    try:
        return pickle.loads(pickle.dumps(fn)) is fn
    except (pickle.PicklingError, AttributeError):
        return False
