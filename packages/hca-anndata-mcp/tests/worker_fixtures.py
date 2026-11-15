"""Tools for the worker tests; a worker process imports them by module name."""

import os
import signal
from pathlib import Path


def rendezvous(fifo: str, end: str) -> dict:
    """Open one end of ``fifo``; the open blocks until another process opens the other end."""
    with Path(fifo).open("w" if end == "write" else "r"):
        pass
    return {"pid": os.getpid()}


def block(started: str, never: str) -> dict:
    """Open ``started`` for writing, then block for good opening ``never``, which nobody writes."""
    with Path(started).open("w"):
        pass
    with Path(never).open("r"):
        pass
    return {}


def pid() -> dict:
    return {"pid": os.getpid()}


def die() -> dict:
    os.kill(os.getpid(), signal.SIGKILL)
    return {}


def flood_stderr() -> dict:
    for _ in range(10):
        os.write(2, b"x" * 100_000)
    return {"flooded": True}


class TwoArgError(Exception):
    def __init__(self, code: int, detail: str) -> None:
        super().__init__(f"{code}: {detail}")


def raise_two_arg_error() -> dict:
    raise TwoArgError(7, "cannot be rebuilt")


def raise_value_error() -> dict:
    raise ValueError("bad value")


def write_marker() -> dict:
    return {"written": True, "pid": os.getpid()}
