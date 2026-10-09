# hca-tracker-client

Find and download atlas files from the HCA Atlas Tracker. This is the library
behind [`hca-tracker-mcp`](../hca-tracker-mcp); it holds all the logic, and the
MCP server is a thin wrapper over it.

- **Atlas version selection.** Every call names both the `network` and the
  `atlas` (the tracker's `shortNameSlug`). Nothing is inferred: the same slug
  can exist in more than one network. `generation` picks that generation's
  newest revision (default: the highest generation); `published` considers
  only published versions.
- **Downloads run in aria2.** `aria2c` fetches each file over 16 parallel
  connections, resumes partial files, queues downloads beyond a limit, and
  verifies the file's SHA-256 before it is given its final name.
- **Downloads outlive the caller.** aria2 runs as a detached daemon, so a
  download keeps going after the MCP server or the Claude session ends, and a
  new session can follow it.

## Requirements

`aria2c` 1.35.0 or newer on `PATH`. There is no fallback to a slower
downloader.

| System | Install |
|---|---|
| macOS | `brew install aria2` |
| Debian / Ubuntu | `apt install aria2` |
| Fedora | `dnf install aria2` |
| RHEL, Amazon Linux 2 | enable EPEL, then `dnf install aria2` / `yum install aria2` |
| Anywhere with conda | `conda install -c conda-forge aria2` |

macOS and Linux only: the daemon lock uses `fcntl`.

## Configuration

Read from the environment, falling back to a `.env` file in the working
directory (only `HCA_TRACKER_*` keys are read from it):

| Variable | Default | |
|---|---|---|
| `HCA_TRACKER_URL` | — | Tracker base URL, e.g. the dev tracker |
| `HCA_TRACKER_API_TOKEN` | — | Read-only API token, created at `<tracker>/api-token` |
| `HCA_TRACKER_CACHE_DIR` | `~/.cache/hca-tracker` | Where files and job state live |
| `HCA_TRACKER_MAX_CONCURRENT` | `2` | Downloads running at once; the rest queue |

The token and presigned download URLs are never logged, returned, or put in an
error message.

## Usage

```python
from hca_tracker_client import Downloads, TrackerClient, list_atlases, list_files, load_config

config = load_config()
tracker = TrackerClient(*config.require_tracker())

list_atlases(tracker)                                   # find the network/atlas pair
list_files(tracker, "lung", "adipose", "integrated")    # or "source"

downloads = Downloads(config)
job = downloads.start("lung", "adipose", "lung-adipose-r2.h5ad")
downloads.status(job["job_id"])   # queued, downloading, verifying, done, failed, ...
downloads.cancel(job["job_id"])   # keeps the partial file; start() resumes it
downloads.list_files()
downloads.delete(job["path"])
```

## How a download works

`start()` runs every check before anything is fetched:

1. The atlas version and file exist.
2. The download link works. A 1-byte ranged GET confirms access and reads the
   `x-amz-meta-source-sha256` header that `hca-smart-sync` attaches on upload.
3. The file is not already downloaded. A verified copy is returned as is. If
   any other file is at the final path when the download starts, `start()`
   refuses. That is checked only at the start: a file that appears at the
   final path while the download runs is replaced when it completes.
4. `aria2c` is installed and recent enough.
5. The destination folder is writable.
6. There is enough free space for the file, for the rest of the downloads
   already running or queued on that disk, and for a margin of 10% of the file
   or 5 GB, whichever is larger.

The tracker's file name is used as is; one containing control characters or a
backslash is refused, never renamed.

Files go to `<cache>/<network>/<atlas>_<version>/<filename>`, where the file
name is the tracker's versioned name (`dest_dir` overrides the folder). While
downloading, the file is `<filename>.part`, with aria2's control file
`<filename>.part.aria2` beside it.

**Verification.** aria2 hashes the whole file and compares it with
`source-sha256` before reporting the download complete; only then is `.part`
renamed to the final name. On a mismatch the job fails with error code 32 and
the `.part` file is kept, so the cause can be investigated. `start()` refuses to
reuse it: delete it first, or pass `restart=True`. A file uploaded without
`hca-smart-sync` has no checksum and is refused before anything is downloaded.

**Resume.** A download stopped by a cancel, a crash or an expired link (they
last 48 hours) resumes when `start()` is called again: it fetches a fresh link
and aria2 continues from its control file.

## The aria2 daemon

One daemon runs per cache folder, started on first use. Its state is in
`<cache>/aria2/`, readable only by the owner:

- `aria2.conf` — the RPC port and secret (on localhost only). The secret is not
  on the command line, where `ps` would show it.
- `session` — unfinished downloads, restored when the daemon restarts. It holds
  presigned URLs, which expire after 48 hours.
- `on-complete.sh`, `on-error.sh` — hooks aria2 runs when a download ends.
  They record the outcome in `<cache>/jobs/<job_id>.json`.

The daemon is trusted only while the `aria2c` recorded in `<cache>/aria2/pid` is
alive; a stale port is never reused. It stays running when idle. To stop it:

```python
from hca_tracker_client.daemon import shutdown
shutdown(config.cache_dir)
```

`start()`, `status()` and `cancel()` start it again when jobs are unfinished,
restoring them; `list_files()` and `delete()` never start it.
