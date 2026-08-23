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

from ._io import (
    compact_categories,
    read_categorical_data,
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
    malformed_name_problems,
    obs_index_problems,
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


def _validate_request(
    obs: h5py.Group, uns: h5py.Group | None, column: str, from_value: str, to_value: str
) -> list[str]:
    """Collect every reason the merge cannot proceed.

    All checks run to completion rather than short-circuiting, so a caller who
    got two things wrong learns both in one round trip.
    """
    problems: list[str] = []

    problems += malformed_name_problems([column])
    problems += obs_index_problems(obs, [column], verbing="merging categories in")
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

    return problems


def merge_obs_categories(path: str, column: str, from_value: str, to_value: str) -> dict:
    """Recode every cell in ``from_value`` to ``to_value`` and drop the empty category.

    All-or-nothing: the request is validated before anything is written, and
    the file is left untouched if any check fails. Both values must already be
    categories — creating one is a different operation, and a missing value is
    a caller mistake worth failing on rather than a silent no-op.

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
        ``cells_recoded`` and ``categories_remaining``, or ``{"error": ...}``.
    """
    try:
        path = resolve_latest(path)
        if not Path(path).is_file():
            return {"error": f"File not found: {path}"}

        if not isinstance(column, str) or not isinstance(from_value, str) or not isinstance(to_value, str):
            # MCP-exposed, so the arguments arrive as decoded JSON and may hold
            # numbers or nulls; everything below assumes strings.
            return {
                "error": (
                    f"column, from_value and to_value must be strings; got {column!r}, {from_value!r} and {to_value!r}"
                )
            }

        with h5py.File(path, "r") as f_in:
            obs = require_obs_group(f_in)
            uns = read_uns(f_in)
            problems = _validate_request(obs, uns, column, from_value, to_value)

            if not problems and column not in direct_members(obs):
                problems.append(f"not present in obs: '{column}'")

            categories: list[str] = []
            cells_recoded = 0
            if not problems:
                item = obs[column]
                if not (isinstance(item, h5py.Group) and "categories" in item):
                    problems.append(
                        f"'{column}' is not a categorical column — this tool edits the categories "
                        f"array, not values row by row"
                    )
                else:
                    cats, codes = read_categorical_data(item)
                    categories = list(cats)
                    missing = [v for v in (from_value, to_value) if v not in categories]
                    if missing:
                        problems.append(
                            f"not categories of '{column}': {missing} — both values must already "
                            f"exist (creating a category is a different operation)"
                        )
                    else:
                        cells_recoded = int((codes == categories.index(from_value)).sum())

        if problems:
            return {"error": "Refusing to merge: " + "; ".join(problems)}

        with snapshot_copy(path) as output_path:
            log_error = None
            with h5py.File(output_path, "a") as f_out:
                obs_out = f_out["obs"]
                cats, codes = read_categorical_data(obs_out[column])  # pyright: ignore[reportArgumentType]
                cat_list = list(cats)
                codes[codes == cat_list.index(from_value)] = cat_list.index(to_value)
                new_cats, new_codes = compact_categories(cat_list, codes)
                replace_categorical_column(obs_out, column, new_cats, new_codes)  # pyright: ignore[reportArgumentType]

                entry = make_edit_entry(
                    operation="merge_obs_categories",
                    description=(
                        f"Merged obs['{column}'] category {from_value!r} into {to_value!r} "
                        f"({cells_recoded} cells recoded)"
                    ),
                    details={
                        "column": column,
                        "from_value": from_value,
                        "to_value": to_value,
                        "cells_recoded": cells_recoded,
                    },
                )
                existing_log = read_edit_log_h5py(f_out)
                log_result = build_edit_log(existing_log, [entry], path)
                if "error" in log_result:
                    log_error = log_result
                else:
                    write_edit_log_h5py(f_out, log_result["json"])

                # The rewrite is the whole operation, so it is verified before
                # the snapshot is accepted: a corrupt codes array here would
                # otherwise ship as the new latest version.
                if log_error is None and (integrity_err := verify_categorical_integrity(f_out, [column])):
                    raise RuntimeError(integrity_err)

            if log_error is not None:
                Path(output_path).unlink()
                return log_error

        cleanup_previous_version(path, output_path)

        return {
            "output_path": output_path,
            "column": column,
            "from_value": from_value,
            "to_value": to_value,
            "cells_recoded": cells_recoded,
            "categories_remaining": len(categories) - 1,
        }

    except Exception as e:
        return {"error": str(e)}
