"""Rename a single obs column in an h5ad file.

The third member of the obs-column family, alongside
:mod:`hca_anndata_tools.drop` and :mod:`hca_anndata_tools.strip`. The three
answer different questions about a producer column that does not belong as it
stands: strip removes a fixed privacy list, drop removes caller-named columns
whose data is redundant, and this renames a column whose *data* is real and
whose *name* is wrong.

Like drop, this tool guards coherence, not validity (#614): renaming
preserves every value and is reversible by renaming back. Promoting producer
data into its canonical schema name is a normal curation act — nee2023's ``cell_type_label`` holds the authors' own
cell-type calls, and ``author_cell_type`` is the schema's name for exactly
that (see clevercanary/hca-ingest-coordination#24).
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np

from ._io import (
    read_batch_condition,
    read_column_order,
    read_edit_log_h5py,
    read_group,
    read_uns,
    write_edit_log_h5py,
)
from .cap import CAP_METADATA_KEY
from .guards import (
    detect_obs_references,
    direct_members,
    legacy_layout_problems,
    malformed_name_problems,
    obs_index_problems,
)
from .write import (
    build_edit_log,
    cleanup_previous_version,
    make_edit_entry,
    resolve_latest,
    snapshot_copy,
)

# anndata writes uns string arrays with this encoding; batch_condition is
# rewritten in place, so it has to be recreated the same way.
_STR_DTYPE = h5py.string_dtype(encoding="utf-8")

# Rows per read when scanning a column for emptiness. Rows, not bytes — the
# width depends on the column, so this is 64 KB of int8 categorical codes and
# 512 KB of float64. Sized against the storage chunks anndata writes (a few
# thousand rows), so a read spans a handful of them rather than hundreds.
_SCAN_CHUNK_ROWS = 1 << 16


def _all_rows(ds: h5py.Dataset, predicate) -> bool:
    """True when ``predicate`` holds for every row, read in bounded chunks.

    Stops at the first chunk it does not hold for — chunk-level, not row-level:
    each chunk is evaluated whole before ``all`` can bail. A populated column is
    the refusal case and normally answers from the first chunk, so the common
    path reads well under a megabyte of a column that may hold tens of millions
    of rows.
    """
    return all(
        predicate(ds[start : start + _SCAN_CHUNK_ROWS]).all() for start in range(0, ds.shape[0], _SCAN_CHUNK_ROWS)
    )


def _is_empty_column(obs: h5py.Group, name: str) -> bool:
    """True when every value in an obs column is null.

    Deliberately narrow: it answers "can this be overwritten without losing
    anything", so it recognizes only the two encodings where emptiness is
    cheap to prove — a categorical whose codes are all ``-1``, and a float
    array that is all NaN. Everything else counts as occupied, including
    anndata's nullable-integer and nullable-boolean groups, which *do* carry a
    null mask but are not worth a second decoder here. A caller who wants one
    of those gone should drop it first and see the count they are discarding.
    """
    item = obs[name]
    if isinstance(item, h5py.Group) and "categories" in item:  # a categorical
        codes = item["codes"]
        if not isinstance(codes, h5py.Dataset):  # narrows h5py's member union
            return False
        return _all_rows(codes, lambda a: a == -1)  # -1 is pandas' missing code
    if isinstance(item, h5py.Dataset) and item.dtype.kind == "f":
        return _all_rows(item, np.isnan)
    return False


def _validate_request(obs: h5py.Group, uns: h5py.Group | None, column: str, new_name: str) -> list[str]:
    """Collect every reason the rename cannot proceed.

    All checks run to completion rather than short-circuiting, so a caller who
    got two things wrong learns both in one round trip.
    """
    problems: list[str] = []

    problems += legacy_layout_problems(uns)

    # This tool's policy per reference mechanism (#614's repair-or-refuse rule):
    #   batch_condition -> REPAIR   (a rename knows the new name; rewritten below)
    #   palettes        -> CASCADE  (moved with the column)
    #   CAP columns     -> REFUSE   (CAP is the system of record; strip and
    #                                re-copy the set rather than renaming it)
    refs = detect_obs_references(uns, (column, new_name))
    if refs.cap_columns:
        problems.append(
            f"look like CAP annotation-set columns: {refs.cap_columns} — the set is declared "
            f"in uns[{CAP_METADATA_KEY!r}], which names its columns. Strip the annotation "
            f"set and re-copy it from CAP instead of renaming its columns"
        )

    malformed = [n for n in (column, new_name) if "/" in n or not n.strip()]
    problems += malformed_name_problems((column, new_name))

    if column == new_name:
        problems.append(f"'{column}' is already the column's name")

    problems += obs_index_problems(obs, (column, new_name), consequence="renaming it would destroy the file")

    # Membership against the group's direct children rather than `in obs`,
    # which would resolve link paths (see the malformed check above).
    #
    # A malformed name is excluded so each bad name is reported once. "/X" is
    # necessarily absent from obs.keys() too, and listing it under both
    # problems would imply its only fault was being missing — sending a caller
    # to hunt for a typo rather than read the path-name rule. drop.py:155 makes
    # the same exclusion for the same reason.
    members = direct_members(obs)
    if column not in members and column not in malformed:
        problems.append(f"not present in obs: '{column}'")

    # The one destination rule: an occupied name is refused, because silently
    # clobbering a populated column is never what a rename meant. A column
    # holding nothing carries no information to lose, so it gives way.
    if new_name in members and not _is_empty_column(obs, new_name):
        problems.append(
            f"'{new_name}' already exists in obs and holds values — drop it first if "
            f"replacing it is intended (a column that is entirely empty is overwritten "
            f"without complaint)"
        )

    return problems


def rename_obs_column(path: str, column: str, new_name: str) -> dict:
    """Rename one obs column, preserving everything except its name.

    The column keeps its position in ``obs[column-order]``, its dtype, its
    categories and its compression — an HDF5 link rename moves no data, so
    there is nothing to preserve by hand. ``uns['<column>_colors']`` travels
    with it, the mirror of :func:`~hca_anndata_tools.drop.drop_obs_columns`
    deleting that palette: scanpy writes it for any categorical it plots, the
    palette belongs to the column rather than standing alone, and one left
    under the old key is orphaned — which the schema validator reports as
    "Colors field uns[...] does not have a corresponding categorical field in
    obs".

    All-or-nothing: every check runs before anything is written, and any
    failure leaves the file untouched with all problems reported together.

    The gates:

    * **Neither name may be an HDF5 link path** (contain ``/``), be blank, or
      be the obs index.
    * **The source must exist**, and must differ from the new name.
    * **The destination must not already exist** — unless it is provably
      empty, in which case it is overwritten. See :func:`_is_empty_column`.

    A column named by ``uns['batch_condition']`` is not refused: that entry is
    rewritten to the new name, since the same column still defines the batches
    and only its name changed. Refusing would be a dead end — ``set_uns``
    validates entries against the obs columns present, so the new name cannot
    be written before the rename happens.

    CAP annotation-set columns (the ``--`` names a set declares in
    ``uns['cap_metadata']``) are refused, as is the deprecated top-level CAP
    layout, matching ``drop_obs_columns``. A rename cannot repair the
    declaration it would break: CAP material is never patched in place — CAP is
    the system of record, and the workflow strips a set wholesale and re-copies
    it from a fresh export.

    Renaming a schema-*required* column **away** is *not* refused (nor is
    dropping one, since #619). Leaving the file short of a required column
    makes it **invalid**, which is ``validate_schema``'s verdict to deliver,
    not this tool's to pre-empt. The
    caller's next move may well restore it, and a tool cannot see that far.
    What this tool does owe the caller is a **coherent** file — no dangling
    references, no destroyed cell identities — which is what every gate above
    protects. See #614.

    On the module docstring's reversibility argument: overwriting an empty
    destination is the one thing renaming back does not undo — that column's
    entry and its declared categories do not return.

    Writes a new timestamped snapshot with an edit-log entry and deletes the
    previous snapshot (never the original), like every other mutating tool.
    The snapshot is not smaller than the input — HDF5 does not reclaim freed
    space in place — so run ``compress_h5ad`` afterwards if size matters.

    Args:
        path: Path to an .h5ad file. Auto-resolves to the latest timestamped
            edit snapshot before operating.
        column: The obs column to rename.
        new_name: Its new name.

    Returns:
        Dict with ``output_path``, ``column``, ``new_name``,
        ``uns_key_renamed`` (the palette that travelled, or None) and
        ``batch_condition_updated`` on success, or ``{"error": ...}``.
    """
    try:
        # Shape-check before anything reads the arguments. This is MCP-exposed,
        # so both names arrive as decoded JSON and may be null, a number, or a
        # list; _validate_request assumes strings, and letting a non-string
        # reach it surfaces "'list' object has no attribute 'strip'" instead of
        # something a caller can act on. Same guard drop_obs_columns applies to
        # its own argument, for the same reason.
        non_str = {
            label: value for label, value in (("column", column), ("new_name", new_name)) if not isinstance(value, str)
        }
        if non_str:
            return {"error": f"column and new_name must both be strings; got: {non_str}"}

        path = resolve_latest(path)
        if not Path(path).is_file():
            return {"error": f"File not found: {path}"}

        with h5py.File(path, "r") as f_in:
            obs = read_group(f_in, "obs")
            if obs is None:
                return {"error": "File has no obs group, or obs is not a group"}
            uns = read_uns(f_in)
            problems = _validate_request(obs, uns, column, new_name)
            palette = f"{column}_colors" if uns is not None and f"{column}_colors" in uns else None
            batch_condition = read_batch_condition(uns)

        if problems:
            return {"error": "Refusing to rename: " + "; ".join(problems)}

        # h5py closes before snapshot_copy's cleanup runs, which is the ordering
        # the unlink needs: removing an open HDF5 handle raises on Windows.
        with snapshot_copy(path) as output_path, h5py.File(output_path, "a") as f_out:
            uns_out = read_uns(f_out)

            # Anything already under the destination's palette key goes, whether
            # it belonged to an empty column being replaced or was orphaned by an
            # earlier edit. Unconditional, because the source owning a palette is
            # not what makes a stale one dangerous: left in place it would
            # describe the incoming column, and a length *match* is worse than a
            # mismatch — the validator reports a mismatch and says nothing about
            # colours that merely happen to fit.
            new_palette = f"{new_name}_colors"
            if uns_out is not None and new_palette in uns_out:
                del uns_out[new_palette]

            # Read before the move, next to the names it is about. Substituted in
            # place rather than via update_column_order, which appends: a renamed
            # column keeps its position, so a reader diffing two versions sees one
            # name change and not a reordering. A replaced empty destination is
            # dropped from the list first, so the name is not listed twice.
            order = [c for c in read_column_order(f_out["obs"]) if c != new_name]
            renamed_order = [new_name if c == column else c for c in order]

            # Validation established that an existing destination is empty, so
            # this discards nothing.
            replaced_destination = new_name in f_out["obs"]
            if replaced_destination:
                del f_out["obs"][new_name]
            f_out["obs"].move(column, new_name)
            f_out["obs"].attrs["column-order"] = renamed_order

            # Rewritten rather than refused — see the docstring for why.
            #
            # A replaced destination's own entry goes first. It declared the
            # column just deleted, and the new name resolves to different data
            # now, so leaving it is the batch_condition analogue of the stale
            # palette above: nothing reports it, because the name still points
            # at *a* column. Substituting afterwards then cannot leave the new
            # name listed twice, so no dedupe is needed.
            entries = [c for c in batch_condition if c != new_name] if replaced_destination else batch_condition
            updated = [new_name if c == column else c for c in entries]
            if updated != batch_condition and uns_out is not None:
                del uns_out["batch_condition"]
                ds = uns_out.create_dataset("batch_condition", data=np.array(updated, dtype=object), dtype=_STR_DTYPE)
                ds.attrs["encoding-type"] = "string-array"
                ds.attrs["encoding-version"] = "0.2.0"

            if palette and uns_out is not None:
                uns_out.move(palette, new_palette)

            batch_condition_updated = updated != batch_condition
            described = f"Renamed obs column '{column}' to '{new_name}'"
            if palette:
                described += f" (and the palette it owns: '{palette}')"
            if batch_condition_updated:
                described += " (and the uns['batch_condition'] entry naming it)"
            entry = make_edit_entry(
                operation="rename_obs_column",
                description=described,
                details={
                    "column": column,
                    "new_name": new_name,
                    "uns_key_renamed": new_palette if palette else None,
                    "batch_condition_updated": batch_condition_updated,
                },
            )

            existing_log = read_edit_log_h5py(f_out)
            log_result = build_edit_log(existing_log, [entry], path)
            if "error" in log_result:
                raise RuntimeError(log_result["error"])
            write_edit_log_h5py(f_out, log_result["json"])

        cleanup_previous_version(path, output_path)

        return {
            "output_path": output_path,
            "column": column,
            "new_name": new_name,
            "uns_key_renamed": new_palette if palette else None,
            "batch_condition_updated": batch_condition_updated,
        }

    except Exception as e:
        return {"error": str(e)}
