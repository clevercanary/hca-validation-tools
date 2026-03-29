"""Write h5ad files with timestamped naming and edit log tracking."""

from __future__ import annotations

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


def generate_output_path(source_path: str, output_dir: str | None = None) -> str:
    """Generate a timestamped output path from a source h5ad path.

    Args:
        source_path: Path to the source .h5ad file.
        output_dir: Directory for the output file. Defaults to same directory as source_path.

    Returns:
        Path string like '/dir/base-2026-03-27-13-54-26.h5ad'. Inherits
        absoluteness from source_path/output_dir.
    """
    filename = os.path.basename(source_path)
    base = strip_timestamp(filename)
    stem = base.removesuffix(".h5ad")
    timestamp = datetime.now(timezone.utc).strftime(_TIMESTAMP_FORMAT)
    out_filename = f"{stem}-{timestamp}.h5ad"

    directory = output_dir if output_dir is not None else os.path.dirname(source_path)
    return os.path.join(directory, out_filename)


def write_h5ad(
    adata: AnnData,
    source_path: str,
    edit_entries: list[dict],
    output_dir: str | None = None,
) -> dict:
    """Write adata to a new timestamped file with edit log entries.

    Computes SHA-256 of the source file, appends edit_entries to
    adata.uns['hca_edit_log'], and writes to a new timestamped path.
    The original source file is never modified.

    Args:
        adata: An in-memory AnnData object (already modified by the caller).
        source_path: Path to the original source .h5ad file on disk.
        edit_entries: List of edit log entry dicts to append. Required keys:
            timestamp, tool, tool_version, operation, description. Optional:
            details (dict of operation-specific structured data).
            The source_file and source_sha256 fields are set automatically.
        output_dir: Directory for the output file. Defaults to same directory as source_path.

    Returns:
        A dict with 'output_path' on success, or 'error' on failure.
    """
    try:
        if not source_path.lower().endswith(".h5ad"):
            return {"error": f"Source path must be a .h5ad file, got: {source_path}"}

        if not os.path.isfile(source_path):
            return {"error": f"Source file not found: {source_path}"}

        if not edit_entries:
            return {"error": "edit_entries must not be empty — every write should document what changed"}

        if output_dir is not None and not os.path.isdir(output_dir):
            return {"error": f"Output directory not found: {output_dir}"}

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

        # Write to new timestamped path
        output_path = generate_output_path(source_path, output_dir)
        adata.write_h5ad(output_path)

        return {"output_path": output_path}

    except Exception as e:
        return {"error": str(e)}
