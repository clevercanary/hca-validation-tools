"""Refuse and record every lookup of an AWS host, so a test that misses a mock fails instead of calling AWS."""

import json
import os
import socket
import sys
from pathlib import Path

LOG_ENV = "AWS_GUARD_LOG"
AWS_HOST_SUFFIXES = (".amazonaws.com", ".amazonaws.com.cn", ".api.aws")
# Instance metadata (IPv4 and IPv6) and the container credentials endpoint
AWS_HOSTS = frozenset({"169.254.169.254", "fd00:ec2::254", "169.254.170.2"})


class AwsHostRefused(BaseException):
    """A lookup of an AWS host; not an ``Exception``, so ``except Exception`` handlers cannot swallow it."""


def is_aws_host(host: str) -> bool:
    """Return whether ``host`` names AWS, ignoring case and a trailing dot."""
    name = host.lower().rstrip(".")
    return name in AWS_HOSTS or name.endswith(AWS_HOST_SUFFIXES)


def install() -> None:
    """Wrap ``socket.getaddrinfo`` in this process; calling it again changes nothing.

    A lookup of an AWS host appends ``{host, pid, argv}`` as a JSON line to the file named by
    ``AWS_GUARD_LOG``, when that variable is set, then raises ``AwsHostRefused``.
    """
    real = socket.getaddrinfo
    if getattr(real, "aws_guard", False):
        return

    def guarded(host, *args, **kwargs):
        name = host.decode() if isinstance(host, bytes) else str(host)
        if is_aws_host(name):
            log = os.environ.get(LOG_ENV)
            if log:
                with Path(log).open("a") as f:
                    f.write(json.dumps({"host": name, "pid": os.getpid(), "argv": sys.argv}) + "\n")
            raise AwsHostRefused(f"aws_guard refused a lookup of {name}; mock the call with moto")
        return real(host, *args, **kwargs)

    guarded.aws_guard = True  # type: ignore[attr-defined]
    socket.getaddrinfo = guarded
