"""Rename a single obs column in an h5ad file.

The third member of the obs-column family, alongside
:mod:`hca_anndata_tools.drop` and :mod:`hca_anndata_tools.strip`. The three
answer different questions about a producer column that does not belong as it
stands: strip removes a fixed privacy list, drop removes caller-named columns
whose data is redundant, and this renames a column whose *data* is real and
whose *name* is wrong.

That distinction is why this module carries none of drop's schema-tier
refusals. Dropping an optional schema column discards producer data that
cannot be reconstructed; renaming preserves every value and is reversible by
renaming back. Promoting producer data into its canonical schema name is a
normal curation act — nee2023's ``cell_type_label`` holds the authors' own
cell-type calls, and ``author_cell_type`` is the schema's name for exactly
that (see clevercanary/hca-ingest-coordination#24).
"""

from __future__ import annotations

import h5py
import numpy as np

from ._io import (
    _decode_bytes,
    read_column_order,
    read_edit_log_h5py,
    write_edit_log_h5py,
)
from .drop import _read_batch_condition
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
        return bool((item["codes"][:] == -1).all())  # -1 is pandas' missing code
    if isinstance(item, h5py.Dataset) and item.dtype.kind == "f":
        return bool(np.isnan(item[:]).all())
    return False


def _validate_request(obs: h5py.Group, uns: h5py.Group | None, column: str, new_name: str) -> list[str]:
    """Collect every reason the rename cannot proceed.

    All checks run to completion rather than short-circuiting, so a caller who
    got two things wrong learns both in one round trip.
    """
    problems: list[str] = []

    # h5py resolves a name containing '/' as an HDF5 link path rather than a
    # dict key: a leading slash resolves from the file root and inner slashes
    # traverse subgroups, so `move("/X", ...)` would relocate the expression
    # matrix. Every check below compares plain strings, so rejecting these up
    # front is what keeps them agreeing with what the move would actually do.
    malformed = [n for n in (column, new_name) if "/" in n or not n.strip()]
    if malformed:
        problems.append(f"not valid obs column names (a column name cannot contain '/' or be blank): {malformed}")

    if column == new_name:
        problems.append(f"'{column}' is already the column's name")

    index_name = _decode_bytes(obs.attrs.get("_index", "_index"))
    if index_name in (column, new_name):
        problems.append(f"'{index_name}' is the obs index, not a column — renaming it would destroy the file")

    # Membership against the group's direct children rather than `in obs`,
    # which would resolve link paths (see the malformed check above).
    #
    # A malformed name is excluded so each bad name is reported once. "/X" is
    # necessarily absent from obs.keys() too, and listing it under both
    # problems would imply its only fault was being missing — sending a caller
    # to hunt for a typo rather than read the path-name rule. drop.py:155 makes
    # the same exclusion for the same reason.
    members = set(obs.keys())
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

    The gates, in the order a caller hits them:

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

    Note this carries no schema-tier refusal, unlike ``drop_obs_columns``.
    Renaming preserves every value and is undone by renaming back, so
    promoting a producer column into its canonical schema name is allowed and
    is the motivating case. Renaming a schema-required column *away* is
    likewise allowed and will fail validation loudly. Two caveats on that
    reversibility: overwriting an empty destination does not restore that
    column's entry or its declared categories on the way back, and a rename
    followed by a drop reaches what ``drop_obs_columns`` alone refuses — both
    operations land in the edit log, which is what keeps that accountable.

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
        path = resolve_latest(path)

        with h5py.File(path, "r") as f_in:
            obs = f_in.get("obs")
            if not isinstance(obs, h5py.Group):
                return {"error": "File has no obs group, or obs is not a group"}
            uns = f_in.get("uns")
            if not isinstance(uns, h5py.Group):
                uns = None
            problems = _validate_request(obs, uns, column, new_name)
            palette = f"{column}_colors" if uns is not None and f"{column}_colors" in uns else None
            batch_condition = _read_batch_condition(uns)

        if problems:
            return {"error": "Refusing to rename: " + "; ".join(problems)}

        # h5py closes before snapshot_copy's cleanup runs, which is the ordering
        # the unlink needs: removing an open HDF5 handle raises on Windows.
        with snapshot_copy(path) as output_path, h5py.File(output_path, "a") as f_out:
            # Validation established that an existing destination is empty, so
            # this discards nothing. Its palette goes too: left behind it would
            # describe the incoming column's data, which is worse than an
            # orphan because a length match makes it silently wrong.
            if new_name in f_out["obs"]:
                del f_out["obs"][new_name]
                if f"{new_name}_colors" in f_out["uns"]:
                    del f_out["uns"][f"{new_name}_colors"]
            f_out["obs"].move(column, new_name)

            # uns['batch_condition'] names the columns that define the
            # experiment's batches. A rename leaves it pointing at a column the
            # file no longer has, and unlike a drop this knows exactly what to
            # point it at instead — the same column still defines the batches,
            # only its name changed. Refusing here would be a dead end: set_uns
            # validates every entry against the obs columns present, so the new
            # name cannot be written before the rename, and the rename cannot
            # happen while the old name is referenced.
            if column in batch_condition:
                updated = [new_name if c == column else c for c in batch_condition]
                del f_out["uns"]["batch_condition"]
                ds = f_out["uns"].create_dataset(
                    "batch_condition", data=np.array(updated, dtype=object), dtype=_STR_DTYPE
                )
                ds.attrs["encoding-type"] = "string-array"
                ds.attrs["encoding-version"] = "0.2.0"

            # Substituted in place rather than via update_column_order,
            # which appends: a renamed column keeps its position, so a
            # reader diffing two versions sees one name change and not a
            # reordering. When an empty destination was replaced, its own
            # entry goes first — otherwise the substitution would leave the
            # name listed twice.
            order = [c for c in read_column_order(f_out["obs"]) if c != new_name]
            f_out["obs"].attrs["column-order"] = [new_name if c == column else c for c in order]

            if palette:
                if f"{new_name}_colors" in f_out["uns"]:
                    del f_out["uns"][f"{new_name}_colors"]
                f_out["uns"].move(palette, f"{new_name}_colors")

            described = f"Renamed obs column '{column}' to '{new_name}'"
            if palette:
                described += f" (and the palette it owns: '{palette}')"
            entry = make_edit_entry(
                operation="rename_obs_column",
                description=described,
                details={
                    "column": column,
                    "new_name": new_name,
                    "uns_key_renamed": f"{new_name}_colors" if palette else None,
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
            "uns_key_renamed": f"{new_name}_colors" if palette else None,
            "batch_condition_updated": column in batch_condition,
        }

    except Exception as e:
        return {"error": str(e)}
