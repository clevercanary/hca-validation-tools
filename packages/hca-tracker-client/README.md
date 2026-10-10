# hca-tracker-client

Find, download, upload and report on atlas files from the HCA Atlas Tracker. This is the
library behind [`hca-tracker-mcp`](../hca-tracker-mcp); it holds all the logic, and the
MCP server is a thin wrapper over it.

- **Atlas version selection.** Every call names both the `network` and the
  `atlas` (the tracker's `shortNameSlug`). Nothing is inferred: the same slug
  can exist in more than one network. `generation` picks that generation's
  newest revision (default: the highest generation); `published` considers
  only published versions.
- **Validation results and status.** The file lists carry each file's
  validation summary, and `validation_report()` the validators' messages.
  The tracker shows a CAP ingest status and an HCA Tier 1 status in its own
  lists but does not serve them from its API, so `status.py` mirrors the
  tracker's rules (`getCapIngestStatusFromParameters` and
  `getHcaTier1ValidationStatus` in hca-atlas-tracker's
  `app/apis/catalog/hca-atlas-tracker/common/utils.ts`), with the tracker's
  test cases ported to `tests/test_status.py`. A change to either rule in the
  tracker has to be made here too.
- **Downloads run in aria2.** `aria2c` fetches each file over 16 parallel
  connections, resumes partial files, queues downloads beyond a limit, and
  verifies the file's SHA-256 before it is given its final name.
- **Downloads outlive the caller.** aria2 runs as a detached daemon, so a
  download keeps going after the MCP server or the Claude session ends, and a
  new session can follow it.
- **Uploads drive `hca-smart-sync`.** A curated file goes back to the
  tracker's bucket through the engine of the CLI the atlas teams use, so it
  lands under the same prefix with the same `source-sha256` metadata; only
  the terminal front end is replaced. Uploads run in a detached worker and
  outlive the caller too. See [How an upload works](#how-an-upload-works).

## Install

Not published to PyPI. Install from the git repo or a local checkout:

```bash
uv pip install "git+https://github.com/clevercanary/hca-validation-tools@main#subdirectory=packages/hca-tracker-client"
uv pip install ./packages/hca-tracker-client   # from a checkout
```

The base package has no dependencies. Uploading needs the `upload` extra,
which brings `hca-smart-sync` (and with it boto3, rich, typer):

```bash
uv pip install "hca-tracker-client[upload] @ git+https://github.com/clevercanary/hca-validation-tools@main#subdirectory=packages/hca-tracker-client"
```

Without it, listing and downloading work and the upload calls raise a
`ConfigError` naming the extra. `hca-smart-sync` is pinned to `0.4.*`: the
engine's names and return shapes are not a declared API, and
`tests/test_uploads.py::test_smart_sync_import_contract` pins what is used.

Most users want the MCP server instead; see
[`hca-tracker-mcp`](../hca-tracker-mcp#install).

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

For uploads, in addition: `s5cmd` (`brew install peak/tap/s5cmd`) or the AWS
CLI on `PATH` for the transfer (`s5cmd` is preferred, as in `hca-smart-sync`),
and an AWS profile with access to the tracker bucket.

## Configuration

Read from the environment, falling back to a `.env` file in the working
directory (only `HCA_TRACKER_*` keys are read from it):

| Variable | Default | |
|---|---|---|
| `HCA_TRACKER_URL` | — | Tracker base URL, e.g. the dev tracker |
| `HCA_TRACKER_API_TOKEN` | — | Read-only API token, created at `<tracker>/api-token` |
| `HCA_TRACKER_CACHE_DIR` | `~/.cache/hca-tracker` | Where files and job state live |
| `HCA_TRACKER_MAX_CONCURRENT` | `2` | Downloads running at once; the rest queue |
| `HCA_TRACKER_ENVIRONMENT` | by host | `dev` or `prod`: which environment the tracker is, when its host is not the prod or dev tracker's (a local test one) |

The token and presigned download URLs are never logged, returned, or put in an
error message.

The AWS profile uploads sign with is not read from here. It is the `profile`
saved by `hca-smart-sync config` in `~/.hca-smart-sync/config.yaml`, so this
client and the CLI sign the same way; else `AWS_PROFILE`, which the AWS tools
honour on their own. `HCA_AWS_PROFILE` is this package's own override, which
the CLI does not read. With none set, uploads refuse.

## Usage

```python
from hca_tracker_client import (
    Downloads, TrackerClient, Uploads, get_atlas, list_atlases, list_files, load_config, validation_report,
)

config = load_config()
tracker = TrackerClient(*config.require_tracker())

list_atlases(tracker)                                   # find the network/atlas pair
files = list_files(tracker, "lung", "adipose", "integrated")   # or "source"; rows carry validation + status
get_atlas(tracker, "lung", "adipose")                   # status, leads with tracker account, counts, tasks
row = files["files"][0]
validation_report(tracker, "lung", "adipose", row["entry_id"], row["kind"], validator="hca_schema")

downloads = Downloads(config)
job = downloads.start("lung", "adipose", "lung-adipose-r2.h5ad")
downloads.status(job["job_id"])   # queued, downloading, verifying, done, failed, ...
downloads.cancel(job["job_id"])   # keeps the partial file; start() resumes it
downloads.list_files()
downloads.delete(job["path"])

uploads = Uploads(config)                                   # needs the upload extra
uploads.plan("gut", "gut", "source-datasets", "~/outbox")   # what start() would upload; no side effects
job = uploads.start("gut", "gut", "source-datasets", "~/outbox", environment="dev")
uploads.status(job["job_id"])     # queued, uploading, done, failed, interrupted
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

## How an upload works

`hca-smart-sync` uploads a *folder*: every `.h5ad` directly in it, hashed and
compared with the bucket, and a manifest written beside them. So does
`Uploads`; stage the files you mean to upload in a folder of their own.

`plan()` and `start()` run the same checks, in this order, before anything
touches the bucket (with one difference: a missing transfer tool, `s5cmd` or
`aws`, is a warning on the plan, so you still see what would upload, and a
refusal on `start()`):

1. The bucket matches the tracker. `environment` picks the bucket (`dev`,
   the default, is `hca-atlas-tracker-data-dev`; `prod` is
   `hca-atlas-tracker-data`, the two literals in `hca-smart-sync`'s CLI). The
   configured tracker ingests from exactly one of them, and a file uploaded to
   the other would never appear in its lists, so an `environment` that
   disagrees with `HCA_TRACKER_URL`'s host is refused. No other bucket is
   reachable.
2. `local_path` is a folder.
3. The atlas resolves on the tracker (as for every call: the newest revision
   of the chosen generation), and `hca-smart-sync` knows it. Its name in the
   CLI's `ATLAS_BIONETWORKS` map is `<slug>-v<generation>` (`gut-v1`), and
   the map decides the bionetwork. It must equal the tracker's network for
   the atlas; a mismatch, or an atlas missing from the map, is refused with
   both values in the message, so a stale map is an error rather than a file
   under the wrong prefix.
4. The selected version is a draft. The tracker refuses an upload to a
   published version (in its own log, after the transfer), so a published one
   is refused here, before it; create the next revision in the tracker first.

The prefix is `s3://<bucket>/<bionetwork>/<folder>/<file-type>/`, with
`file-type` `source-datasets` or `integrated-objects` and `folder` the name
the tracker reads the version from: `<slug>-v<generation>` for revision 0
(`gut-v1` is v1.0) and `<slug>-v<generation>-<revision>` after that (`gut-v1-1`
is v1.1). For revision 0 that is byte for byte the CLI's path. The CLI's map
names only the revision-0 form, so the CLI itself cannot upload to a later
revision; this client can, because it takes the revision from the tracker.
5. An AWS profile is configured (see Configuration) and exists in
   `~/.aws/config`.
6. The engine's own access check: the profile can list the target.

`plan()` then returns `sync(plan_only=True)`: per file `name`, `size_bytes`,
`sha256` and `reason` (`new`, `changed`, or `forced`), the files found
`up_to_date` (same SHA-256 already in the bucket: skipped), the target bucket
and prefix, the profile, and the transfer tool (`s5cmd`, or `aws` as the
fallback). It has no side effects and can be called freely.

`start()` runs that plan, then spawns the worker
(`python -m hca_tracker_client.upload_worker`) in a session of its own, with
its output on `<cache>/uploads/<job_id>.log`, and returns the job id with the
plan it is executing. Nothing is started when every file is up to date;
`force=True` re-uploads them. One upload per folder at a time: a second
`start()` for a folder with a job in flight returns that job.

The worker runs the real `sync()`: the manifest is written in the folder, each
file goes up with `x-amz-meta-source-sha256`, then the manifest goes to the
atlas's `manifests/` prefix. The job record in `<cache>/uploads/<job_id>.json`
is updated as each file completes; `status()` reports `files_done`,
`bytes_done`, the file in flight and, for it, the transfer tool's own latest
progress line from the log (as the CLI shows it; it is not parsed). A job ends
`done` with `manifest_path`, or `failed` naming the files not uploaded. If the
worker dies without recording an outcome, `status()` reports the job
`interrupted`. Either way, `start()` again plans only what the bucket still
lacks.

The plan `start()` returned is the plan the worker runs: it refuses a folder
in which any `.h5ad` was added, removed, or changed since, judged by name,
size and modification time. That check reads no file content, so an edit
that keeps both the size and the modification time is not seen, and the
engine would then upload bytes other than the SHA-256 the plan showed (the
limit rsync and the `hca-smart-sync` CLI share). Re-hashing at transfer time
is the subject of #741.

**Closing the loop.** Once the tracker has ingested the file, `list_files()`
shows its new revision (`uploaded_at`, `wip_number`) and `validation_report()`
the validators' verdict.

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
