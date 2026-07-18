"""Write h5ad files with timestamped naming and edit log tracking."""

from __future__ import annotations

import contextlib
import glob
import hashlib
import json
import re
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


def _compute_sha256(path: str) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(_HASH_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


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
