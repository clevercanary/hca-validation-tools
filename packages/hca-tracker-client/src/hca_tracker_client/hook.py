"""Entry point aria2 runs when a download completes or fails.

Invoked as ``python -m hca_tracker_client.hook <complete|error> <cache_dir>
<gid> <file count> <path>`` by the wrapper scripts the daemon module writes.
It runs in its own process, so it works with no MCP server running.
"""

import contextlib
import http.client
import sys
import xmlrpc.client
from pathlib import Path

from .daemon import Aria2Error, connect
from .outcome import finalize, record_error
from .store import ACTIVE, JobStore


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        return 2
    event, cache_dir, gid = argv[0], Path(argv[1]), argv[2]
    store = JobStore(cache_dir)
    job = store.load(gid)
    if job is None or job.state not in ACTIVE:
        return 0
    if event == "complete":
        finalize(job, store)
    elif event == "error":
        aria2 = connect(cache_dir)
        status: dict = {}
        if aria2 is not None:
            with contextlib.suppress(Aria2Error, OSError, http.client.HTTPException, xmlrpc.client.ProtocolError):
                status = aria2.tell_status(gid)
        record_error(job, store, status, aria2)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
