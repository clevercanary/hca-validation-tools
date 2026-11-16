"""Run read tools in parallel worker processes and write tools one at a time.

The rules are in ``docs/anndata-mcp-concurrency-contract.md``.
"""

from __future__ import annotations

import contextlib
import ctypes
import functools
import math
import os
import pickle
import re
import sys
from collections import deque
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import anyio
from anyio import BrokenWorkerProcess, to_process

if TYPE_CHECKING:
    from fastmcp import FastMCP

Kind = Literal["fast", "slow", "write"]

READ_WORKERS_VAR = "HCA_ANNDATA_MCP_READ_WORKERS"
SLOW_WORKERS_VAR = "HCA_ANNDATA_MCP_SLOW_WORKERS"
RETIRE_GIB_VAR = "HCA_ANNDATA_MCP_RETIRE_GIB"
DEFAULT_READ_WORKERS = 16
DEFAULT_RETIRE_GIB = 3.0


@dataclass(frozen=True)
class Settings:
    """N read workers, ``slow_workers`` of them for slow reads, and the memory an idle worker may keep."""

    read_workers: int
    slow_workers: int
    retire_bytes: int


def _count(environ: Mapping[str, str], var: str) -> int | None:
    raw = environ.get(var)
    if raw is None:
        return None
    if not re.fullmatch(r"[0-9]+", raw) or int(raw) < 1:
        raise ValueError(f"{var} must be a positive integer, got {raw!r}")
    return int(raw)


def settings(environ: Mapping[str, str]) -> Settings:
    """The worker settings from the environment.

    Unset, N is 16, the slow workers half of N rounded down, and the retire limit 3 GiB.

    Raises:
        ValueError: a variable is malformed, N is below 2, or the slow workers are not fewer than N.
    """
    n = _count(environ, READ_WORKERS_VAR) or DEFAULT_READ_WORKERS
    if n < 2:
        raise ValueError(f"{READ_WORKERS_VAR} must be at least 2, one fast and one slow worker, got {n}")
    s = _count(environ, SLOW_WORKERS_VAR) or n // 2
    if s >= n:
        raise ValueError(f"{SLOW_WORKERS_VAR} must be less than {READ_WORKERS_VAR} ({n}), got {s}")
    raw_gib = environ.get(RETIRE_GIB_VAR)
    if raw_gib is None:
        gib = DEFAULT_RETIRE_GIB
    elif re.fullmatch(r"[0-9]+(\.[0-9]+)?", raw_gib) and float(raw_gib) > 0:
        gib = float(raw_gib)
    else:
        raise ValueError(f"{RETIRE_GIB_VAR} must be a positive number of GiB, got {raw_gib!r}")
    return Settings(n, s, int(gib * 2**30))


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


@dataclass(frozen=True)
class Returned:
    """A read's value, with the worker's pid and the memory it held once the read ended."""

    value: Any
    pid: int
    held_bytes: int


@dataclass(frozen=True)
class Raised:
    """A read's exception, with the worker's pid and the memory it held once the read ended."""

    error: Exception
    pid: int
    held_bytes: int


def held_bytes() -> int:
    """The memory this process holds now: anonymous resident memory on Linux, physical footprint on macOS.

    Raises:
        NotImplementedError: on any other platform.
        OSError: macOS refused the read.
    """
    if sys.platform == "linux":
        _, resident, shared, *_ = Path("/proc/self/statm").read_text().split()
        return (int(resident) - int(shared)) * os.sysconf("SC_PAGE_SIZE")
    if sys.platform == "darwin":
        return _macos_footprint()
    raise NotImplementedError(f"held memory is not measured on {sys.platform}")


@functools.cache
def _proc_pid_rusage() -> Callable[..., int]:
    return ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True).proc_pid_rusage


def _macos_footprint() -> int:
    # rusage_info_v4 (<sys/resource.h>): a 16-byte uuid, then uint64 fields; ri_phys_footprint is the 8th.
    info = (ctypes.c_uint64 * 66)()
    if _proc_pid_rusage()(os.getpid(), 4, ctypes.byref(info)) != 0:
        raise OSError(ctypes.get_errno(), "proc_pid_rusage failed")
    return info[2 + 7]


def run_in_worker(fn: Callable[..., Any], /, **kwargs: Any) -> Returned | Raised:
    """Call ``fn`` inside a worker process through :func:`call_rebuildable`, and report what it left behind.

    Points file descriptor 2 at ``/dev/null`` first: anyio connects it to a
    pipe nobody reads, so output there would fill the pipe and hang the worker.
    """
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 2)
    os.close(devnull)
    try:
        value = call_rebuildable(fn, **kwargs)
    except Exception as exc:
        # The traceback's frames hold the read's locals; drop them before measuring.
        exc.__traceback__ = exc.__cause__ = exc.__context__ = None
        return Raised(exc, os.getpid(), held_bytes())
    return Returned(value, os.getpid(), held_bytes())


async def retire(pid: int) -> None:
    """Take worker ``pid`` out of anyio's pool and kill it.

    Call it straight after the read on ``pid`` returns, with no await in between,
    so that worker is still the last one anyio put back as idle and no other
    call can have taken it.

    Raises:
        RuntimeError: the last idle worker is not ``pid``.
    """
    idle = to_process._process_pool_idle_workers.get()
    if not idle or idle[-1][0].pid != pid:
        raise RuntimeError(f"cannot retire worker {pid}: it is not the last idle worker")
    process, _ = idle.pop()
    to_process._process_pool_workers.get().discard(process)
    with contextlib.suppress(ProcessLookupError):
        process.kill()
    with anyio.CancelScope(shield=True):
        await process.aclose()


def worker_died(tool_name: str) -> dict[str, str]:
    """The result of a read whose worker process died."""
    return {"error": f"{tool_name}: the worker process died (killed, or out of memory); nothing was written"}


def raise_if_start_failed(exc: BrokenWorkerProcess) -> None:
    """Re-raise a worker start-up failure with its cause; return for a worker that died later.

    Raises:
        RuntimeError: ``exc`` is a start-up failure; the message names its cause.
    """
    # anyio gives a message only to a start-up failure, with the real exception as its cause.
    if exc.args:
        cause = exc.__cause__
        if cause is None:
            detail = exc.args[0]
        else:
            detail = f"{type(cause).__name__}: {cause}" if str(cause) else type(cause).__name__
        raise RuntimeError(f"a read worker could not start: {detail}") from exc


async def find_live_worker(ping: Callable[[], Awaitable[object]], tries: int) -> None:
    """Await ``ping`` until it answers, at most ``tries`` times, then return either way.

    Only ``BrokenWorkerProcess`` counts as a miss; anything else ``ping`` raises propagates.
    """
    for _ in range(tries):
        try:
            await ping()
            return
        except BrokenWorkerProcess:
            continue


@dataclass(frozen=True)
class Registered:
    """A registered tool: the function as written, and its label."""

    fn: Callable[..., Any]
    kind: Kind


class Registrar:
    """Registers tools on one server, each labelled fast, slow or write, all sharing one gate."""

    def __init__(self, mcp: FastMCP, settings: Settings) -> None:
        self._mcp = mcp
        self._gate = Gate()
        self._lanes = {
            "fast": anyio.CapacityLimiter(settings.read_workers - settings.slow_workers),
            "slow": anyio.CapacityLimiter(settings.slow_workers),
        }
        self._unbounded = anyio.CapacityLimiter(math.inf)
        self._pings = settings.read_workers + 1
        self._retire_bytes = settings.retire_bytes
        self.tools: dict[str, Registered] = {}

    def register(self, fn: Callable[..., Any], *, kind: Kind) -> None:
        """Register ``fn`` as a tool: a fast or slow read runs in a worker process in its lane, a write in this one.

        Raises:
            TypeError: ``fn`` is a read that a worker cannot find by its
                ``__module__`` and ``__qualname__``.
        """
        if kind == "write":
            wrapped = self._write(fn)
        elif _pickles_by_reference(fn):
            wrapped = self._read(fn, self._lanes[kind])
        else:
            raise TypeError(f"{fn.__name__}: a worker cannot find it by its __module__ and __qualname__")
        self._mcp.tool()(wrapped)
        self.tools[fn.__name__] = Registered(fn, kind)

    def _read(self, fn: Callable[..., Any], lane: anyio.CapacityLimiter) -> Callable[..., Any]:
        @functools.wraps(fn)
        async def read(**kwargs: Any) -> Any:
            async with lane, self._gate.read():
                await find_live_worker(self._ping, self._pings)
                try:
                    done = await self._in_worker(functools.partial(run_in_worker, fn, **kwargs))
                except BrokenWorkerProcess:
                    return worker_died(fn.__name__)
                if done.held_bytes > self._retire_bytes:
                    await retire(done.pid)
                if isinstance(done, Raised):
                    raise done.error
                return done.value

        return read

    async def _in_worker(self, call: Callable[[], Any]) -> Any:
        try:
            return await to_process.run_sync(call, cancellable=True, limiter=self._unbounded)
        except BrokenWorkerProcess as exc:
            raise_if_start_failed(exc)
            raise

    async def _ping(self) -> None:
        # anyio hands a call to an idle worker that has died until the event loop sees
        # the exit. A ping runs nothing, so unlike a read it is safe to repeat, and each
        # failed ping discards one dead worker; the read then reuses the worker that answered.
        await self._in_worker(os.getpid)

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
