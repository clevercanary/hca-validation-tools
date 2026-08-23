"""Fold one category of a categorical obs column into another.

The remedy half of #527, which detects near-duplicate categorical values: a
producer column carrying ``Prophylatctic Mastectomy`` alongside the correctly
spelled ``Prophylactic Mastectomy`` validates clean, so nothing but a
deliberate merge fixes it.

Deliberately narrower than the general obs-editing design (#236): the value
*is* the row selector, so there is no selection syntax, no ontology
validation (nothing new is introduced — one existing category absorbs
another), no multi-valued fields, and no find-and-replace semantics. Both
categories must already exist.
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np

from ._io import (
    _decode_bytes,
    read_edit_log_h5py,
    read_uns,
    replace_categorical_column,
    verify_categorical_integrity,
    write_edit_log_h5py,
)
from .guards import (
    detect_obs_references,
    direct_members,
    legacy_layout_problems,
    obs_name_problems,
    require_obs_group,
)
from .write import (
    build_edit_log,
    cleanup_previous_version,
    make_edit_entry,
    resolve_latest,
    snapshot_copy,
)

_TERM_ID_SUFFIX = "_ontology_term_id"


def _read_categories(obs: h5py.Group, column: str) -> list[str]:
    """The column's categories, decoded.

    Categories only: the codes array is the expensive half, and the write
    phase is the one place that needs it.
    """
    return [_decode_bytes(v) for v in obs[column]["categories"][:]]


def _column_problems(obs: h5py.Group, column: str, from_value: str, to_value: str) -> list[str]:
    """The column cascade: present, categorical, and holding both values.

    Short-circuits within itself — there is no asking whether an absent column
    is categorical — which is why it is one helper rather than three entries in
    the caller's problem list.
    """
    # Presence is already established by obs_name_problems, which is why this
    # helper runs only when that returned nothing.
    item = obs[column]
    if not (isinstance(item, h5py.Group) and "categories" in item):
        return [f"'{column}' is not a categorical column — this tool edits the categories array, not values row by row"]
    categories = _read_categories(obs, column)
    if non_string := [c for c in categories if not isinstance(c, str)]:
        return [
            f"'{column}' has non-string categories (e.g. {non_string[0]!r}) — this tool "
            f"matches by string value, so it cannot address them"
        ]
    if missing := [v for v in (from_value, to_value) if v not in categories]:
        return [
            f"not categories of '{column}': {missing} — both values must already "
            f"exist (creating a category is a different operation)"
        ]
    return []


def _validate_request(
    obs: h5py.Group, uns: h5py.Group | None, column: str, from_value: str, to_value: str
) -> list[str]:
    """Collect every reason the merge cannot proceed.

    Checks run to completion rather than short-circuiting, so a caller who got
    two things wrong learns both in one round trip.
    """
    problems: list[str] = []

    name_problems = obs_name_problems(obs, [column], verbing="merging categories in")
    problems += name_problems
    problems += legacy_layout_problems(uns)

    if from_value == to_value:
        problems.append(f"from_value and to_value are the same ({from_value!r}) — nothing to merge")

    # This tool's policy per reference mechanism (#614's repair-or-refuse rule):
    #   batch_condition -> ALLOW    (the column keeps its name and identity, so
    #                                the declaration still names a real column;
    #                                nothing dangles)
    #   palettes        -> REFUSE   (see below)
    #   CAP columns     -> REFUSE   (CAP is the system of record; a set is
    #                                stripped and re-copied, never edited here)
    refs = detect_obs_references(uns, [column])
    if refs.cap_columns:
        problems.append(
            f"'{column}' is a CAP annotation-set column — CAP is the system of record for its "
            f"exports, so strip the set and re-copy it from a fresh export rather than editing "
            f"its values here"
        )
    if palette := refs.palettes.get(column):
        # uns['<col>_colors'] is positionally aligned to the categories, so
        # dropping one shifts every colour after it. This tool cannot repair
        # that — it has no way to know which colour the merged-away category
        # owned — and the validator only checks the palette's *length*, so a
        # silently recoloured file can still pass.
        problems.append(
            f"uns[{palette!r}] is a per-category palette positionally aligned to '{column}', so "
            f"removing a category would shift every colour after it. Drop the palette first "
            f"(drop_obs_columns removes it with its column, or delete the uns key), then merge"
        )

    # The coherence guard: a derived label and its term ID must agree. Merging
    # labels alone desyncs them, and the term IDs are the source populate_labels
    # regenerates the labels *from* — so editing the label here would be undone
    # by the next labelling pass, or worse, survive as a disagreement.
    if f"{column}{_TERM_ID_SUFFIX}" in direct_members(obs):
        problems.append(
            f"'{column}' is a derived label: the file also carries "
            f"'{column}{_TERM_ID_SUFFIX}', which is what it is derived from. Merging labels "
            f"alone would leave the two disagreeing — correct the term IDs instead, then "
            f"regenerate the labels with populate_labels"
        )

    # Gated on the *name* only, not on every problem: reading obs[column] needs
    # a well-formed, non-index, present name, but a palette or term-ID refusal
    # must not hide a misspelled value from the same report.
    if not name_problems:
        problems += _column_problems(obs, column, from_value, to_value)

    return problems


def merge_obs_categories(path: str, column: str, from_value: str, to_value: str) -> dict:
    """Recode every cell in ``from_value`` to ``to_value`` and drop the empty category.

    All-or-nothing: the request is validated before anything is written, and
    the file is left untouched if any check fails. Both values must already be
    categories — creating one is a different operation, and a missing value is
    a caller mistake worth failing on rather than a silent no-op.

    Exactly one category disappears: the merged-away one. Categories that are
    empty for their own reasons are left alone, so the result differs from the
    file only where the caller asked.

    The column's compression, chunking and encoding survive the rewrite
    (:func:`replace_categorical_column`), and the expression matrix is never
    loaded: only the one column group is rewritten in a snapshot copy.

    Refuses the obs index, names containing ``/``, a non-categorical column,
    the deprecated top-level CAP layout, CAP annotation-set columns, a column
    carrying a per-category palette, and a derived label whose
    ``*_ontology_term_id`` source is present. Whether the *result* is valid is
    ``validate_schema``'s verdict, not this tool's (#614).

    Args:
        path: Path to an .h5ad file. Auto-resolves to the latest timestamped
            edit snapshot before operating.
        column: The categorical obs column to edit.
        from_value: The category to fold away. Must exist.
        to_value: The category that absorbs it. Must exist.

    Returns:
        Dict with ``output_path``, ``column``, ``from_value``, ``to_value``,
        ``cells_recoded``, ``categories_remaining`` and
        ``regenerate_labels_required``, or ``{"error": ...}``.
    """
    try:
        path = resolve_latest(path)
        if not Path(path).is_file():
            return {"error": f"File not found: {path}"}

        # MCP-exposed, so the arguments arrive as decoded JSON and may hold
        # numbers or nulls; everything below assumes strings. Named per
        # argument, matching rename_obs_column, so the caller knows which.
        non_str = {
            name: value
            for name, value in (("column", column), ("from_value", from_value), ("to_value", to_value))
            if not isinstance(value, str)
        }
        if non_str:
            return {"error": f"must be strings: {non_str}"}

        with h5py.File(path, "r") as f_in:
            obs = require_obs_group(f_in)
            problems = _validate_request(obs, read_uns(f_in), column, from_value, to_value)
            # Resolved from the same read that validated, so the write phase
            # does no discovery (drop.py's pattern).
            categories = [] if problems else _read_categories(obs, column)
            # Merging term IDs is the *recommended* remedy when a label is
            # wrong (see the guard above), so it is allowed — but it leaves the
            # paired label stale until populate_labels runs, and the caller has
            # no other way to know that.
            label_column = column.removesuffix(_TERM_ID_SUFFIX)
            regenerate_labels_required = label_column != column and label_column in direct_members(obs)

        if problems:
            return {"error": "Refusing to merge: " + "; ".join(problems)}

        from_index, to_index = categories.index(from_value), categories.index(to_value)
        new_categories = categories[:from_index] + categories[from_index + 1 :]

        with snapshot_copy(path) as output_path, h5py.File(output_path, "a") as f_out:
            obs_out = require_obs_group(f_out)
            codes = np.asarray(obs_out[column]["codes"][:])
            expected_valid = int((codes >= 0).sum())

            recoded = codes == from_index
            cells_recoded = int(recoded.sum())
            codes[recoded] = to_index
            # Only the merged-away category is removed, so every code above it
            # shifts down one. Recoding first is what makes this correct when
            # to_index > from_index: those cells shift with the rest. Missing
            # codes (-1) are below every index and stay put.
            codes[codes > from_index] -= 1

            replace_categorical_column(obs_out, column, new_categories, codes)

            entry = make_edit_entry(
                operation="merge_obs_categories",
                description=(
                    f"Merged obs['{column}'] category {from_value!r} into {to_value!r} "
                    f"({cells_recoded} cells recoded)"
                    + (
                        f" — obs['{label_column}'] is now stale; run populate_labels"
                        if regenerate_labels_required
                        else ""
                    )
                ),
                details={
                    "column": column,
                    "from_value": from_value,
                    "to_value": to_value,
                    "cells_recoded": cells_recoded,
                },
            )
            log_result = build_edit_log(read_edit_log_h5py(f_out), [entry], path)
            if "error" in log_result:
                raise RuntimeError(log_result["error"])
            write_edit_log_h5py(f_out, log_result["json"])

            # Verified before the snapshot is accepted: a corrupt codes array
            # would otherwise ship as the new latest version. The valid count
            # is checked too — a merge recodes and never nulls, so it is the
            # invariant the recode is most able to break.
            if err := verify_categorical_integrity(f_out, [column], {column: expected_valid}):
                raise RuntimeError(err)

        cleanup_previous_version(path, output_path)

        return {
            "output_path": output_path,
            "column": column,
            "from_value": from_value,
            "to_value": to_value,
            "cells_recoded": cells_recoded,
            "categories_remaining": len(new_categories),
            "regenerate_labels_required": regenerate_labels_required,
        }

    except Exception as e:
        return {"error": str(e)}
