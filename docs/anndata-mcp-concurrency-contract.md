# Contract: hca-anndata-mcp parallel reads, serial writes

**Status:** Built in #897; fast and slow lanes and worker retirement in #899
**Date:** 2026-11-15
**Prompted by:** the 2026-11-14 immune v1 evaluation on the curation workstation. Nine agents shared one server, which sat at 100% of one core with 18 calls in flight and one running, while the machine (16 vCPUs, 8 cores) was about 93% idle. Epic #896; the full design that follows this one is #894 and #895.

## The one-line contract

**Reads run in parallel; writes run as they do today; a write never overlaps a read inside one server.** Because they never overlap, the snapshot model in `hca-anndata-tools` stays unchanged.

## Scope

One `hca-anndata-mcp` server process. Claude Code starts one stdio server per session, and that session's subagents share it. Other sessions, scripts and the CLI are other processes, and this contract does not coordinate with them.

## Terms

- **Write tool:** a tool that can create, change, rename or delete a file. That includes writing an edit snapshot and removing the previous version (`cleanup_previous_version` in `write.py`).
- **Read tool:** a tool that only opens files to read them and creates, changes, renames or deletes no file. A result held in memory, such as `plot_embedding`'s PNG, is still a read.
- **Worker:** a separate Python process that runs one read call at a time, started through `anyio.to_process.run_sync`. Threads are not enough, because h5py lets one thread into the library at a time.
- **Gate:** a readers-writer lock in the server. Any number of reads hold it together; a write holds it alone.
- **Slow read:** a read that can take minutes, because it loads or streams a whole file or opens every file in a folder. Every other read is a **fast read**.
- **Lane:** the slots one kind of read takes. Slow reads take the slow lane's S slots and fast reads the fast lane's N − S, so a fast read never waits for a slow read's slot.
- **Held memory:** what a worker holds once its read has ended: resident memory less shared pages on Linux (`/proc/self/statm`), physical footprint on macOS (`proc_pid_rusage`).
- **Retire:** take a worker out of anyio's pool and kill it, so its memory goes back to the machine.

The 41 tools registered in `server.py` on 2026-11-21 divide as follows. The write list is every tool whose code reaches `write_h5ad`, a snapshot helper or `cleanup_previous_version`.

| Kind | Count | Tools |
| --- | --- | --- |
| Write | 18 | `set_uns`, `set_producer_uns`, `convert_cellxgene_to_hca`, `strip_forbidden_obs_columns`, `drop_obs_columns`, `merge_obs_categories`, `rename_obs_column`, `rename_cell_ids`, `backfill_obs_from_source`, `copy_cap_annotations`, `copy_matrix_from_file`, `strip_cap_annotations`, `replace_placeholder_values`, `compress_h5ad`, `normalize_raw`, `set_source_dataset`, `label_h5ad`, `populate_labels` |
| Slow read | 8 | `plot_embedding` (loads the whole file), `validate_schema` (the validator loads the whole file), `check_raw_counts`, `check_duplicate_cells`, `check_donor_sex` (each streams the whole count matrix), `find_source_datasets`, `check_source_obs`, `check_cap_currency` (each opens every candidate file in a folder, which loads its `obs`) |
| Fast read | 15 | `get_summary`, `get_storage_info`, `get_descriptive_stats`, `view_data`, `locate_files`, `get_cap_annotations`, `list_uns_fields`, `validate_marker_genes`, `compare_cap_export`, `view_edit_log`, `check_x_normalization`, `check_embeddings`, `check_barcodes`, `check_schema_type`, `validate_cell_annotation` |

A tool's label does not depend on its arguments. `get_descriptive_stats` reads only `obs` or `var`. `view_data` can be asked for a large slice of the matrix; rule 24 covers the memory that leaves behind.

## Rules

### Labels

1. Every tool is registered through one helper whose `kind` parameter, `"fast"`, `"slow"` or `"write"`, is required. There is no default, so an unlabelled tool cannot be registered, and a write cannot also be a lane.
2. A test checks that the server's write set and slow set equal the table above, and that `list_tools()` returns the same names, parameters, output schemas and descriptions as before the change.

### Reads

3. Each read call runs in a worker, never in the server process. Its registered function is an async wrapper made with `functools.wraps`, so FastMCP no longer runs it on the event loop. A worker finds the tool function by its `__module__` and `__qualname__`, so a read it cannot find that way is refused at registration and the server does not start.
4. At most N reads run at once: at most S slow reads and at most N − S fast reads (rule 23). The wrapper takes a slot from its lane's own `CapacityLimiter` and passes `run_sync` an unbounded limiter, because `run_sync` takes its limiter internally, after the gate, and anyio's default allows one worker per core. N comes from `HCA_ANNDATA_MCP_READ_WORKERS` (default 16) and S from `HCA_ANNDATA_MCP_SLOW_WORKERS` (default N ÷ 2, rounded down), both checked at startup as positive integers with 1 ≤ S < N, so N must be at least 2. The defaults come from #899's measurement: 2, 4, 6 and 8 matrix passes at once gave 9.2, 14.9, 19.8 and 23.2 calls a minute, and the workstation's 16 vCPUs are 8 cores with two threads each, so 8 slow reads take one core each. Fast reads are short and mostly wait on the disk, so the fast lane gets the other half: about one fast call per agent arrives at once.
5. A read takes the gate only once it holds its lane's slot, so a read that is only queued never delays a write.
6. A read resolves the file it opens (`resolve_latest`) inside the worker, after taking the gate. Its result then describes one snapshot.
7. A read returns the same value, or raises the same exception type with the same message, as it does today. Arguments go by keyword through `functools.partial`, because `run_sync` passes positional arguments only.

### Writes

8. Each write call runs in the server process on its event loop, as today. While a write runs, the server answers nothing else, as today.
9. A write holds the gate alone. It starts only when no read holds the gate.
10. Once a write is waiting, no new read takes the gate until that write has finished. When a write finishes, every read that was waiting takes the gate before the next waiting write starts. Waiting writes start in the order they arrived.

### Failure and cancellation

11. The gate and the slot are released when a call returns, raises or is cancelled. A read whose worker is retired (rule 24) releases them once that worker has exited.
12. A read runs with `cancellable=True`: a cancelled read's worker is killed with SIGKILL, then the gate is released. This is safe because a read writes nothing.
13. A write cannot be cancelled once it runs, as today.
14. A worker that dies, for example out of memory, fails only its own call. anyio raises `BrokenWorkerProcess` with no message, so the wrapper returns `{"error": "<tool>: the worker process died (killed, or out of memory); nothing was written"}` and no traceback, because there is none to give (`scheduling.worker_died`). Other calls carry on. anyio hands a call to an idle worker that has died until the event loop has seen the exit, under 10 ms in testing, so before each read the wrapper sends a call that does nothing (`os.getpid`) and repeats it, up to N + 1 times, while it meets a dead worker (`scheduling.find_live_worker`). A worker that cannot start raises `RuntimeError("a read worker could not start: <Type>: <message>")` with the real cause instead, and the pings stop at the first such failure (`scheduling.raise_if_start_failed`). A worker that does not start within anyio's 20 s limit counts as a start-up failure, so the read fails rather than trying another worker. A retired worker leaves the pool before it is killed (rule 24), so it never uses up a ping. A ping, unlike a read, is safe to repeat; the read itself is never repeated, because a read that killed its worker by running out of memory would do so again. A worker that dies between the ping and the read still fails that read with the error above. An exception that cannot be pickled and rebuilt in the server would arrive there as an unrelated `TypeError`, so the worker raises `RuntimeError("<Type>: <message>")` in its place (`scheduling.call_rebuildable`). Every other exception arrives with its own type and message, as rule 7 says.

### Known costs, accepted

15. Worker output is lost. anyio points a worker's `sys.stdout` and `sys.stderr` at `/dev/null` and connects its file descriptor 2 to a pipe nobody reads, which hangs the worker once the pipe fills, so the worker points descriptor 2 at `/dev/null` before each call (`scheduling.run_in_worker`). Descriptor 1 is the pipe that carries results back: a read that writes to it below Python's `print` breaks the worker, and the call is reported as rule 14's dead worker. Today a read's warnings reach Claude Code's MCP log through the server's stderr; that is what is given up.
16. A new worker imports the modules of the tools it runs, not the server: `main.py` imports the server inside `run()`, because anyio re-runs the entry script in every worker. Measured on 2026-11-15, a worker's first `get_summary` takes 0.7 s and leaves it at 174 MiB; its first `plot_embedding` loads scanpy, adding 0.9 s and 120 MiB with a warm disk cache and up to 9.4 s without one. A call to a warm worker adds 0.2 ms, and rule 14's ping adds one more such round trip. A retired worker's replacement pays the first-call cost again: a new worker's first `validate_schema` took 11.9 s against 4.2 s warm on a 66 MB file (Linux, 2026-11-15), because the validator loads its data on first use. On the files measured, 66 to 586 MB on Linux, a warm validator worker held 2.05–2.51 GiB, under the 3 GiB limit, so rule 24 keeps it; on a 3.3 GB file on macOS it held 2.1 GiB. A `get_summary` worker held 3.6 GiB on that same 3.3 GB file, so on multi-GB files it is likely retired after every call, and each replacement pays the first-call cost again.
17. Idle workers do not exit on a timer. anyio kills a worker idle for 300 s only when a later read finds it, and the most recently used worker never exits on its own. What an idle worker keeps varies: measured on 2026-11-15, `get_summary` on a 3.3 GB file kept 3.6 GiB, and `plot_embedding` kept all of a 10.4 GiB peak on one file and almost none of a 3.7 GiB peak on another. Rule 24 retires any worker holding more than the limit when its read ends, so up to N idle workers each hold about the limit or less; the measurement is taken before anyio pickles the result, so what pickling leaves behind is not counted.
18. A read cancelled while its worker is still starting leaks that one worker process.
19. Coverage does not count code that runs in a worker. anyio kills a loop's workers with SIGKILL when the loop's root task ends, so they never write coverage data, and under pytest-asyncio every test is its own root task. Tests call the tool bodies, `run_in_worker` and the held-memory read in the test process as well.

### Worker start-up

20. The server sets `PYTHONSAFEPATH=1` in its own environment before it starts (`main.run`), and every worker inherits it. A worker starts as `python -u -m anyio.to_process`, which would otherwise put the server's working directory first on its `sys.path` until the parent's path arrives, so a module there named like `anyio` or a standard-library module would run in the worker. Python 3.10 ignores the variable, so there that exposure remains.

### Server death and hung reads

21. When the server is killed, idle workers exit, and a busy worker finishes its read, still holding its memory, before it exits. Nothing is written, because a read writes nothing.
22. A read that never returns holds its slot and the gate. Once a write is waiting, every later read in that server waits behind the write until the client cancels the hung read (rule 12).

### Lanes and retirement

23. A slow read takes a slot in the slow lane, a fast read in the fast lane (rule 4). A fast read never waits for a slow read's slot, and while S slow reads run, a further slow read waits for one of the S to end. The label is the time a read can take, not its memory: memory is rule 24's job, because a fast read on a large file can hold gigabytes.
24. A worker reports its pid and held memory with every result, returned, or raised as an `Exception` (`scheduling.Returned`, `scheduling.Raised`); after a `BaseException` such as `SystemExit` it reports nothing and is not retired. When the held memory is above `HCA_ANNDATA_MCP_RETIRE_GIB` (default 3 GiB, a positive number), the wrapper retires that worker before it returns the result (`scheduling.retire`). It takes the worker off the end of anyio's idle list, where `run_sync` has just put it, checks its pid, drops it from anyio's set of workers, and kills it, with no `await` between the result arriving and the kill, so no other call can have taken the worker; a pid that does not match raises. This reaches into anyio's private `_process_pool_workers` and `_process_pool_idle_workers`, so `anyio` is pinned below 5 and a test fails if either moves. Held memory, not peak: on Linux a new process's `ru_maxrss` starts at the server's own peak.

## What this contract does not promise

- **No coordination between processes.** Two Claude sessions each run their own server, and a script or the CLI is a third process. A write in one can overlap a read or a write in another, exactly as today. The optional per-file `flock` in #896 covers that later.
- **No parallel writes.** Two writes never run together, even on different files.
- **No write during a long read.** A write waits for every running read to finish. Reads over a large file can take minutes. During evaluation, which is all reads, this costs nothing.
- **No memory guard per file.** `plot_embedding` loads a whole file (`backed=None`), and the largest file on the workstation is 63.6 GB, so one worker could take most of its 123 GB alone, and S slow reads at once are counted, not weighed. #904 replaces this with a memory budget for slow reads. Rule 24 bounds what idle workers keep, not what a running read takes.
- **No change to the file model.** `hca-anndata-tools` keeps claiming the final snapshot name and editing it in place. That is safe here only because rule 9 keeps reads and writes apart inside one server.

## Moving on to #895

#895 lets writes overlap reads once #894 publishes snapshots only when complete. Moving on means replacing rules 9 and 10 with #895's write mutex. Rules 1 to 7, 11 to 21, 23 and 24 carry over, and so does rule 22's first point, that a hung read holds its slot until the client cancels it.

## Definition of done

- [x] Every tool is registered with a required read or write label, and the write set equals the table above (rules 1–2). Test: the write-set test.
- [x] `list_tools()` returns the same names, parameters, output schemas and descriptions as `main` (rules 2–3). Test: a parity test over the tool list.
- [x] Two reads run at the same time in different worker processes (rules 3–4). Test: two fixture reads each wait for the other's barrier file in `tmp_path`, and report different PIDs.
- [x] A write waits for running reads; a read that arrives while a write waits runs after it; and reads waiting when a write finishes run before the next write (rules 5, 9, 10). Test: the gate on its own, driven by anyio events, records the order.
- [x] A cancelled read releases the gate, and a dead worker returns the rule 14 error while other calls carry on (rules 11, 12, 14). Test: cancel a fixture read and kill a worker, then a write runs.
- [x] Each of the 23 read tools returns the same result through a worker as in the server process (rule 7). Test: a parity test over the test fixture file.
- [x] `HCA_ANNDATA_MCP_READ_WORKERS` set to `0` or `abc` stops the server at startup with a message naming the variable (rule 4).
- [x] Every read is labelled fast or slow, and the slow set equals the table above (rules 1, 2, 23). Test: the registration tests. (#899)
- [x] A fast read returns while the slow lane is full, and a further slow read waits (rules 4, 23). Test: the lane test, which fails with one shared limiter. (#899)
- [x] A worker holding more than the limit leaves anyio's pool, also when its read raises; one below it stays; 50 retirements leave no process or open file behind (rule 24). Tests: the retirement tests. (#899)
- [x] `HCA_ANNDATA_MCP_SLOW_WORKERS` set to `0`, to N or above, or to `abc`, and `HCA_ANNDATA_MCP_READ_WORKERS` set to `1`, stop the server at startup with a message naming the variable (rule 4). (#899)
- Moved to #904: a memory budget for slow reads, and defaults set from peak memory measured on the workstation (No memory guard per file).

## Not yet confirmed

- Peak memory per read on the workstation's largest files (#904).
- Throughput at S = 8 on the workstation itself; #899's measurement ran on a 10-core Mac (rule 4).
- How often each tool's worker is retired on the workstation's multi-GB files (rule 16); watch it during #899's How to verify step 2.
- The workstation's core count from `lscpu`; 8 cores with two threads is AWS's published `r7i.4xlarge` layout.
- Whether Claude Code sends `notifications/cancelled` when a call is interrupted.
