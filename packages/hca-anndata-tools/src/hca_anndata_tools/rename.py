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

from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from ._io import (
    _decode_bytes,
    direct_members,
    obs_index_name,
    read_categorical_data,
    read_edit_log_h5py,
    read_group,
    read_string_dataset,
    read_uns,
    replace_string_dataset,
    write_edit_log_h5py,
)
from .cap import cellxgene_schema_version
from .guards import is_malformed_name, legacy_layout_problems, require_obs_group
from .write import (
    build_edit_log,
    cleanup_previous_version,
    make_edit_entry,
    resolve_latest,
    snapshot_copy_hashed,
)

# Before/after pairs returned for eyeball confirmation, and the cap on IDs
# quoted inside error messages so a 2M-row failure stays readable.
_N_EXAMPLES = 5


def _check_arguments(column, value, prefix_from, prefix_to) -> list[str]:
    """Collect every problem with the call's arguments.

    Shape-checks everything before any file is opened. This is an MCP-exposed
    tool, so the arguments arrive as decoded JSON and may hold numbers or
    nulls; everything downstream assumes strings.
    """
    problems: list[str] = []

    if not isinstance(column, str) or not isinstance(value, str):
        problems.append(f"column and value must be strings; got {column!r} and {value!r}")
    # h5py resolves a name containing '/' as an HDF5 link path (see guards.py);
    # this tool takes one column, so it reports the singular form.
    elif is_malformed_name(column):
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
    a per-row string array; plain string datasets are decoded by h5py in C via
    ``asstr()``. A non-string, non-categorical column can never equal a string
    value, so it selects nothing rather than erroring mid-read.
    """
    item = obs[column]
    if isinstance(item, h5py.Group) and "categories" in item:
        categories, codes = read_categorical_data(item)
        if value not in categories:
            return np.zeros(codes.shape, dtype=bool)
        return codes == categories.get_loc(value)
    if isinstance(item, h5py.Group):
        # Nullable-dtype columns (pandas boolean / Int64 / string) are stored
        # as values+mask groups with no categories; they have no `.dtype`, so
        # without this branch the string check below would crash instead of
        # honoring the select-nothing contract above.
        values = item.get("values")
        shape = values.shape if isinstance(values, h5py.Dataset) else (0,)
        return np.zeros(shape, dtype=bool)
    if h5py.check_string_dtype(item.dtype) is None:  # pyright: ignore[reportAttributeAccessIssue]
        return np.zeros(item.shape, dtype=bool)  # pyright: ignore[reportAttributeAccessIssue]
    return np.asarray(item.asstr()[:] == value)  # pyright: ignore[reportAttributeAccessIssue]


def _compute_new_ids(
    ids: np.ndarray, selected: np.ndarray, prefix_from: str, prefix_to: str
) -> tuple[np.ndarray, list[list[str]]]:
    """Apply the prefix substitution to the selected rows.

    Pure function, separable from the gates on purpose (see the module
    docstring): a future operation mode supplies a different version of this
    step and inherits every gate unchanged.

    Returns the full new ID array and the before/after example pairs.
    """
    new_ids = ids.copy()
    new_ids[selected] = [prefix_to + cell_id[len(prefix_from) :] for cell_id in ids[selected]]
    examples = [[str(ids[i]), str(new_ids[i])] for i in selected[:_N_EXAMPLES]]
    return new_ids, examples


def rename_cell_ids(path: str, column: str, value: str, prefix_from: str, prefix_to: str) -> dict:
    """Rename the cell IDs of rows selected by an obs column value.

    Selects the rows whose obs ``column`` equals ``value`` and rewrites their
    obs-index entries from ``prefix_from + <rest>`` to ``prefix_to + <rest>``.
    All-or-nothing: every gate runs before anything is written, and any
    failure leaves the file untouched with all problems reported together.

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

    No rows move — everything row-shaped (obs columns, ``X``, ``raw.X``,
    ``obsm``/``obsp``) aligns to cells by position, not by ID, so it all rides
    along untouched, and ``raw`` needs nothing: it has no ``obs`` of its own.
    The IDs live in the obs index plus one duplicate copy inside each
    DataFrame stored in ``obsm`` (anndata writes the frame's own index and
    refuses to read a file where the copies disagree), so those are rewritten
    in the same pass — and a file whose copies *already* disagree is refused
    as broken. The index dataset's name is read from ``obs.attrs['_index']``
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
        column: The obs column whose value selects the rows to rename. The
            obs index itself is not a column and is refused as a selector.
        value: The value that selects the rows.
        prefix_from: The prefix every selected ID must currently start with.
        prefix_to: Its replacement.

    Returns:
        Dict with ``output_path``, ``n_selected``, ``n_renamed`` (always equal
        to ``n_selected`` for this operation; the issue asks for both so a
        broader-than-intended selector stays visible), and ``examples`` (up to
        five ``[before, after]`` pairs), or ``{"error": ...}``.
    """
    try:
        problems = _check_arguments(column, value, prefix_from, prefix_to)
        if problems:
            return {"error": "Refusing to rename: " + "; ".join(problems)}

        path = resolve_latest(path)
        if not Path(path).is_file():
            return {"error": f"File not found: {path}"}

        with h5py.File(path, "r") as f_in:
            obs = require_obs_group(f_in)

            version = cellxgene_schema_version(f_in)
            if version:
                return {
                    "error": (
                        f"Refusing to rename: the file declares CellxGENE schema {version}. "
                        f"This tool is scoped to HCA-layout files — renaming an exported file "
                        f"(e.g. a CAP export) forks a record its source system would overwrite; "
                        f"see issues #533 and #596."
                    )
                }

            uns = read_uns(f_in)
            # Parity with drop.py / copy_cap.py (#552): the legacy layout marks
            # a CAP export even when uns['schema_version'] is absent, and
            # renaming a CAP export is what the gate above exists to prevent.
            if legacy_problems := legacy_layout_problems(uns):
                return {"error": f"Refusing to rename: {legacy_problems[0]}"}

            index_name = obs_index_name(obs)
            if column == index_name:
                return {
                    "error": (
                        f"Refusing to rename: '{index_name}' is the obs index, not a column — select by an obs column"
                    )
                }
            # Membership against direct children, not `column in obs`, which
            # would resolve link paths (the '/' trap checked above).
            if column not in direct_members(obs):
                return {"error": f"Refusing to rename: obs column not present: '{column}'"}

            mask = _selection_mask(obs, column, value)
            n_selected = int(mask.sum())
            if n_selected == 0:
                # Gated before the index read: a mistyped selector should not
                # pay for decoding 2M IDs it will never use.
                return {"error": f"Refusing to rename: no rows match obs['{column}'] == {value!r}"}
            # dtype=object (inside read_string_dataset) pins what asstr()
            # already returns: a fixed-width unicode dtype here would silently
            # clip the longer renamed IDs on assignment in _compute_new_ids.
            ids = read_string_dataset(obs, index_name)

            # A DataFrame in obsm carries its own duplicate copy of the cell
            # IDs (anndata writes the frame's index alongside the parent's),
            # and anndata refuses to read a file where the two disagree. So
            # every such copy must be renamed in the same pass — and if one
            # already disagrees, the file is broken in a way a rename would
            # only paper over.
            obsm_df_indexes: list[tuple[str, str]] = []  # (obsm key, index dataset name)
            obsm = read_group(f_in, "obsm")
            if obsm is not None:
                for obsm_key, member in obsm.items():
                    if not (
                        isinstance(member, h5py.Group)
                        and _decode_bytes(member.attrs.get("encoding-type", "")) == "dataframe"
                    ):
                        continue
                    sub_name = obs_index_name(member)
                    sub_ids = read_string_dataset(member, sub_name)
                    if sub_ids.shape != ids.shape or not (sub_ids == ids).all():
                        return {
                            "error": (
                                f"Refusing to rename: obsm[{obsm_key!r}] is a DataFrame whose index "
                                f"does not match the obs index — the file is internally inconsistent "
                                f"and must be repaired before any rename"
                            )
                        }
                    obsm_df_indexes.append((obsm_key, sub_name))

        selected = np.flatnonzero(mask)
        # Count and sample the disagreements rather than materializing them
        # all — on a wrong-prefix call the offenders can be the whole sample.
        bad_count = 0
        bad_examples: list[str] = []
        for cell_id in ids[selected]:
            if not cell_id.startswith(prefix_from):
                bad_count += 1
                if len(bad_examples) < _N_EXAMPLES:
                    bad_examples.append(cell_id)
        if bad_count:
            return {
                "error": (
                    f"Refusing to rename: {bad_count} of {n_selected} selected rows do not start "
                    f"with {prefix_from!r} (e.g. {bad_examples}) — the selector and the prefix "
                    f"disagree about which rows are being renamed"
                )
            }

        # The pre-existing check runs unconditionally, before the rename is
        # even computed: a file whose IDs already collide is refused outright,
        # including when this rename would happen to make the index unique —
        # resolving a collision by renaming one side of it is a curation
        # decision a human must take, not a side effect this tool may write.
        # The two refusals also carry different remedies: repair the file
        # versus change the arguments.
        pre_existing = pd.Index(ids).duplicated()
        if pre_existing.any():
            already = sorted(set(ids[pre_existing]))
            return {
                "error": (
                    f"Refusing to rename: the file already contains {len(already)} duplicate cell "
                    f"IDs before any rename (e.g. {already[:_N_EXAMPLES]}) — repair the file's "
                    f"pre-existing collisions first"
                )
            }

        new_ids, examples = _compute_new_ids(ids, selected, prefix_from, prefix_to)

        duplicated = pd.Index(new_ids).duplicated()
        if duplicated.any():
            colliding = sorted(set(new_ids[duplicated]))
            return {
                "error": (
                    f"Refusing to rename: the result would contain {len(colliding)} duplicate cell "
                    f"IDs (e.g. {colliding[:_N_EXAMPLES]}) — a rename that introduces collisions is "
                    f"the defect this tool exists to fix, not something it will write"
                )
            }

        with snapshot_copy_hashed(path) as (output_path, source_sha256), h5py.File(output_path, "a") as f_out:
            replace_string_dataset(f_out["obs"], index_name, new_ids)  # pyright: ignore[reportArgumentType]
            for obsm_key, sub_name in obsm_df_indexes:
                replace_string_dataset(f_out["obsm"][obsm_key], sub_name, new_ids)  # pyright: ignore[reportArgumentType, reportIndexIssue]

            entry = make_edit_entry(
                operation="rename_cell_ids",
                description=(
                    f"Renamed {n_selected} cell IDs from prefix {prefix_from!r} to {prefix_to!r} "
                    f"for rows where obs['{column}'] == {value!r}"
                ),
                details={
                    "column": column,
                    "value": value,
                    "prefix_from": prefix_from,
                    "prefix_to": prefix_to,
                    "n_selected": n_selected,
                    "n_renamed": n_selected,
                    "examples": examples,
                    "obsm_dataframes_updated": [obsm_key for obsm_key, _ in obsm_df_indexes],
                },
            )
            existing_log = read_edit_log_h5py(f_out)
            log_result = build_edit_log(existing_log, [entry], path, source_sha256)
            if "error" in log_result:
                raise RuntimeError(log_result["error"])
            write_edit_log_h5py(f_out, log_result["json"])

        cleanup_previous_version(path, output_path)

        return {
            "output_path": output_path,
            "n_selected": n_selected,
            "n_renamed": n_selected,
            "examples": examples,
        }

    except Exception as e:
        # No unlink here: snapshot_copy_hashed removes the snapshot itself.
        return {"error": str(e)}
