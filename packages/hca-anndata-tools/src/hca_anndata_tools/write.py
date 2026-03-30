"""Write h5ad files with timestamped naming and edit log tracking."""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anndata import AnnData

_TIMESTAMP_PATTERN = re.compile(r"-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}(?=\.h5ad$)")
_TIMESTAMP_FORMAT = "%Y-%m-%d-%H-%M-%S"
EDIT_LOG_KEY = "hca_edit_log"
_HASH_CHUNK_SIZE = 1 << 20  # 1 MB — keeps syscall count low on multi-GB files
_REQUIRED_ENTRY_KEYS = {"timestamp", "tool", "tool_version", "operation", "description"}


def _compute_sha256(path: str) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_HASH_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def strip_timestamp(filename: str) -> str:
    """Strip an existing UTC timestamp suffix from an h5ad filename.

    Args:
        filename: A filename (not a full path), e.g. 'foo-2026-03-27-13-54-26.h5ad'.

    Returns:
        The filename without the timestamp suffix, e.g. 'foo.h5ad'.
    """
    return _TIMESTAMP_PATTERN.sub("", filename)


def _base_stem(path: str) -> str:
    """Extract the base stem (no timestamp, no extension) from an h5ad path."""
    return strip_timestamp(os.path.basename(path)).removesuffix(".h5ad")


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
    return os.path.join(os.path.dirname(source_path), f"{stem}-{generate_timestamp()}.h5ad")


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
    directory = os.path.dirname(path) or "."
    stem = _base_stem(path)

    # Glob for timestamped variants, then strict regex filter on full basename
    pattern = os.path.join(directory, f"{glob.escape(stem)}-*-*-*-*-*-*.h5ad")
    full_re = re.compile(rf"^{re.escape(stem)}-\d{{4}}-\d{{2}}-\d{{2}}-\d{{2}}-\d{{2}}-\d{{2}}\.h5ad$")
    candidates = [
        f for f in glob.glob(pattern)
        if full_re.match(os.path.basename(f))
    ]

    if not candidates:
        return path

    # Timestamps are lexicographically ordered
    return os.path.normpath(max(candidates))


def _is_timestamped(path: str) -> bool:
    """Check if a path has a timestamp suffix (i.e. it's an edit, not the original)."""
    return bool(_TIMESTAMP_PATTERN.search(os.path.basename(path)))


def write_h5ad(
    adata: AnnData,
    source_path: str,
    edit_entries: list[dict],
    output_path: str | None = None,
) -> dict:
    """Write adata to a new timestamped file with edit log entries.

    Computes SHA-256 of the source file, appends edit_entries to
    adata.uns['hca_edit_log'], and writes to a new timestamped path.
    The original (non-timestamped) file is never modified. If source_path
    is a previous timestamped edit, it is deleted after the new file is
    successfully written — keeping only the original + latest edit on disk.

    Args:
        adata: An in-memory AnnData object (already modified by the caller).
        source_path: Path to the source .h5ad file on disk.
        edit_entries: List of edit log entry dicts to append. Required keys:
            timestamp, tool, tool_version, operation, description. Optional:
            details (dict of operation-specific structured data).
            The source_file and source_sha256 fields are set automatically.
        output_path: Override the generated output path. If None, a
            timestamped path is generated from the source filename.

    Returns:
        A dict with 'output_path' on success, or 'error' on failure.
    """
    try:
        if not source_path.endswith(".h5ad"):
            return {"error": f"Source path must be a .h5ad file, got: {source_path}"}

        if not os.path.isfile(source_path):
            return {"error": f"Source file not found: {source_path}"}

        if not edit_entries:
            return {"error": "edit_entries must not be empty — every write should document what changed"}

        # Validate edit entries have required fields
        for i, entry in enumerate(edit_entries):
            missing = _REQUIRED_ENTRY_KEYS - entry.keys()
            if missing:
                return {"error": f"edit_entries[{i}] missing required keys: {sorted(missing)}"}

        # Compute source identity
        sha256 = _compute_sha256(source_path)
        source_filename = os.path.basename(source_path)

        # Build new entries with provenance fields (don't mutate caller's dicts)
        stamped_entries = [
            {**entry, "source_file": source_filename, "source_sha256": sha256}
            for entry in edit_entries
        ]

        # Append to existing edit log (preserve previous entries).
        # The log is stored as a JSON string in uns because anndata's HDF5
        # writer cannot serialize lists of dicts natively.
        raw_log = adata.uns.get(EDIT_LOG_KEY, "[]")
        if isinstance(raw_log, str):
            try:
                existing_log = json.loads(raw_log)
            except json.JSONDecodeError:
                return {"error": f"Existing {EDIT_LOG_KEY} contains invalid JSON"}
            if not isinstance(existing_log, list):
                return {"error": f"Existing {EDIT_LOG_KEY} decoded to {type(existing_log).__name__}, expected list"}
        elif isinstance(raw_log, list):
            existing_log = raw_log
        else:
            return {
                "error": (
                    f"Existing {EDIT_LOG_KEY} has unsupported type "
                    f"{type(raw_log).__name__}; refusing to overwrite edit log"
                )
            }
        adata.uns[EDIT_LOG_KEY] = json.dumps(existing_log + stamped_entries)

        # Write to output path (caller-provided or auto-generated)
        if output_path is None:
            output_path = generate_output_path(source_path)
        adata.write_h5ad(output_path, compression="gzip")

        # Delete previous timestamped version (never the original).
        # Skip if output == source (same-second write overwrote in place).
        if (
            _is_timestamped(source_path)
            and source_path != output_path
            and os.path.isfile(source_path)
        ):
            try:
                os.remove(source_path)
            except OSError:
                pass  # write succeeded; stale file is harmless

        return {"output_path": output_path}

    except Exception as e:
        return {"error": str(e)}
