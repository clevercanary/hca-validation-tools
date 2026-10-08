# hca-tracker-mcp

MCP server to list and download atlas files from the HCA Atlas Tracker. It is a
thin wrapper over [`hca-tracker-client`](../hca-tracker-client), which holds the
logic; see its README for how version selection, the checks before
downloading, verification and resume work.

It is a separate server from `hca-anndata-mcp`, so that server's tool list stays
focused and the tracker token stays here. The two work together through local
paths: a file this server downloads can be opened with `hca-anndata-mcp`'s
tools.

## Requirements

- `aria2c` 1.35.0 or newer on `PATH` (`brew install aria2`, `apt install aria2`;
  see the client README for other systems).
- A tracker API token (read-only), created at `<tracker>/api-token`.

## Configuration

| Variable | Default | |
|---|---|---|
| `HCA_TRACKER_URL` | — | Tracker base URL |
| `HCA_TRACKER_API_TOKEN` | — | Read-only API token |
| `HCA_TRACKER_CACHE_DIR` | `~/.cache/hca-tracker` | Where files and job state live |
| `HCA_TRACKER_CONFIRM_GB` | `5` | Files larger than this need `confirm=true` |
| `HCA_TRACKER_MAX_CONCURRENT` | `2` | Downloads running at once; the rest queue |

Set them in the server's environment, or in a `.env` file in the directory the
server runs in (only `HCA_TRACKER_*` keys are read from it). Claude Code starts
a project's MCP servers in the project root, so the repo `.env` works.

## `.mcp.json`

Installed from PyPI:

```json
{
  "mcpServers": {
    "hca-tracker": {
      "command": "uvx",
      "args": ["hca-tracker-mcp"],
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

From a checkout, point at the venv binary (`uv sync` in this folder first):

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

All read-only, matching the token's scope.

- **list_atlases** — every atlas version: `network`, `atlas` (slug), `version`,
  `is_latest`, `published`. Use it to find the `network`/`atlas` pair.
- **list_integrated_objects** / **list_source_datasets** `(network, atlas,
  generation?, published?)` — an atlas version's files: `name`, `size`,
  `file_id`, `integrity_status`.
- **start_download** `(network, atlas, file, generation?, published?, dest_dir?,
  confirm?, restart?)` — runs the checks, starts the download in the
  background, and returns `job_id`, `path` and `size` at once. Large files need
  `confirm=true`.
- **download_status** `(job_id?)` — state (`queued`, `downloading`,
  `verifying`, `done`, `failed`, `cancelled`, `interrupted`), bytes done and
  total, rate, time left. Without `job_id`, every job.
- **cancel_download** `(job_id)` — keeps the partial file for resuming.
- **list_downloads** — downloaded and partial files.
- **delete_download** `(path)` — deletes a file, its partial download and
  its job records.
- **check_environment** — `aria2c` path and version, the daemon, the cache
  folder and free space, whether the tracker is reachable and the token valid.

Downloads run in a detached aria2 daemon: they continue after the server or
the session ends, and `download_status` in a new session reports them.
