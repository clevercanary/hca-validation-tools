# Contract: hca-anndata-mcp parallel reads, serial writes

**Status:** Built in #897
**Date:** 2026-11-15
**Prompted by:** the 2026-11-14 immune v1 evaluation on the curation workstation. Nine agents shared one server, which sat at 100% of one core with 18 calls in flight and one running, while the 16-core machine was about 93% idle. Epic #896; the full design that follows this one is #894 and #895.

## The one-line contract

**Reads run in parallel; writes run as they do today; a write never overlaps a read inside one server.** Because they never overlap, the snapshot model in `hca-anndata-tools` stays unchanged.

## Scope

One `hca-anndata-mcp` server process. Claude Code starts one stdio server per session, and that session's subagents share it. Other sessions, scripts and the CLI are other processes, and this contract does not coordinate with them.

## Terms

- **Write tool:** a tool that can create, change, rename or delete a file. That includes writing an edit snapshot and removing the previous version (`cleanup_previous_version` in `write.py`).
- **Read tool:** a tool that only opens files to read them and creates, changes, renames or deletes no file. A result held in memory, such as `plot_embedding`'s PNG, is still a read.
- **Worker:** a separate Python process that runs one read call at a time, started through `anyio.to_process.run_sync`. Threads are not enough, because h5py lets one thread into the library at a time.
- **Gate:** a readers-writer lock in the server. Any number of reads hold it together; a write holds it alone.

The 39 tools registered in `server.py` on 2026-11-15 divide as follows. The write list is every tool whose code reaches `write_h5ad`, a snapshot helper or `cleanup_previous_version`.

| Kind | Count | Tools |
| --- | --- | --- |
| Write | 17 | `set_uns`, `set_producer_uns`, `convert_cellxgene_to_hca`, `strip_forbidden_obs_columns`, `drop_obs_columns`, `merge_obs_categories`, `rename_obs_column`, `rename_cell_ids`, `backfill_obs_from_source`, `copy_cap_annotations`, `strip_cap_annotations`, `replace_placeholder_values`, `compress_h5ad`, `normalize_raw`, `set_source_dataset`, `label_h5ad`, `populate_labels` |
| Read | 22 | `get_summary`, `get_storage_info`, `get_descriptive_stats`, `view_data`, `locate_files`, `plot_embedding`, `get_cap_annotations`, `list_uns_fields`, `validate_marker_genes`, `view_edit_log`, `check_x_normalization`, `check_raw_counts`, `check_duplicate_cells`, `check_embeddings`, `check_donor_sex`, `check_barcodes`, `find_source_datasets`, `check_cap_currency`, `check_source_obs`, `check_schema_type`, `validate_schema`, `validate_cell_annotation` |

## Rules

### Labels

1. Every tool is registered through one helper whose `kind` parameter, read or write, is required. There is no default, so an unlabelled tool cannot be registered.
2. A test checks that the server's write set equals the table above, and that `list_tools()` returns the same names, parameters, output schemas and descriptions as before the change.

### Reads

3. Each read call runs in a worker, never in the server process. Its registered function is an async wrapper made with `functools.wraps`, so FastMCP no longer runs it on the event loop. A worker finds the tool function by its `__module__` and `__qualname__`, so a read it cannot find that way is refused at registration and the server does not start.
4. At most N reads run at once. The wrapper takes a slot from the server's own `CapacityLimiter(N)` and passes `run_sync` an unbounded limiter, because `run_sync` takes its limiter internally, after the gate, and anyio's default allows one worker per core. N comes from `HCA_ANNDATA_MCP_READ_WORKERS`, checked at startup as a positive integer. The default, 6, is a placeholder until #899 sets it from measured peak memory.
5. A read takes the gate only once it holds a slot, so a read that is only queued never delays a write.
6. A read resolves the file it opens (`resolve_latest`) inside the worker, after taking the gate. Its result then describes one snapshot.
7. A read returns the same value, or raises the same exception type with the same message, as it does today. Arguments go by keyword through `functools.partial`, because `run_sync` passes positional arguments only.

### Writes

8. Each write call runs in the server process on its event loop, as today. While a write runs, the server answers nothing else, as today.
9. A write holds the gate alone. It starts only when no read holds the gate.
10. Once a write is waiting, no new read takes the gate until that write has finished. When a write finishes, every read that was waiting takes the gate before the next waiting write starts. Waiting writes start in the order they arrived.

### Failure and cancellation

11. The gate and the slot are released when a call returns, raises or is cancelled.
12. A read runs with `cancellable=True`: a cancelled read's worker is killed with SIGKILL, then the gate is released. This is safe because a read writes nothing.
13. A write cannot be cancelled once it runs, as today.
14. A worker that dies, for example out of memory, fails only its own call. anyio raises `BrokenWorkerProcess` with no message, so the wrapper returns `{"error": "<tool>: the worker process died (killed, or out of memory); nothing was written"}` and no traceback, because there is none to give (`scheduling.worker_died`). Other calls carry on. anyio hands a call to an idle worker that has died until the event loop has seen the exit, under 10 ms in testing, so before each read the wrapper sends a call that does nothing (`os.getpid`) and repeats it, up to N + 1 times, while it meets a dead worker (`scheduling.find_live_worker`). A worker that cannot start raises `RuntimeError("a read worker could not start: <Type>: <message>")` with the real cause instead, and the pings stop at the first such failure (`scheduling.raise_if_start_failed`). A worker that does not start within anyio's 20 s limit counts as a start-up failure, so the read fails rather than trying another worker. A ping, unlike a read, is safe to repeat; the read itself is never repeated, because a read that killed its worker by running out of memory would do so again. A worker that dies between the ping and the read still fails that read with the error above. An exception that cannot be pickled and rebuilt in the server would arrive there as an unrelated `TypeError`, so the worker raises `RuntimeError("<Type>: <message>")` in its place (`scheduling.call_rebuildable`). Every other exception arrives with its own type and message, as rule 7 says.

### Known costs, accepted

15. Worker output is lost. anyio points a worker's `sys.stdout` and `sys.stderr` at `/dev/null` and connects its file descriptor 2 to a pipe nobody reads, which hangs the worker once the pipe fills, so the worker points descriptor 2 at `/dev/null` before each call (`scheduling.run_in_worker`). Descriptor 1 is the pipe that carries results back: a read that writes to it below Python's `print` breaks the worker, and the call is reported as rule 14's dead worker. Today a read's warnings reach Claude Code's MCP log through the server's stderr; that is what is given up.
16. A new worker imports the modules of the tools it runs, not the server: `main.py` imports the server inside `run()`, because anyio re-runs the entry script in every worker. Measured on 2026-11-15, a worker's first `get_summary` takes 0.7 s and leaves it at 174 MiB; its first `plot_embedding` loads scanpy, adding 0.9 s and 120 MiB with a warm disk cache and up to 9.4 s without one. A call to a warm worker adds 0.2 ms, and rule 14's ping adds one more such round trip.
17. Idle workers do not exit on a timer. anyio kills a worker idle for 300 s only when a later read finds it, and the most recently used worker never exits on its own. A worker keeps its peak memory until then, so after an evaluation up to N workers may hold their peaks.
18. A read cancelled while its worker is still starting leaks that one worker process.
19. Coverage does not count code that runs in a worker. anyio kills a loop's workers with SIGKILL when the loop's root task ends, so they never write coverage data, and under pytest-asyncio every test is its own root task. Tests call the tool bodies in the test process as well.

### Worker start-up

20. The server sets `PYTHONSAFEPATH=1` in its own environment before it starts (`main.run`), and every worker inherits it. A worker starts as `python -u -m anyio.to_process`, which would otherwise put the server's working directory first on its `sys.path` until the parent's path arrives, so a module there named like `anyio` or a standard-library module would run in the worker. Python 3.10 ignores the variable, so there that exposure remains.

### Server death and hung reads

21. When the server is killed, idle workers exit, and a busy worker finishes its read, still holding its memory, before it exits. Nothing is written, because a read writes nothing.
22. A read that never returns holds its slot and the gate. Once a write is waiting, every later read in that server waits behind the write until the client cancels the hung read (rule 12).

## What this contract does not promise

- **No coordination between processes.** Two Claude sessions each run their own server, and a script or the CLI is a third process. A write in one can overlap a read or a write in another, exactly as today. The optional per-file `flock` in #896 covers that later.
- **No parallel writes.** Two writes never run together, even on different files.
- **No write during a long read.** A write waits for every running read to finish. Reads over a large file can take minutes. During evaluation, which is all reads, this costs nothing.
- **No memory guard per file.** `plot_embedding` loads a whole file (`backed=None`), and the largest file on the workstation is 63.6 GB, so one worker could take most of its 123 GB alone. #899 replaces this with a memory budget for scans.
- **No change to the file model.** `hca-anndata-tools` keeps claiming the final snapshot name and editing it in place. That is safe here only because rule 9 keeps reads and writes apart inside one server.

## Moving on to #895

#895 lets writes overlap reads once #894 publishes snapshots only when complete. Moving on means replacing rules 9 and 10 with #895's write mutex. Rules 1 to 7 and 11 to 21 carry over, and so does rule 22's first point, that a hung read holds its slot until the client cancels it.

## Definition of done

- [x] Every tool is registered with a required read or write label, and the write set equals the table above (rules 1–2). Test: the write-set test.
- [x] `list_tools()` returns the same names, parameters, output schemas and descriptions as `main` (rules 2–3). Test: a parity test over the tool list.
- [x] Two reads run at the same time in different worker processes (rules 3–4). Test: two fixture reads each wait for the other's barrier file in `tmp_path`, and report different PIDs.
- [x] A write waits for running reads; a read that arrives while a write waits runs after it; and reads waiting when a write finishes run before the next write (rules 5, 9, 10). Test: the gate on its own, driven by anyio events, records the order.
- [x] A cancelled read releases the gate, and a dead worker returns the rule 14 error while other calls carry on (rules 11, 12, 14). Test: cancel a fixture read and kill a worker, then a write runs.
- [x] Each of the 22 read tools returns the same result through a worker as in the server process (rule 7). Test: a parity test over the test fixture file.
- [x] `HCA_ANNDATA_MCP_READ_WORKERS` set to `0` or `abc` stops the server at startup with a message naming the variable (rule 4).
- Moved to #899: setting the default N from measured peak memory, and a memory guard per file (rule 4; No memory guard per file).

## Not yet confirmed

- Peak memory per read on the workstation's largest files (#899).
- Whether Claude Code sends `notifications/cancelled` when a call is interrupted.
