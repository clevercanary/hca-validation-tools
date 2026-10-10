# hca-tracker-mcp

MCP server to list, download, upload and report on atlas files from the HCA
Atlas Tracker. It is a thin wrapper over
[`hca-tracker-client`](../hca-tracker-client), which holds the logic; see its
README for how version selection, the checks before downloading, verification,
resume, and the checks before uploading work.

It is a separate server from `hca-anndata-mcp`, so that server's tool list stays
focused and the tracker token stays here. The two work together through local
paths: a file this server downloads can be opened with `hca-anndata-mcp`'s
tools.

## Requirements

- `aria2c` 1.35.0 or newer on `PATH` (`brew install aria2`, `apt install aria2`;
  see the client README for other systems).
- A tracker API token (read-only), created at `<tracker>/api-token`.
- For uploads: `s5cmd` (`brew install peak/tap/s5cmd`) or the AWS CLI on
  `PATH`, and an AWS profile with access to the tracker bucket, saved with
  `hca-smart-sync config` (or set as `HCA_AWS_PROFILE`). The server installs
  `hca-smart-sync` itself; the CLI need not be installed.

## Configuration

| Variable | Default | |
|---|---|---|
| `HCA_TRACKER_URL` | — | Tracker base URL |
| `HCA_TRACKER_API_TOKEN` | — | Read-only API token |
| `HCA_TRACKER_CACHE_DIR` | `~/.cache/hca-tracker` | Where files and job state live |
| `HCA_TRACKER_MAX_CONCURRENT` | `2` | Downloads running at once; the rest queue |
| `HCA_TRACKER_ENVIRONMENT` | by host | `dev` or `prod`, when the tracker's host is not the prod or dev tracker's |

Set them in the server's environment, or in a `.env` file in the directory the
server runs in (only `HCA_TRACKER_*` keys are read from it). Claude Code starts
a project's MCP servers in the project root, so the repo `.env` works.

## Install

Not published to PyPI. Run it straight from the git repo with `uvx` (uv
builds `hca-tracker-client` from the same commit), or install it from a local
checkout:

```bash
# from git — nothing to install; uvx builds and caches it
uvx --from "git+https://github.com/clevercanary/hca-validation-tools@main#subdirectory=packages/hca-tracker-mcp" hca-tracker-mcp

# from a checkout
uv tool install ./packages/hca-tracker-mcp            # puts hca-tracker-mcp on PATH
uv tool install --reinstall ./packages/hca-tracker-mcp  # after pulling changes
```

`uvx` caches the build for a ref: pass `--refresh` to pick up a newer `main`,
or pin `@<commit>` instead of `@main` for a fixed version.

## `.mcp.json`

From git, with `uvx`:

```json
{
  "mcpServers": {
    "hca-tracker": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/clevercanary/hca-validation-tools@main#subdirectory=packages/hca-tracker-mcp",
        "hca-tracker-mcp"
      ],
      "env": {
        "HCA_TRACKER_URL": "https://<tracker-host>",
        "HCA_TRACKER_API_TOKEN": "${HCA_TRACKER_API_TOKEN}"
      }
    }
  }
}
```

`${HCA_TRACKER_API_TOKEN}` is expanded from the environment Claude Code runs
in, so the token itself need not be in the file. Leave `env` out to use the
`.env` file instead.

After `uv tool install` from a checkout, use `"command": "hca-tracker-mcp"`.
Or point at the checkout's venv binary (`uv sync` in this folder first):

```json
{
  "mcpServers": {
    "hca-tracker": {
      "command": "/abs/path/to/packages/hca-tracker-mcp/.venv/bin/hca-tracker-mcp"
    }
  }
}
```

## Tools

The tracker side is read-only, matching the token's scope. Uploads go to the
tracker's S3 bucket with the AWS profile above; the tracker ingests from there.

- **list_atlases** — every atlas version: `network`, `atlas` (slug), `version`,
  `is_latest`, `published`. Use it to find the `network`/`atlas` pair.
- **list_integrated_objects** / **list_source_datasets** `(network, atlas,
  generation?, published?)` — an atlas version's files: `name`, `size_bytes`,
  `size`, `file_id`, `integrity_status`, then `entry_id` and `kind` (what
  `get_validation_report` takes), `title`, `cell_count`, `revision`,
  `wip_number`, `uploaded_at`, `is_archived`, `cap_url`, `validation_status`,
  `validation_error_message`, `validation` (`overall_valid` and, per validator
  `cap` / `cellxgene` / `hca_schema` / `hca_cell_annotation`, `valid`,
  `error_count`, `warning_count`; `null` when validation produced no result),
  `tier1_status` (`VALID` / `INVALID` / `UNKNOWN`) and `cap_status`
  (`PUBLISHED` / `CAP_READY` / `CAP_VALIDATION_FAILED` / `NEEDS_VALIDATION` /
  `INFO_REQUIRED` / `NOT_REQUIRED`). Source datasets also carry
  `reprocessed_status`, `publication_status`, `source_study_title` and
  `integrated_objects` (the integrated objects that use the dataset). The
  tracker's lists omit archived files, so `is_archived` is `false` today.
- **get_atlas** `(network, atlas, generation?, published?)` — the atlas
  version's record: `title`, `short_name`, `status` (`IN_PROGRESS` /
  `OC_ENDORSED`), `published_at`, `wave`, `target_completion`,
  `cap_project_url`, `integration_leads` (`name`, `email`, `tracker_account`,
  `last_login`), `counts` (`source_studies`, `source_datasets`,
  `integrated_objects`), `ingestion_tasks` (`cap`, `cellxgene`,
  `hca_data_repository`, each `count` and `completed`),
  `publications` (`doi`, `title`). `tracker_account` is `active`, `disabled`,
  or `unknown` when no tracker user has the lead's contact email; people log
  in with a Google address that can differ from it, so `unknown` is not
  evidence of a missing account. `last_login` is `null` when unknown or when
  the user has never logged in.
- **get_validation_report** `(network, atlas, entry_id, kind, generation?,
  published?, validator?, max_messages?)` — one file's validator messages,
  by the `entry_id` and `kind` of its list row. Returns `file`, `file_id`,
  `entry_id`, `kind`, `validation_status`, `validation_error_message`,
  `max_messages` and `reports`. `reports` holds,
  per validator, `valid`, `started_at`, `finished_at`, `error_count`,
  `warning_count`, `errors`, `warnings` and `truncated`: each list is cut to
  `max_messages` (default 200; a file can carry tens of thousands of warnings)
  while the counts stay complete. `validator` keeps one validator. `reports`
  is `null` when validation never completed; a `job_failed` file has only
  `validation_error_message`.
- **start_download** `(network, atlas, file, generation?, published?, dest_dir?,
  restart?)` — runs the checks, starts the download in the background, and
  returns `job_id`, `path` and `size` at once.
- **download_status** `(job_id?)` — state (`queued`, `downloading`,
  `verifying`, `done`, `failed`, `cancelled`, `interrupted`), bytes done and
  total, rate, time left. Without `job_id`, every job.
- **cancel_download** `(job_id)` — keeps the partial file for resuming.
- **list_downloads** — downloaded and partial files.
- **delete_download** `(path)` — deletes a file, its partial download and
  its job records. Only files in the cache, or exactly a job's own file when
  it was saved elsewhere.
- **plan_upload** `(network, atlas, file_type, local_path, generation?,
  environment?, force?)` — what `start_upload` would upload, with no side
  effects. `file_type` is `source-datasets` or `integrated-objects`;
  `local_path` a folder, whose top-level `.h5ad` files are considered
  (`hca-smart-sync` syncs a folder, never one file; stage what you mean to
  upload in a folder of its own). Returns `target` (`s3://<bucket>/<prefix>`,
  no credentials), `bucket`, `prefix`, `profile`, `transfer_tool` (`s5cmd` or
  `aws`), `files` (`name`, `size_bytes`, `sha256`, `reason`: `new`, `changed`
  or `forced`), `up_to_date` (already in the bucket unchanged; skipped) and
  `warnings`. Refuses, before touching the bucket, an `environment` other than
  the configured tracker's, an atlas `hca-smart-sync` does not know or files
  under a different bionetwork than the tracker does, a published atlas
  version (the tracker rejects uploads to one; create its next revision
  first), a missing profile, and a profile that cannot list the target. The
  folder in the prefix names the revision: `gut-v1` is v1.0, `gut-v1-1` is
  v1.1.
- **start_upload** `(same)` — runs the plan in a detached worker and returns
  `job_id` with the plan being executed. Nothing is started when every file is
  up to date (`job_id` is `null`); `force` uploads them anyway. One job per
  folder at a time.
- **upload_status** `(job_id?)` — state (`queued`, `uploading`, `done`,
  `failed`, `interrupted`), `files_done` of `files_total`, bytes, the
  `current_file` and the transfer tool's latest `progress` line for it, then
  `manifest_path` when done. Without `job_id`, every job.
- **check_environment** — `aria2c` path and version, the daemon, the cache
  folder and free space, whether the tracker is reachable and the token valid;
  under `upload`: `hca-smart-sync`, `s5cmd` and `aws`, the AWS profile and its
  source, whether it can list the bucket the configured tracker ingests from,
  and the verdict `can_upload`.

`cap_status` and `tier1_status` are not served by the tracker API; the client
mirrors the tracker's own rules (see the client README).

Downloads run in a detached aria2 daemon: they continue after the server or
the session ends, and `download_status` in a new session reports them. Uploads
run in a detached worker process the same way; `upload_status` follows them.

## Putting a curated file back

```
plan_upload(network, atlas, file_type, local_path)   # see what would go where; nothing happens
start_upload(...)                                     # same arguments; returns job_id
upload_status(job_id)                                 # until state is done
list_source_datasets / list_integrated_objects        # the file's new revision: uploaded_at, wip_number
get_validation_report(entry_id, kind)                 # the validators' verdict on it
```

`environment` defaults to `dev` and must be the configured tracker's; `prod`
is always explicit. The tracker ingests the file after the upload completes,
so the new revision appears in the lists a little later than `done`.
