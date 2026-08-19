"""Rename cell IDs (the obs index) for rows selected by an obs column value.

Built for one defect class: a sample's cell IDs lost a distinguishing
segment somewhere in a pipeline, and the fix is to select that sample's rows
and put the segment back (#533). The operation is deliberately narrow — a
prefix substitution, not a mapping or a pattern rewrite — because the safety
comes from two independent witnesses that must agree before anything is
written: the obs selector names the rows, and the prefix check confirms every
one of them carries the ID form the caller expects. A more general rewrite
would collapse that to a single witness. Widening (a ``mapping=`` or
``suffix_from=`` mode) waits for a real case that needs it; the gates here are
form-independent and would carry over.
"""

from __future__ import annotations

import contextlib
import shutil
from pathlib import Path

import h5py
import numpy as np

from ._io import (
    _decode_bytes,
    read_categorical_data,
    read_edit_log_h5py,
    write_edit_log_h5py,
)
from .inspect import _read_schema_version
from .write import (
    build_edit_log,
    cleanup_previous_version,
    generate_output_path,
    make_edit_entry,
    resolve_latest,
)

# Before/after pairs returned for eyeball confirmation, and the cap on IDs
# quoted inside error messages so a 2M-row failure stays readable.
_N_EXAMPLES = 5


def _check_arguments(where, prefix_from, prefix_to) -> list[str]:
    """Collect every problem with the call's arguments.

    Shape-checks everything before any file is opened. This is an MCP-exposed
    tool, so the arguments arrive as decoded JSON and may hold numbers, nulls,
    or the wrong containers; everything downstream assumes strings.
    """
    problems: list[str] = []

    if not isinstance(where, dict) or len(where) != 1:
        problems.append("where must be a dict with exactly one {column: value} pair")
    else:
        column, value = next(iter(where.items()))
        if not isinstance(column, str) or not isinstance(value, str):
            problems.append(f"where must map a column name to a string value; got {{{column!r}: {value!r}}}")
        # h5py resolves a name containing '/' as an HDF5 link path, not a dict
        # key (see drop.py for the full trap) — reject before any lookup.
        elif "/" in column or not column.strip():
            problems.append(f"not a valid obs column name (cannot contain '/' or be blank): {column!r}")

    if not isinstance(prefix_from, str) or not prefix_from:
        problems.append("prefix_from must be a non-empty string")
    if not isinstance(prefix_to, str):
        problems.append("prefix_to must be a string")
    elif prefix_from == prefix_to:
        problems.append("prefix_from and prefix_to are identical — nothing would change")

    return problems


def _selection_mask(obs: h5py.Group, column: str, value: str) -> np.ndarray:
    """Boolean mask of the rows whose ``column`` equals ``value``.

    Categorical columns are matched through their codes without materializing
    a per-row string array; anything else is read and decoded in full.
    """
    item = obs[column]
    if isinstance(item, h5py.Group) and "categories" in item:
        categories, codes = read_categorical_data(item)
        if value not in categories:
            return np.zeros(codes.shape, dtype=bool)
        return codes == categories.get_loc(value)
    values = np.array([_decode_bytes(v) for v in item[:]], dtype=object)
    return values == value


def _compute_new_ids(
    ids: list[str], mask: np.ndarray, prefix_from: str, prefix_to: str
) -> tuple[list[str], list[list[str]]]:
    """Apply the prefix substitution to the selected rows.

    Pure function, separable from the gates on purpose (see the module
    docstring): a future operation mode supplies a different version of this
    step and inherits every gate unchanged.

    Returns the full new ID list and the before/after example pairs.
    """
    new_ids = list(ids)
    examples: list[list[str]] = []
    for i in np.flatnonzero(mask):
        old = ids[i]
        new_ids[i] = prefix_to + old[len(prefix_from) :]
        if len(examples) < _N_EXAMPLES:
            examples.append([old, new_ids[i]])
    return new_ids, examples


def rename_cell_ids(path: str, where: dict, prefix_from: str, prefix_to: str) -> dict:
    """Rename the cell IDs of rows selected by an obs column value.

    Selects the rows whose obs ``column`` equals ``value`` (the single pair in
    ``where``) and rewrites their obs-index entries from
    ``prefix_from + <rest>`` to ``prefix_to + <rest>``. All-or-nothing: every
    gate runs before anything is written, and any failure leaves the file
    untouched with all problems reported together.

    The gates, in the order a caller hits them:

    * **HCA-layout files only.** A file declaring a CellxGENE
      ``uns['schema_version']`` is refused outright. The motivating case is
      the CAP export of an atlas: CAP — not the exported file — is the system
      of record for its annotations, so renaming the export forks a file CAP
      would overwrite on its next export (#533, #596).
    * **The selector must match.** Zero matching rows is an error, not a
      no-op — the caller named specific rows, so finding none is a mistake
      worth failing on.
    * **Selector and substitution must agree.** Every selected row's ID must
      start with ``prefix_from``; a partial match means the two witnesses
      disagree about which rows are being renamed.
    * **Uniqueness is a hard gate.** The *entire* resulting index is checked
      before writing, and a collision is reported with the colliding IDs — a
      rename that introduces duplicate cell IDs is the exact defect this tool
      exists to fix.

    Only the index dataset is rewritten — no rows move. Everything row-shaped
    (obs columns, ``X``, ``raw.X``, ``obsm``/``obsp``) aligns to cells by
    position, not by ID, so it all rides along untouched; the IDs exist in
    exactly one place in the file. ``raw`` needs nothing: it has no ``obs`` of
    its own. The index dataset's name is read from ``obs.attrs['_index']``
    rather than assumed — HCA-layout files are not uniform here (``cellID``
    on the breast integrated object).

    Writes a new timestamped snapshot with an edit-log entry, like every
    other mutating tool. That means copying the whole file to change a few
    thousand strings — deliberate: the snapshot convention is what keeps a
    curation history auditable, and an in-place rewrite of an HDF5
    variable-length string dataset is unproven here.

    Args:
        path: Path to an .h5ad file. Auto-resolves to the latest timestamped
            edit snapshot before operating.
        where: Exactly one ``{column: value}`` pair naming the obs column and
            the value that selects the rows to rename. The obs index itself
            is not a column and is refused as a selector.
        prefix_from: The prefix every selected ID must currently start with.
        prefix_to: Its replacement.

    Returns:
        Dict with ``output_path``, ``n_selected``, ``n_renamed`` (always equal
        to ``n_selected`` for this operation, reported separately so a future
        mode where they can differ keeps the same shape), and ``examples``
        (up to five ``[before, after]`` pairs), or ``{"error": ...}``.
    """
    output_path = None
    try:
        problems = _check_arguments(where, prefix_from, prefix_to)
        if problems:
            return {"error": "Refusing to rename: " + "; ".join(problems)}
        column, value = next(iter(where.items()))

        path = resolve_latest(path)
        if not Path(path).is_file():
            return {"error": f"File not found: {path}"}

        with h5py.File(path, "r") as f_in:
            obs = f_in.get("obs")
            if obs is None:
                return {"error": "File has no obs group"}
            if not isinstance(obs, h5py.Group):
                return {"error": "obs is not a group — the file predates the modern h5ad layout"}

            version = _read_schema_version(f_in)
            if version:
                return {
                    "error": (
                        f"Refusing to rename: the file declares CellxGENE schema {version}. "
                        f"This tool is scoped to HCA-layout files — renaming an exported file "
                        f"(e.g. a CAP export) forks a record its source system would overwrite; "
                        f"see issues #533 and #596."
                    )
                }

            index_name = _decode_bytes(obs.attrs.get("_index", "_index"))
            if column == index_name:
                return {
                    "error": (
                        f"Refusing to rename: '{index_name}' is the obs index, not a column — select by an obs column"
                    )
                }
            # Membership against direct children, not `column in obs`, which
            # would resolve link paths (the '/' trap checked above).
            if column not in set(obs.keys()):
                return {"error": f"Refusing to rename: obs column not present: '{column}'"}

            ids = [_decode_bytes(v) for v in obs[index_name][:]]  # pyright: ignore[reportIndexIssue]
            mask = _selection_mask(obs, column, value)

        n_selected = int(mask.sum())
        if n_selected == 0:
            return {"error": f"Refusing to rename: no rows match obs['{column}'] == {value!r}"}

        bad_prefix = [ids[i] for i in np.flatnonzero(mask) if not ids[i].startswith(prefix_from)]
        if bad_prefix:
            shown = bad_prefix[:_N_EXAMPLES]
            return {
                "error": (
                    f"Refusing to rename: {len(bad_prefix)} of {n_selected} selected rows do not start "
                    f"with {prefix_from!r} (e.g. {shown}) — the selector and the prefix disagree about "
                    f"which rows are being renamed"
                )
            }

        new_ids, examples = _compute_new_ids(ids, mask, prefix_from, prefix_to)

        if len(set(new_ids)) != len(new_ids):
            seen: set[str] = set()
            collisions: list[str] = []
            for cell_id in new_ids:
                if cell_id in seen:
                    collisions.append(cell_id)
                else:
                    seen.add(cell_id)
            shown = sorted(set(collisions))[:_N_EXAMPLES]
            return {
                "error": (
                    f"Refusing to rename: the result would contain {len(collisions)} duplicate cell "
                    f"IDs (e.g. {shown}) — a rename that introduces collisions is the defect this "
                    f"tool exists to fix, not something it will write"
                )
            }

        output_path = generate_output_path(path)
        shutil.copy2(path, output_path)

        log_error = None
        with h5py.File(output_path, "a") as f_out:
            index_ds = f_out["obs"][index_name]  # pyright: ignore[reportIndexIssue]
            attrs = dict(index_ds.attrs)  # pyright: ignore[reportAttributeAccessIssue]
            compression = index_ds.compression  # pyright: ignore[reportAttributeAccessIssue]
            compression_opts = index_ds.compression_opts  # pyright: ignore[reportAttributeAccessIssue]
            chunks = index_ds.chunks  # pyright: ignore[reportAttributeAccessIssue]
            del f_out["obs"][index_name]  # pyright: ignore[reportIndexIssue]
            new_ds = f_out["obs"].create_dataset(  # pyright: ignore[reportAttributeAccessIssue]
                index_name,
                data=np.array(new_ids, dtype=object),
                dtype=h5py.string_dtype(encoding="utf-8"),
                compression=compression,
                compression_opts=compression_opts,
                chunks=chunks,
            )
            for key, attr_value in attrs.items():
                new_ds.attrs[key] = attr_value

            entry = make_edit_entry(
                operation="rename_cell_ids",
                description=(
                    f"Renamed {n_selected} cell IDs from prefix {prefix_from!r} to {prefix_to!r} "
                    f"for rows where obs['{column}'] == {value!r}"
                ),
                details={
                    "where": {column: value},
                    "prefix_from": prefix_from,
                    "prefix_to": prefix_to,
                    "n_selected": n_selected,
                    "n_renamed": n_selected,
                    "examples": examples,
                },
            )
            existing_log = read_edit_log_h5py(f_out)
            log_result = build_edit_log(existing_log, [entry], path)
            if "error" in log_result:
                log_error = log_result
            else:
                write_edit_log_h5py(f_out, log_result["json"])

        if log_error is not None:
            Path(output_path).unlink()
            return log_error

        cleanup_previous_version(path, output_path)

        return {
            "output_path": output_path,
            "n_selected": n_selected,
            "n_renamed": n_selected,
            "examples": examples,
        }

    except Exception as e:
        if output_path and Path(output_path).is_file():
            with contextlib.suppress(OSError):
                Path(output_path).unlink()
        return {"error": str(e)}
