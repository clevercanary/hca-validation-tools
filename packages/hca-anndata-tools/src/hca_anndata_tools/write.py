"""Write h5ad files with timestamped naming and edit log tracking."""

from __future__ import annotations

import contextlib
import glob
import hashlib
import json
import re
import shutil
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from . import __version__

if TYPE_CHECKING:
    from anndata import AnnData

_TIMESTAMP_PATTERN = re.compile(r"-edit-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}(?=\.h5ad$)")
_TIMESTAMP_FORMAT = "%Y-%m-%d-%H-%M-%S"
EDIT_LOG_KEY = "edit_history"
_HASH_CHUNK_SIZE = 1 << 20  # 1 MB — keeps syscall count low on multi-GB files
_REQUIRED_ENTRY_KEYS = {"timestamp", "tool", "tool_version", "operation", "description"}

# The message every tool returns when a snapshot name collides with its own
# source. Shared so the wording cannot drift between call sites — it contains
# a non-ASCII em dash, which is exactly what drifts on a re-type.
SAME_SECOND_SNAPSHOT_ERROR = "An edit snapshot for this second already exists — retry in a moment."


class SameSecondSnapshotError(RuntimeError):
    """A snapshot could not be named distinctly from the file it copies.

    Carries :data:`SAME_SECOND_SNAPSHOT_ERROR` as its message, so a caller
    whose handler returns ``{"error": str(e)}`` reports it unchanged.
    """


def _compute_sha256(path: str) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(_HASH_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_with_sha256(source_path: str, dest_path: str) -> str:
    """Copy source to dest and return the source's SHA-256 hex digest.

    One streaming pass instead of a hash read followed by a copy read —
    on a multi-GB h5ad that halves the read I/O of a copy-and-patch tool.

    Refuses same-file calls: opening dest with 'wb' would truncate the
    source to zero bytes before reading it, so this must fail the way
    shutil.copy2 does rather than trust every caller's same-second guard.
    samefile() compares filesystem identity (inode), catching hard links
    that a resolved-path comparison would miss; it raises on a missing
    path, so it only runs when dest already exists.
    """
    if Path(dest_path).exists() and Path(source_path).samefile(dest_path):
        raise shutil.SameFileError(f"{source_path!r} and {dest_path!r} are the same file")
    h = hashlib.sha256()
    with Path(source_path).open("rb") as src, Path(dest_path).open("wb") as dst:
        for chunk in iter(lambda: src.read(_HASH_CHUNK_SIZE), b""):
            h.update(chunk)
            dst.write(chunk)
    shutil.copystat(source_path, dest_path)
    return h.hexdigest()


@contextlib.contextmanager
def snapshot_copy(path: str) -> Iterator[str]:
    """Yield the path of a fresh snapshot copy of ``path``, cleaning it up on error.

    The copy-and-patch tools all need the same three things around
    ``shutil.copy2``, and each of them is a way to lose data if omitted:

    * **A name that isn't the source.** ``generate_output_path`` timestamps to
      the second, so a tool running on a snapshot and finishing within that same
      second generates its own source's name. Rather than fail the run, this
      waits out the boundary and regenerates — these tools are fast enough that
      back-to-back curation steps collide routinely — and raises
      :class:`SameSecondSnapshotError` only if the retry still collides.
    * **Refusing a destination that already is the source.** A hard link or
      ``./``-prefixed path has a different string form, so the equality check
      above misses it. ``copy2`` compares inodes before opening the
      destination, so catching ``SameFileError`` covers what string equality
      cannot — and covers it atomically with the copy, rather than as a
      separate check that can go stale between test and use. Such a
      destination is never removed: it predates the call, and one naming the
      source's own directory entry would take the source with it.
    * **Removing a snapshot we wrote but could not finish.** ``shutil.copyfile``
      opens the destination ``'wb'`` and does not remove it if the copy then
      fails partway (ENOSPC on a multi-GB h5ad is the realistic case). A
      leftover partial is worse than an error: it carries the newest ``-edit-``
      timestamp, so :func:`resolve_latest` would hand that truncated file to
      every later call on the dataset.

    The distinction the failure paths turn on is whether *we* created the file
    at the destination. ``SameFileError`` is the one failure that writes
    nothing, and the one case where unlinking the destination would delete the
    source — so it never reaches the cleanup. Everything else that fails after
    the copy begins leaves a file that is ours to remove.

    Body exceptions propagate after the snapshot is removed, so a caller's own
    ``except`` still sees them. A caller that returns normally keeps the
    snapshot, including a caller that unlinked it itself.

    Args:
        path: Path to the source file. Callers should pass a
            :func:`resolve_latest`-resolved path.

    Yields:
        Path to the newly created snapshot copy.

    Raises:
        SameSecondSnapshotError: The generated name is the source, or an alias
            of it, and waiting out the second boundary did not help.
    """
    output_path = generate_output_path(path)
    if output_path == path:
        time.sleep(1)
        output_path = generate_output_path(path)
    if output_path == path:
        raise SameSecondSnapshotError(SAME_SECOND_SNAPSHOT_ERROR)

    try:
        shutil.copy2(path, output_path)
    except shutil.SameFileError as e:
        # copy2 compares inodes before opening the destination, so nothing was
        # written. The destination is the source or an alias of it, and either
        # way it existed before this call and is not ours to remove — for an
        # alias naming the same directory entry ('./'-prefixed), removing it
        # would take the source with it.
        raise SameSecondSnapshotError(SAME_SECOND_SNAPSHOT_ERROR) from e
    except BaseException:
        with contextlib.suppress(OSError):
            Path(output_path).unlink()
        raise

    try:
        yield output_path
    except BaseException:
        with contextlib.suppress(OSError):
            Path(output_path).unlink()
        raise


def strip_timestamp(filename: str) -> str:
    """Strip an existing UTC timestamp suffix from an h5ad filename.

    Args:
        filename: A filename (not a full path), e.g. 'foo-edit-2026-03-27-13-54-26.h5ad'.

    Returns:
        The filename without the timestamp suffix, e.g. 'foo.h5ad'.
    """
    return _TIMESTAMP_PATTERN.sub("", filename)


def _base_stem(path: str) -> str:
    """Extract the base stem (no timestamp, no extension) from an h5ad path."""
    return strip_timestamp(Path(path).name).removesuffix(".h5ad")


def generate_timestamp() -> str:
    """Generate a UTC timestamp string for output filenames."""
    return datetime.now(timezone.utc).strftime(_TIMESTAMP_FORMAT)


def generate_output_path(source_path: str) -> str:
    """Generate a timestamped output path from a source h5ad path.

    Args:
        source_path: Path to the source .h5ad file.

    Returns:
        Path string in the same directory as source_path.
    """
    stem = _base_stem(source_path)
    return str(Path(source_path).parent / f"{stem}-edit-{generate_timestamp()}.h5ad")


def resolve_latest(path: str) -> str:
    """Find the latest timestamped version of an h5ad file.

    Given any version of a file (original or timestamped), scans the
    directory for timestamped variants and returns the newest one.
    If no timestamped versions exist, returns the original path.

    Args:
        path: Path to any version of an h5ad file.

    Returns:
        Path to the latest timestamped version, or the original if none exist.
    """
    directory = Path(path).parent
    stem = _base_stem(path)

    # Glob for timestamped variants, then strict regex filter on full basename
    full_re = re.compile(rf"^{re.escape(stem)}-edit-\d{{4}}-\d{{2}}-\d{{2}}-\d{{2}}-\d{{2}}-\d{{2}}\.h5ad$")
    candidates = [f for f in directory.glob(f"{glob.escape(stem)}-edit-*-*-*-*-*-*.h5ad") if full_re.match(f.name)]

    if not candidates:
        return path

    # Timestamps are lexicographically ordered
    return str(max(candidates))


def _is_timestamped(path: str) -> bool:
    """Check if a path has a timestamp suffix (i.e. it's an edit, not the original)."""
    return bool(_TIMESTAMP_PATTERN.search(Path(path).name))


def has_edit_log_operation(adata, operation: str) -> bool:
    """Return True if ``uns['provenance']['edit_history']`` contains an
    entry with the given ``operation`` value.

    Accepts both shapes the edit log can take, mirroring
    :func:`build_edit_log`'s input handling:

    * JSON string — the on-disk shape (what
      :func:`read_edit_log_h5py` returns and what AnnData round-trips
      through HDF5).
    * Python ``list`` of dicts — the in-flight shape during write
      transformations, before the log is serialized.

    Returns False if the log is missing, malformed, or contains no
    matching entry. Each entry's ``operation`` is the machine-readable
    name set by :func:`make_edit_entry` (e.g. ``"import_cellxgene"``,
    ``"strip_forbidden_obs_columns"``).

    Use this to gate tools on file origin / prior edits without having
    to parse the edit-log JSON yourself. Common case: refusing to run a
    redundant operation that an earlier tool already performed.

    Args:
        adata: An AnnData (or anything with a ``.uns`` mapping).
        operation: The operation name to look for.

    Returns:
        ``True`` if any matching entry exists, ``False`` otherwise.
    """
    provenance = adata.uns.get("provenance")
    if not isinstance(provenance, dict):
        return False
    log_raw = provenance.get(EDIT_LOG_KEY)
    if isinstance(log_raw, str):
        try:
            log = json.loads(log_raw)
        except json.JSONDecodeError:
            return False
    elif isinstance(log_raw, list):
        log = log_raw
    else:
        return False
    if not isinstance(log, list):
        return False
    return any(isinstance(entry, dict) and entry.get("operation") == operation for entry in log)


def make_edit_entry(
    operation: str,
    description: str,
    details: dict | None = None,
) -> dict:
    """Build an edit-log entry with timestamp, tool, and tool_version populated.

    Args:
        operation: Short machine-readable operation name (e.g. 'set_uns').
        description: Human-readable description of the change.
        details: Optional operation-specific structured data.

    Returns:
        A dict with the standard edit-log entry shape, ready to pass to
        write_h5ad() or build_edit_log().
    """
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": "hca-anndata-tools",
        "tool_version": __version__,
        "operation": operation,
        "description": description,
        "details": details if details is not None else {},
    }


def build_edit_log(
    existing_log_raw: str | list,
    edit_entries: list[dict],
    source_path: str,
    source_sha256: str | None = None,
) -> dict:
    """Build an updated edit log JSON string.

    Validates entries, computes SHA-256 of the source file, stamps each
    entry with source_file and source_sha256, and appends to the existing log.

    Args:
        existing_log_raw: Current edit log value (JSON string or list).
            Use "[]" if no log exists.
        edit_entries: New entries to append. Required keys:
            timestamp, tool, tool_version, operation, description.
        source_path: Path to the source .h5ad file on disk.
        source_sha256: Pre-computed SHA-256 hex digest. If None, computed
            from source_path.

    Returns:
        Dict with 'json' (updated JSON string) on success, or 'error'.
    """
    if not edit_entries:
        return {"error": "edit_entries must not be empty — every write should document what changed"}

    for i, entry in enumerate(edit_entries):
        missing = _REQUIRED_ENTRY_KEYS - entry.keys()
        if missing:
            return {"error": f"edit_entries[{i}] missing required keys: {sorted(missing)}"}

    sha256 = source_sha256 if source_sha256 is not None else _compute_sha256(source_path)
    source_filename = Path(source_path).name

    stamped_entries = [{**entry, "source_file": source_filename, "source_sha256": sha256} for entry in edit_entries]

    if isinstance(existing_log_raw, str):
        try:
            existing_log = json.loads(existing_log_raw)
        except json.JSONDecodeError:
            return {"error": f"Existing {EDIT_LOG_KEY} contains invalid JSON"}
        if not isinstance(existing_log, list):
            return {"error": f"Existing {EDIT_LOG_KEY} decoded to {type(existing_log).__name__}, expected list"}
    elif isinstance(existing_log_raw, list):
        existing_log = existing_log_raw
    else:
        return {
            "error": (
                f"Existing {EDIT_LOG_KEY} has unsupported type "
                f"{type(existing_log_raw).__name__}; refusing to overwrite edit log"
            )
        }

    return {"json": json.dumps(existing_log + stamped_entries)}


def cleanup_previous_version(source_path: str, output_path: str) -> None:
    """Delete previous timestamped version if applicable.

    Never deletes the original (non-timestamped) file. Skips if output
    overwrote source in place (same-second write).
    """
    if _is_timestamped(source_path) and source_path != output_path and Path(source_path).is_file():
        with contextlib.suppress(OSError):
            Path(source_path).unlink()  # write succeeded; stale file is harmless


def write_h5ad(
    adata: AnnData,
    source_path: str,
    edit_entries: list[dict],
    output_path: str | None = None,
    compression: Literal["gzip", "lzf"] | None = "gzip",
    compression_opts: int | None = None,
) -> dict:
    """Write adata to a new timestamped file with edit log entries.

    Computes SHA-256 of the source file, appends edit_entries to
    adata.uns['provenance']['edit_history'], and writes to a new timestamped path.
    The original (non-timestamped) file is never modified. If source_path
    is a previous timestamped edit, it is deleted after the new file is
    successfully written — keeping only the original + latest edit on disk.

    Args:
        adata: An AnnData object (already modified by the caller). In-memory
            and backed-mode (backed='r') instances are both supported; in
            backed mode X is streamed chunk-wise from its source file.
        source_path: Path to the source .h5ad file on disk.
        edit_entries: List of edit log entry dicts to append. Required keys:
            timestamp, tool, tool_version, operation, description. Optional:
            details (dict of operation-specific structured data).
            The source_file and source_sha256 fields are set automatically.
        output_path: Override the generated output path. If None, a
            timestamped path is generated from the source filename.
        compression: HDF5 filter for chunked datasets. Defaults to 'gzip'.
            Passed through to anndata.AnnData.write_h5ad.
        compression_opts: Filter options (e.g. gzip level 0-9). None uses
            the filter's default.

    Returns:
        A dict with 'output_path' on success, or 'error' on failure.
    """
    try:
        if not source_path.endswith(".h5ad"):
            return {"error": f"Source path must be a .h5ad file, got: {source_path}"}

        if not Path(source_path).is_file():
            return {"error": f"Source file not found: {source_path}"}

        provenance = adata.uns.get("provenance", {})
        if isinstance(provenance, dict) and EDIT_LOG_KEY in provenance:
            existing_log_raw = provenance[EDIT_LOG_KEY]
        else:
            existing_log_raw = "[]"

        log_result = build_edit_log(existing_log_raw, edit_entries, source_path)
        if "error" in log_result:
            return log_result

        adata.uns.setdefault("provenance", {})[EDIT_LOG_KEY] = log_result["json"]

        if output_path is None:
            output_path = generate_output_path(source_path)
        adata.write_h5ad(output_path, compression=compression, compression_opts=compression_opts)

        cleanup_previous_version(source_path, output_path)

        return {"output_path": output_path}

    except Exception as e:
        return {"error": str(e)}
