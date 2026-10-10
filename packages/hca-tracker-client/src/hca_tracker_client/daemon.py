"""The aria2 daemon that runs downloads for one cache folder.

aria2c runs in its own session with its RPC server on localhost, so a
download outlives the MCP server and the Claude session that started it. Its
session file brings unfinished downloads back after a crash or reboot, and it
runs our hook (``python -m hca_tracker_client.hook``) when a download completes
or fails.

Everything lives in ``<cache>/aria2/``, a folder only the owner can read: the
config file holds the RPC secret, and the session file holds presigned URLs.
The secret goes in the config file rather than on the command line, where any
local user could read it with ``ps``.
"""

import contextlib
import http.client
import os
import secrets
import shlex
import signal
import socket
import subprocess
import sys
import time
import xml.parsers.expat
import xmlrpc.client
from pathlib import Path

from .config import PREFIX
from .errors import TrackerError, redact
from .store import file_lock

CONF = "aria2.conf"
SESSION = "session"
PIDFILE = "pid"
STATUS_KEYS = [
    "gid",
    "status",
    "totalLength",
    "completedLength",
    "downloadSpeed",
    "errorCode",
    "errorMessage",
    "verifiedLength",
    "verifyIntegrityPending",
]


class Aria2Error(TrackerError):
    """An RPC call to aria2 failed: aria2 rejected it, or the daemon could not be reached."""

    @property
    def not_found(self) -> bool:
        return "is not found" in str(self)


class _TimeoutTransport(xmlrpc.client.Transport):
    def __init__(self, timeout: float):
        super().__init__()
        self.timeout = timeout

    def make_connection(self, host):  # type: ignore[override]
        connection = super().make_connection(host)
        connection.timeout = self.timeout
        return connection


class Aria2:
    """XML-RPC client for one running aria2 daemon.

    Status calls ask for an explicit list of keys (``STATUS_KEYS``) and never
    for ``files`` or ``uris``, which hold the presigned URL.
    """

    def __init__(self, port: int, secret: str, timeout: float = 10):
        self._token = f"token:{secret}"
        self._proxy = xmlrpc.client.ServerProxy(
            f"http://127.0.0.1:{port}/rpc", transport=_TimeoutTransport(timeout), allow_none=False
        )

    def call(self, method: str, *params):
        """Call an aria2 method; every failure, including an unreachable daemon, raises Aria2Error."""
        try:
            return getattr(self._proxy.aria2, method)(self._token, *params)
        except xmlrpc.client.Fault as fault:
            raise Aria2Error(redact(f"aria2 {method}: {fault.faultString}", self._token)) from None
        except (
            OSError,
            http.client.HTTPException,
            xmlrpc.client.ProtocolError,
            xmlrpc.client.ResponseError,
            xml.parsers.expat.ExpatError,
        ) as error:
            raise Aria2Error(redact(f"aria2 {method}: {type(error).__name__}: {error}", self._token)) from None

    def tell_status(self, gid: str) -> dict:
        return self.call("tellStatus", gid, STATUS_KEYS)

    def version(self) -> str:
        return self.call("getVersion")["version"]


def daemon_dir(cache_dir: Path) -> Path:
    return cache_dir / "aria2"


def _read_conf(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _write_private(path: Path, text: str, mode: int = 0o600) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    path.chmod(mode)


def _write_hook(directory: Path, cache_dir: Path, event: str) -> Path:
    """Write the shell wrapper aria2 runs for an event; aria2 passes (gid, file count, path)."""
    script = directory / f"on-{event}.sh"
    command = shlex.join([sys.executable, "-m", "hca_tracker_client.hook", event, str(cache_dir)])
    _write_private(script, f'#!/bin/sh\nexec {command} "$@"\n', mode=0o700)
    return script


def _conf_text(directory: Path, port: int, secret: str, max_concurrent: int, on_complete: Path, on_error: Path) -> str:
    session = directory / SESSION
    options = {
        "enable-rpc": "true",
        "rpc-listen-all": "false",
        "rpc-listen-port": str(port),
        "rpc-secret": secret,
        "max-concurrent-downloads": str(max_concurrent),
        # The issue's engine settings: 16 connections per file, 64 MiB pieces.
        "max-connection-per-server": "16",
        "split": "16",
        "min-split-size": "64M",
        "continue": "true",
        "file-allocation": "none",
        # Never write to a renamed file (aria2 would otherwise save to
        # name.1.part beside an existing one) or overwrite one.
        "auto-file-renaming": "false",
        "allow-overwrite": "false",
        "save-session": str(session),
        "save-session-interval": "10",
        "input-file": str(session),
        "on-download-complete": str(on_complete),
        "on-download-error": str(on_error),
        "quiet": "true",
    }
    return "".join(f"{key}={value}\n" for key, value in options.items())


def _pid(directory: Path) -> int | None:
    try:
        return int((directory / PIDFILE).read_text().strip())
    except (OSError, ValueError):
        return None


def process_matches(pid: int, marker: str) -> bool:
    """True if ``pid`` is alive and its command line contains ``marker``: not a reused pid of something else."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    result = subprocess.run(["ps", "-ww", "-p", str(pid), "-o", "args="], capture_output=True, text=True)
    return marker in result.stdout


def _is_daemon(directory: Path, pid: int) -> bool:
    """True if pid is the aria2c started with this folder's config."""
    return process_matches(pid, f"--conf-path={directory / CONF}")


def connect(cache_dir: Path) -> Aria2 | None:
    """Return a client for the cache's daemon if it is running, else None.

    The port is trusted only while the aria2c recorded in the pidfile is alive
    and holds it. Once that process is gone, another local user could listen on
    the old port and would be sent the next presigned URL.
    """
    directory = daemon_dir(cache_dir)
    conf = directory / CONF
    pid = _pid(directory)
    if not conf.is_file() or pid is None or not _is_daemon(directory, pid):
        return None
    values = _read_conf(conf)
    try:
        client = Aria2(int(values["rpc-listen-port"]), values["rpc-secret"], timeout=5)
        client.version()
    except (KeyError, ValueError, Aria2Error):
        return None
    return client


def _wait_exit(directory: Path, pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while _is_daemon(directory, pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.1)
    return True


def _stop_process(directory: Path, grace: float = 10) -> None:
    """Make sure the last daemon process for this folder has exited.

    aria2 stops answering RPC as soon as it starts shutting down, but keeps
    downloading for a few seconds while it halts. A new daemon started in that
    window would write the same .part files as the old one, so wait for the
    process itself, and end it if it does not exit.
    """
    pid = _pid(directory)
    if pid is None or _wait_exit(directory, pid, grace):
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, sig)
        if _wait_exit(directory, pid, 5):
            return


def ensure_daemon(cache_dir: Path, aria2c: str, max_concurrent: int, timeout: float = 15) -> Aria2:
    """Return a client for the cache's daemon, starting the daemon if it is not running.

    The daemon is started in its own session, so it outlives the process that
    started it, and its pid is recorded so a restart can wait for the old one.
    Each start uses a new port and secret.
    """
    directory = daemon_dir(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    with file_lock(directory / "lock"):
        client = connect(cache_dir)
        if client is not None:
            client.call("changeGlobalOption", {"max-concurrent-downloads": str(max_concurrent)})
            return client

        _stop_process(directory)
        port, secret = _free_port(), secrets.token_hex(16)
        on_complete = _write_hook(directory, cache_dir, "complete")
        on_error = _write_hook(directory, cache_dir, "error")
        conf = _conf_text(directory, port, secret, max_concurrent, on_complete, on_error)
        _write_private(directory / CONF, conf)
        session = directory / SESSION
        if not session.exists():
            _write_private(session, "")

        # The daemon and its hooks don't need the tracker token; keep it out of
        # their environment.
        env = {key: value for key, value in os.environ.items() if not key.startswith(PREFIX)}
        errors = directory / "daemon.err"
        try:
            with errors.open("w") as stderr:
                process = subprocess.Popen(
                    [aria2c, f"--conf-path={directory / CONF}"],
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=stderr,
                    start_new_session=True,
                    close_fds=True,
                    cwd=directory,
                )
        except OSError as error:
            raise TrackerError(f"Could not start the aria2 daemon: {error}") from None
        _write_private(directory / PIDFILE, str(process.pid))

        client = Aria2(port, secret)
        deadline = time.monotonic() + timeout
        while True:
            try:
                client.version()
                return client
            except Aria2Error:
                code = process.poll()
                if code is not None:
                    output = redact(errors.read_text().strip(), secret)
                    raise TrackerError(f"The aria2 daemon exited on start (exit {code}): {output}") from None
                if time.monotonic() > deadline:
                    raise TrackerError(
                        f"The aria2 daemon did not answer on port {port} within {timeout:.0f}s"
                    ) from None
                time.sleep(0.1)


def shutdown(cache_dir: Path) -> bool:
    """Stop the cache's daemon, saving its session; True if one was running.

    Returns once the process has exited, not just stopped answering.
    """
    directory = daemon_dir(cache_dir)
    client = connect(cache_dir)
    if client is not None:
        with contextlib.suppress(Aria2Error):
            client.call("saveSession")
            client.call("forceShutdown")
    pid = _pid(directory)
    running = client is not None or (pid is not None and _is_daemon(directory, pid))
    if directory.is_dir():
        _stop_process(directory)
    return running
