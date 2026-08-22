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


def _is_empty_column(obs: h5py.Group, name: str) -> bool:
    """True when every value in an obs column is null.

    Deliberately conservative: it answers "can this be overwritten without
    losing anything", so it says yes only where nullness is representable and
    provable. A categorical stores missing as code ``-1``, and a float array
    stores it as NaN. Integer, boolean and string arrays have no null value,
    so a caller who wants one of those gone should drop it first and see the
    count they are discarding.
    """
    item = obs[name]
    if isinstance(item, h5py.Group):  # categorical: categories + codes
        codes = item.get("codes")
        if not isinstance(codes, h5py.Dataset):
            return False
        return bool((codes[:] == -1).all())
    if isinstance(item, h5py.Dataset) and item.dtype.kind == "f":
        values = item[:]
        return bool((values != values).all())  # NaN is the only self-inequality
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
    members = set(obs.keys())
    if column not in members:
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

    # uns['batch_condition'] declares which columns define the experiment's
    # batches, so a rename would leave it naming a column that no longer
    # exists. Refused rather than rewritten: editing that declaration is a
    # curation decision, not a side effect of renaming.
    if column in _read_batch_condition(uns):
        problems.append(
            f"'{column}' is referenced by uns['batch_condition'] — renaming it would leave "
            f"that declaration naming a column the file no longer has. Edit "
            f"uns['batch_condition'] first if the rename is intended"
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

    * **Neither name may be an HDF5 link path** (contain ``/``) or be blank.
    * **The source must exist**, and must not be the obs index.
    * **The destination must not already exist** — unless it is provably
      empty, in which case it is overwritten. See :func:`_is_empty_column`.
    * **The column must not be named by** ``uns['batch_condition']``, which
      would be left referring to a column the file no longer has.

    Note this carries no schema-tier refusal, unlike ``drop_obs_columns``.
    Renaming preserves every value and is undone by renaming back, so
    promoting a producer column into its canonical schema name is allowed and
    is the motivating case. Renaming a schema-required column *away* is
    likewise allowed and will fail validation loudly.

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
        Dict with ``output_path``, ``column``, ``new_name`` and
        ``uns_key_renamed`` (the palette that travelled, or None) on success,
        or ``{"error": ...}``.
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
            # Resolved from the same read that validated, so the write phase
            # does no discovery.
            palette = f"{column}_colors" if uns is not None and f"{column}_colors" in uns else None
            replacing_empty = new_name in set(obs.keys())

        if problems:
            return {"error": "Refusing to rename: " + "; ".join(problems)}

        # h5py closes before snapshot_copy's cleanup runs, which is the ordering
        # the unlink needs: removing an open HDF5 handle raises on Windows.
        with snapshot_copy(path) as output_path, h5py.File(output_path, "a") as f_out:
            if replacing_empty:
                del f_out["obs"][new_name]
            f_out["obs"].move(column, new_name)

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
        }

    except Exception as e:
        return {"error": str(e)}
