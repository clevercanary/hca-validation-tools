"""Write h5ad files with timestamped naming and edit log tracking."""

from __future__ import annotations

import contextlib
import glob
import hashlib
import json
import os
import re
import shutil
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from . import __version__
from ._keys import EDIT_LOG_KEY, PROVENANCE_KEY

if TYPE_CHECKING:
    from anndata import AnnData

_TIMESTAMP_PATTERN = re.compile(r"-edit-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}(?=\.h5ad$)")
_TIMESTAMP_FORMAT = "%Y-%m-%d-%H-%M-%S"

_HASH_CHUNK_SIZE = 1 << 20  # 1 MB — keeps syscall count low on multi-GB files
_REQUIRED_ENTRY_KEYS = {"timestamp", "tool", "tool_version", "operation", "description"}

# The message every tool returns when a snapshot name collides with its own
# source. Shared so the wording cannot drift between call sites — it contains
# a non-ASCII em dash, which is exactly what drifts on a re-type.
SAME_SECOND_SNAPSHOT_ERROR = "An edit snapshot for this second already exists — retry in a moment."


class MissingLineageRootError(RuntimeError):
    """The source is an edit snapshot whose original is not beside it.

    Editing it anyway would end with :func:`cleanup_previous_version`
    deleting the directory's only copy — refusing up front is what keeps
    the recoverability premise (#614/#619) true: the original always
    survives, and the chain never runs where there is no original.
    """


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


def _try_claim(path: str) -> bool:
    """Atomically create an empty file at ``path``; False if the name is taken.

    ``O_CREAT | O_EXCL`` is the whole point: testing occupancy and then copying
    leaves a window in which another writer can take the name, and ``copy2``
    would then silently overwrite their file. Creating the file *is* the claim,
    so there is no window to lose.

    It also settles the symlink case without a separate check — ``O_EXCL``
    refuses a symlink at the path, including a broken one that
    ``Path.exists()`` reports as absent.
    """
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    os.close(fd)
    return True


def _claim_snapshot_path(path: str) -> str:
    """Claim, and return, a snapshot path that no other file holds.

    ``generate_output_path`` timestamps to the second, so a name can already be
    taken — by the source itself (a snapshot edited within that same second),
    by an alias of it, or by a sibling tool's snapshot from the same second.
    All three are the same problem: the name is not ours to write. Waiting out
    the boundary and regenerating resolves every one of them, which is cheaper
    than failing a run the caller must then notice and retry.

    Returns with an empty file already created at the claimed path — that is
    what makes the caller's cleanup unambiguous. The name was ours to take, so
    whatever sits there afterwards is ours to remove.

    Raises:
        SameSecondSnapshotError: Still taken after waiting out the boundary.
    """
    output_path = generate_output_path(path)
    if _try_claim(output_path):
        return output_path
    time.sleep(1)
    output_path = generate_output_path(path)
    if _try_claim(output_path):
        return output_path
    raise SameSecondSnapshotError(SAME_SECOND_SNAPSHOT_ERROR)


@contextlib.contextmanager
def snapshot_copy(path: str) -> Iterator[str]:
    """Yield the path of a fresh snapshot copy of ``path``, cleaning it up on error.

    Wraps ``shutil.copy2`` with the three things every copy-and-patch tool
    needs around it, each of which is a way to lose data if omitted:

    * a destination name no file already occupies — see
      :func:`_claim_snapshot_path`;
    * a refusal, rather than a silent overwrite, when that cannot be arranged;
    * removal of the snapshot if the copy or the caller's body then fails.
      ``shutil.copyfile`` opens the destination ``'wb'`` and leaves a partial
      file behind on error, and a leftover partial is worse than an error: it
      carries the newest ``-edit-`` timestamp, so :func:`resolve_latest` would
      hand that truncated file to every later call on the dataset.

    Body exceptions propagate after the snapshot is removed, so a caller's own
    ``except`` still sees them. A caller that returns normally keeps the
    snapshot.

    Args:
        path: Path to the source file. Callers should pass a
            :func:`resolve_latest`-resolved path.
    Yields:
        Path to the newly created snapshot copy. Use
        :func:`snapshot_copy_hashed` when the caller also needs the source
        digest for the edit log.

    Raises:
        SameSecondSnapshotError: No free snapshot name was available, even
            after waiting out the second boundary.
    """
    output_path = _claim_snapshot_path(path)

    try:
        shutil.copy2(path, output_path)
    except shutil.SameFileError as e:
        # Nothing was written — the copy compares inodes before opening the
        # destination — but the file at output_path *is* ours: the O_EXCL
        # claim created it. Leaving it would strand a zero-byte file carrying
        # the newest -edit- timestamp, which resolve_latest would then hand to
        # every later call (#597).
        with contextlib.suppress(OSError):
            Path(output_path).unlink()
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


@contextlib.contextmanager
def snapshot_copy_hashed(path: str) -> Iterator[tuple[str, str]]:
    """:func:`snapshot_copy`, yielding the source's SHA-256 alongside the path.

    The digest is computed *during* the copy, so a caller that needs it for
    the edit log does not read the whole file a second time —
    :func:`build_edit_log` hashes the source itself when not given one.
    Separate from :func:`snapshot_copy` rather than a flag on it because the
    streaming copy this requires is slower than ``shutil.copy2`` when the
    digest goes unused: measured on a 6.7 GB file, copy2 2.7 s, copy2 plus a
    separate hash 6.0 s, one streaming pass 4.3 s.

    Yields:
        ``(output_path, sha256)`` for the newly created snapshot copy.

    Raises:
        SameSecondSnapshotError: No free snapshot name was available, even
            after waiting out the second boundary.
    """
    output_path = _claim_snapshot_path(path)

    try:
        sha256 = _copy_with_sha256(path, output_path)
    except shutil.SameFileError as e:
        # The claimed file is ours; see snapshot_copy for why it is removed.
        with contextlib.suppress(OSError):
            Path(output_path).unlink()
        raise SameSecondSnapshotError(SAME_SECOND_SNAPSHOT_ERROR) from e
    except BaseException:
        with contextlib.suppress(OSError):
            Path(output_path).unlink()
        raise

    try:
        yield output_path, sha256
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

    Refuses (:class:`MissingLineageRootError`) when ``source_path`` is itself
    an edit snapshot and its original — the timestamp-stripped name — is not
    beside it. Such a snapshot is the directory's only copy of the lineage:
    the next edit's :func:`cleanup_previous_version` would delete it, which
    is exactly the loss the snapshot chain exists to prevent. Every mutating
    tool names its output through this function, so the refusal holds
    chain-wide.

    Args:
        source_path: Path to the source .h5ad file.

    Returns:
        Path string in the same directory as source_path.
    """
    source = Path(source_path)
    if _is_timestamped(source_path):
        root = source.with_name(strip_timestamp(source.name))
        if not root.is_file():
            raise MissingLineageRootError(
                f"Refusing to edit: {source.name} is an edit snapshot but its "
                f"original ({root.name}) is not beside it, so this is the "
                f"directory's only copy of the lineage and the next cleanup "
                f"would delete it. Copy the original into the directory, or "
                f"rename this file to {root.name} to start a new lineage."
            )
    stem = _base_stem(source_path)
    return str(source.parent / f"{stem}-edit-{generate_timestamp()}.h5ad")


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
    provenance = adata.uns.get(PROVENANCE_KEY)
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


def parse_edit_log(existing_log_raw: str | list) -> dict:
    """The existing edit log as a list, or the reason it cannot be used.

    Split out of :func:`build_edit_log` because it needs no digest: a caller
    holding the raw log can refuse a corrupt one *before* copying a multi-GB
    file, rather than after the copy and the mutations (#597).

    Returns:
        Dict with 'log' (the entries) on success, or 'error'.
    """
    if isinstance(existing_log_raw, list):
        return {"log": existing_log_raw}
    if not isinstance(existing_log_raw, str):
        return {
            "error": (
                f"Existing {EDIT_LOG_KEY} has unsupported type "
                f"{type(existing_log_raw).__name__}; refusing to overwrite edit log"
            )
        }
    try:
        existing_log = json.loads(existing_log_raw)
    except json.JSONDecodeError:
        return {"error": f"Existing {EDIT_LOG_KEY} contains invalid JSON"}
    if not isinstance(existing_log, list):
        return {"error": f"Existing {EDIT_LOG_KEY} decoded to {type(existing_log).__name__}, expected list"}
    return {"log": existing_log}


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

    parsed = parse_edit_log(existing_log_raw)
    if "error" in parsed:
        return parsed

    return {"json": json.dumps(parsed["log"] + stamped_entries)}


def cleanup_previous_version(source_path: str, output_path: str) -> None:
    """Delete previous timestamped version if applicable.

    Never deletes the original (non-timestamped) file. Skips if output
    overwrote source in place (same-second write).
    """
    if _is_timestamped(source_path) and source_path != output_path and Path(source_path).is_file():
        with contextlib.suppress(OSError):
            Path(source_path).unlink()  # write succeeded; stale file is harmless


def nullable_string_locations(adata: AnnData) -> list[str]:
    """Dataframe locations holding pandas nullable strings (StringDtype).

    The write funnel's half of the write profile: anndata 0.11.4 raises on a
    ``StringArray`` (``allow_write_nullable_strings`` defaults False, which is
    the behaviour we want — our output must stay CellxGENE-compatible), but
    only *after* it has already streamed X into the output file. Checking
    here refuses before any bytes are written (hca-validation-tools#641
    tracks converting instead of refusing). Covers the value a column holds
    and the categories behind a categorical, on every dataframe anndata
    serializes: obs, var, raw.var, and obsm frames.
    """
    import pandas as pd

    def is_nullable_string(dtype) -> bool:
        if isinstance(dtype, pd.CategoricalDtype):
            return is_nullable_string(dtype.categories.dtype)
        return isinstance(dtype, pd.StringDtype)

    frames = [("obs", adata.obs), ("var", adata.var)]
    if adata.raw is not None:
        frames.append(("raw.var", adata.raw.var))
    frames += [(f"obsm['{key}']", val) for key, val in adata.obsm.items() if isinstance(val, pd.DataFrame)]
    found = []
    for name, df in frames:
        if is_nullable_string(df.index.dtype):
            found.append(f"{name} index")
        found += [f"{name}['{col}']" for col in df.columns if is_nullable_string(df[col].dtype)]
    return found


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

        provenance = adata.uns.get(PROVENANCE_KEY, {})
        if isinstance(provenance, dict) and EDIT_LOG_KEY in provenance:
            existing_log_raw = provenance[EDIT_LOG_KEY]
        else:
            existing_log_raw = "[]"

        log_result = build_edit_log(existing_log_raw, edit_entries, source_path)
        if "error" in log_result:
            return log_result

        adata.uns.setdefault(PROVENANCE_KEY, {})[EDIT_LOG_KEY] = log_result["json"]

        if nullable := nullable_string_locations(adata):
            return {
                "error": (
                    f"Refusing to write: {', '.join(nullable)} hold(s) pandas nullable string "
                    f"values, which this package can read but cannot write back "
                    f"(hca-validation-tools#641). Re-exporting the file with plain string "
                    f"arrays is the workaround available today; it is not the only possible fix."
                )
            }

        if output_path is None:
            output_path = generate_output_path(source_path)
        try:
            adata.write_h5ad(output_path, compression=compression, compression_opts=compression_opts)
        except BaseException:
            # A truncated file wearing the -edit-<timestamp> name is
            # indistinguishable from a good snapshot — leave no plausible
            # artifact behind a failed write.
            Path(output_path).unlink(missing_ok=True)
            raise

        cleanup_previous_version(source_path, output_path)

        return {"output_path": output_path}

    except Exception as e:
        return {"error": str(e)}
