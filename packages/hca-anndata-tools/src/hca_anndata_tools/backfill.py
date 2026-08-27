"""Backfill missing obs values in a target h5ad from a source h5ad, joined on cell ID.

Built for metadata lost in integration (#534): cells in an integrated object
carry placeholders ("unknown", NaN) for columns whose true values survive in
the source dataset the cells came from. The join key is the obs index, and the
never-overwrite rule is the core contract — a value is written only where the
target holds nothing (NaN, empty, or a recognized placeholder). A real target
value that disagrees with the source is left alone and reported as a conflict.

Partial overlap is the normal case, not an oddity: an integrated object
filters cells and draws from several sources, so source cells absent from the
target are skipped silently and target cells absent from the source simply
stay as they are. Run once per source; each run resolves the newest edit
snapshot of the target and replaces the previous snapshot on success, so
repeated runs chain without accumulating file copies.
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from ._io import (
    DEFAULT_PLACEHOLDERS,
    check_duplicate_ids,
    direct_members,
    holds_string_values,
    is_missing_value,
    masked_categories_reason,
    obs_index_name,
    read_categories,
    read_edit_log_h5py,
    read_element,
    read_group,
    read_index,
    read_uns,
    replace_categorical_column,
    replace_string_dataset,
    unwritable_element_reason,
    verify_categorical_integrity,
    write_edit_log_h5py,
)
from .guards import is_malformed_name, legacy_layout_problems
from .write import (
    _compute_sha256,
    build_edit_log,
    cleanup_previous_version,
    make_edit_entry,
    parse_edit_log,
    resolve_latest,
    snapshot_copy_hashed,
)

# Cap on the conflict examples quoted per column, and on the duplicate IDs
# quoted in error messages, so a large disagreement stays readable.
_N_EXAMPLES = 5


def _check_arguments(columns) -> list[str]:
    """Collect every problem with the call's arguments.

    Shape-checks before any file is opened. This is an MCP-exposed tool, so
    the arguments arrive as decoded JSON and may hold numbers or nulls;
    everything downstream assumes strings.
    """
    if not isinstance(columns, list) or not columns:
        return ["columns must be a non-empty list of obs column names"]
    problems: list[str] = []
    for col in columns:
        # h5py resolves a name containing '/' as an HDF5 link path, not a
        # dict key (see drop.py for the full trap) — reject before any lookup.
        if not isinstance(col, str) or is_malformed_name(col):
            problems.append(f"not a valid obs column name (must be a non-blank string without '/'): {col!r}")
    if len(set(columns)) != len(columns):
        problems.append("columns contains duplicates")
    return problems


def _read_column(
    obs: h5py.Group, col: str, placeholders: set[str], side: str, is_target: bool = False
) -> tuple[dict | None, str | None]:
    """Read one obs column into a uniform shape: (column dict, error).

    The dict holds ``kind`` ('categorical' or 'string'), per-row ``values``
    (object array of strings; a missing row holds None — or pd.NA when its
    code points at a masked category), and a ``missing``
    mask (NaN, masked, empty, or placeholder). Categorical columns also carry
    ``cats``/``codes``. Layouts with no missing vocabulary this tool
    understands (numeric or boolean values, plain or nullable) are refused
    rather than guessed at.

    ``is_target`` marks the side whose columns get rewritten. It changes the
    verdict on two shapes this tool can *read* but not write back: a
    nullable-string column (``replace_string_dataset`` needs a Dataset to
    copy layout from — refused before the snapshot), and a categorical with
    masked categories (a void category has no value a rewrite could keep).
    On the read-only source side both shapes just read.

    The missing predicate runs once per distinct value, never per row — the
    categorical branch works on the categories, the string branch factorizes
    first (a metadata column on a 2M-cell file has few distinct values).
    """
    item = obs[col]
    if isinstance(item, h5py.Group) and "categories" in item:
        # A numeric/boolean pandas Categorical is stored the same way; its
        # values have no missing vocabulary here either, so refuse it with
        # the clear error rather than tripping over .strip() on a non-string.
        # An EMPTY categories array (an all-NaN column) is fine — anndata
        # writes it with a non-string dtype, but there is nothing to compare.
        # The categories may themselves be a nullable-string-array *group*
        # (the liver shape, hca-validation-tools#638) — still string values,
        # and probing .dtype on the group would leak an h5py internal.
        cats_item = item["categories"]
        if len(cats_item) and not holds_string_values(cats_item):  # pyright: ignore[reportArgumentType]
            return None, (
                f"{side} column '{col}' is a categorical of non-string values — "
                "only string-valued categorical and string obs columns can be backfilled"
            )
        cats = read_categories(item)  # pyright: ignore[reportArgumentType]
        if is_target and (reason := masked_categories_reason(cats, f"Target column '{col}'")):
            return None, reason
        codes: np.ndarray = item["codes"][:]  # pyright: ignore[reportIndexIssue, reportAssignmentType]
        cat_values = np.array(list(cats), dtype=object)
        cat_missing = np.array([is_missing_value(c, placeholders) for c in cats], dtype=bool)
        valid = codes >= 0
        values = np.full(len(codes), None, dtype=object)
        values[valid] = cat_values[codes[valid]]
        missing = ~valid
        missing[valid] = cat_missing[codes[valid]]
        return {
            "kind": "categorical",
            "cats": list(cats),
            "codes": codes,
            "ordered": bool(item.attrs["ordered"]),
            "values": values,
            "missing": missing,
        }, None
    # Numeric, boolean, and their nullable group counterparts all land here:
    # no string values to compare, one verdict.
    if not holds_string_values(item):
        return None, (
            f"{side} column '{col}' is not categorical or string — only those obs column types can be backfilled"
        )
    # A nullable-string target reads fine but replace_string_dataset needs a
    # Dataset to copy layout from — refuse before the snapshot. A Dataset
    # target passes through (reason is None).
    if is_target and (reason := unwritable_element_reason(item, f"Target column '{col}'")):
        return None, f"Refusing to backfill: {reason}"
    values = read_element(item)
    # factorize sends pd.NA (a masked entry) to code -1 — missing, which is
    # exactly what a masked source value means here.
    codes, uniques = pd.factorize(values)
    uniq_missing = np.array([is_missing_value(u, placeholders) for u in uniques], dtype=bool)
    valid = codes >= 0
    missing = ~valid
    missing[valid] = uniq_missing[codes[valid]]
    return {"kind": "string", "values": values, "missing": missing}, None


def _read_obs_for_backfill(
    path: str, columns: list[str], placeholders: set[str], side: str, is_target: bool = False
) -> tuple[dict | None, dict | None]:
    """Read the obs index and the requested columns from one file.

    Returns (data, error_result); exactly one is set. ``data`` holds ``index``
    (a pandas Index of cell IDs) and ``columns`` (column name → the dict from
    :func:`_read_column`). ``is_target`` marks the mutation candidate: it adds
    the legacy-CAP-layout refusal and the edit-log read (``raw_log``); ``side``
    is display text for messages only.
    """
    with h5py.File(path, "r") as f:
        obs = read_group(f, "obs")
        if obs is None:
            return None, {"error": f"{side} file has no obs group: {path}"}
        if is_target:
            uns = read_uns(f)
            # Parity with drop.py / rename.py (#552): mutating tools refuse
            # the deprecated top-level CAP layout.
            if legacy_problems := legacy_layout_problems(uns):
                return None, {"error": f"Refusing to backfill: the {side.lower()} file — {legacy_problems[0]}"}
        index_name = obs_index_name(obs)
        obs_keys = direct_members(obs)
        for col in columns:
            if col == index_name:
                return None, {
                    "error": f"'{index_name}' is the {side.lower()} obs index (the join key), not a backfillable column"
                }
            if col not in obs_keys:
                return None, {"error": f"{side} file has no obs column '{col}'"}
        # read_index refuses a masked index — the join key cannot contain
        # nulls. Duplicates stay a caller concern; see read_index.
        index = pd.Index(read_index(obs, index_name, side))
        dupe_err = check_duplicate_ids(index, f"{side} cells")
        if dupe_err:
            return None, {"error": dupe_err}
        col_data = {}
        for col in columns:
            data, err = _read_column(obs, col, placeholders, side, is_target=is_target)
            if err:
                return None, {"error": err}
            col_data[col] = data
        result = {"index": index, "columns": col_data}
        if is_target:
            result["raw_log"] = read_edit_log_h5py(f)
        return result, None


def _fill_categorical(obs: h5py.Group, col: str, data: dict, fill_rows: np.ndarray, fill_values: np.ndarray) -> None:
    """Rewrite a categorical column with the fills applied.

    Extends the categories with any new fill values, then drops exactly the
    categories the fills left unused (the placeholder being replaced,
    typically). A category that was already unused before the fill is kept —
    the declared vocabulary is set data this tool must not touch.
    """
    cats: list[str] = data["cats"]
    codes: np.ndarray = data["codes"]
    new_cats = cats + sorted(set(fill_values) - set(cats))
    # Work in int64: the new category positions can overflow the original
    # codes dtype before the unused-category drop shrinks the range.
    work = codes.astype(np.int64)
    work[fill_rows] = pd.Index(new_cats).get_indexer(fill_values)

    used_before = np.zeros(len(new_cats), dtype=bool)
    used_before[codes[codes >= 0]] = True
    used_after = np.zeros(len(new_cats), dtype=bool)
    used_after[work[work >= 0]] = True
    keep = np.flatnonzero(used_after | ~used_before)

    final_cats = [new_cats[i] for i in keep]
    lookup = np.full(len(new_cats), -1, dtype=np.int64)
    lookup[keep] = np.arange(len(keep))
    valid = work >= 0
    final_codes = np.full(work.shape, -1, dtype=np.int64)
    final_codes[valid] = lookup[work[valid]]
    replace_categorical_column(obs, col, final_cats, final_codes)


def _verify_backfill(f: h5py.File, per_column: dict, fills: dict, placeholders: set[str]) -> str | None:
    """Re-read every filled column from the output and check the result.

    Two independent checks per column: the filled rows hold exactly the
    values the source supplied, and the missing count landed on the predicted
    ``missing_after``. Returns an error message, or None if all pass.
    """
    obs = f["obs"]
    for col, (fill_rows, fill_values) in fills.items():
        data, err = _read_column(obs, col, placeholders, "Output")  # pyright: ignore[reportArgumentType]
        if err is not None:
            return err
        assert data is not None
        if not (data["values"][fill_rows] == fill_values).all():
            return f"Verification failed: column '{col}' does not hold the filled values"
        actual_missing = int(data["missing"].sum())
        expected_missing = per_column[col]["missing_after"]
        if actual_missing != expected_missing:
            return (
                f"Verification failed: column '{col}' has {actual_missing} missing values, expected {expected_missing}"
            )
    return None


def backfill_obs_from_source(target_path: str, source_path: str, columns: list[str]) -> dict:
    """Copy obs values from a source h5ad into a target, filling only gaps.

    Joins source cells to target cells on the obs index and, for each
    requested column, writes the source value into every matched target cell
    whose current value is missing — NaN, empty, or a recognized placeholder
    such as "unknown" (the same list replace_placeholder_values uses). Values
    already set in the target are never touched: where a set value disagrees
    with the source it is counted as a conflict and reported with examples,
    not overwritten and not an error. Source cells with no matching target
    cell are skipped silently — the target may have filtered them out.

    Uses h5py copy-and-patch (the replace_placeholder_values technique): the
    expression matrix is never loaded, and only the filled obs columns are
    rewritten, preserving their compression settings. Categorical columns get
    their categories extended for new values and cleaned of categories the
    fill left unused. If no column has anything to fill, nothing is written
    and an error is returned carrying the full per-column stats.

    Writes a new timestamped snapshot of the target with an edit-log entry,
    like every other mutating tool, and deletes the previous snapshot (never
    the original). The source file is read-only and never modified. Both
    paths auto-resolve to their latest timestamped edit snapshot, so per-source
    runs against the same target chain naturally.

    If the target's cell IDs need repair (e.g. a rename_cell_ids fix), do that
    **before** backfilling — this tool propagates values by cell identity and
    trusts the join.

    Args:
        target_path: Path to the .h5ad file to fill.
        source_path: Path to the .h5ad file holding the values.
        columns: Obs column names to backfill. Each must exist in both files
            as a categorical or string column.

    Returns:
        Dict with ``output_path``, ``source``, ``n_source_cells``,
        ``n_target_cells``, ``n_matched``, ``total_filled``, and
        ``per_column`` — for each column: ``filled``, ``already_set``,
        ``conflicts`` + ``conflict_examples`` (up to five
        ``[cell_id, target_value, source_value]``), ``source_missing``
        (target missing but source missing too), ``unmatched`` (target
        missing with no source cell to consult), ``missing_before`` /
        ``missing_after`` over all target cells, and ``pct_full_after`` —
        or ``{"error": ...}``.
    """
    try:
        problems = _check_arguments(columns)
        if problems:
            return {"error": "Refusing to backfill: " + "; ".join(problems)}

        target_path = resolve_latest(target_path)
        source_path = resolve_latest(source_path)
        for side, path in (("Target", target_path), ("Source", source_path)):
            if not Path(path).is_file():
                return {"error": f"{side} file not found: {path}"}
        if Path(target_path).resolve() == Path(source_path).resolve():
            return {"error": "Source and target are the same file"}

        placeholders = {v.lower() for v in DEFAULT_PLACEHOLDERS}

        target, err = _read_obs_for_backfill(target_path, columns, placeholders, "Target", is_target=True)
        if err is not None:
            return err
        assert target is not None
        source, err = _read_obs_for_backfill(source_path, columns, placeholders, "Source")
        if err is not None:
            return err
        assert source is not None

        target_index: pd.Index = target["index"]
        n_target = len(target_index)
        n_source = len(source["index"])

        # --- Join on cell ID ---
        indexer = source["index"].get_indexer(target_index)
        matched_rows = np.flatnonzero(indexer >= 0)
        n_matched = len(matched_rows)
        if n_matched == 0:
            return {
                "error": (
                    f"No source cells match the target on cell ID (source has {n_source}, "
                    f"target has {n_target}, 0 shared) — is this the right source file?"
                )
            }
        source_rows = indexer[matched_rows]

        # --- Per-column stats and fill plan (nothing written yet) ---
        per_column: dict[str, dict] = {}
        fills: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for col in columns:
            tgt = target["columns"][col]
            src = source["columns"][col]
            tgt_missing: np.ndarray = tgt["missing"]

            # Work in matched-row space: an integrated target dwarfs any one
            # source, so target-length scatter arrays would mostly hold air.
            tgt_missing_m = tgt_missing[matched_rows]
            src_missing_m = src["missing"][source_rows]
            src_values_m = src["values"][source_rows]

            fill_m = tgt_missing_m & ~src_missing_m
            fill_rows = matched_rows[fill_m]
            fill_values = src_values_m[fill_m]

            conflict_m = np.flatnonzero(~tgt_missing_m & ~src_missing_m)
            conflict_m = conflict_m[tgt["values"][matched_rows[conflict_m]] != src_values_m[conflict_m]]

            filled = len(fill_rows)
            if filled and tgt["kind"] == "categorical" and tgt["ordered"]:
                new_categories = sorted(set(fill_values) - set(tgt["cats"]))
                if new_categories:
                    return {
                        "error": (
                            f"Column '{col}' is an ordered categorical and the fill would introduce "
                            f"new categories {new_categories[:_N_EXAMPLES]} — appending to an ordered "
                            f"vocabulary silently corrupts its ordering. Make the column unordered or "
                            f"re-derive the ordering upstream first."
                        )
                    }
            missing_before = int(tgt_missing.sum())
            matched_missing = int(tgt_missing_m.sum())
            missing_after = missing_before - filled
            per_column[col] = {
                "filled": filled,
                "already_set": n_matched - matched_missing,
                "conflicts": len(conflict_m),
                "conflict_examples": [
                    [target_index[matched_rows[i]], tgt["values"][matched_rows[i]], src_values_m[i]]
                    for i in conflict_m[:_N_EXAMPLES]
                ],
                "source_missing": int((tgt_missing_m & src_missing_m).sum()),
                "unmatched": missing_before - matched_missing,
                "missing_before": missing_before,
                "missing_after": missing_after,
                "pct_full_after": round(100.0 * (n_target - missing_after) / n_target, 1),
            }
            if filled:
                fills[col] = (fill_rows, fill_values)

        total_filled = sum(stats["filled"] for stats in per_column.values())
        overlap = {
            "n_source_cells": n_source,
            "n_target_cells": n_target,
            "n_matched": n_matched,
        }
        if total_filled == 0:
            return {
                "error": (
                    "Nothing to backfill: no matched cell has a missing target value "
                    "the source can fill — no file was written"
                ),
                **overlap,
                "per_column": per_column,
            }

        # --- Copy (hashing the target in the same read), then patch ---
        if "error" in (parsed := parse_edit_log(target["raw_log"])):
            return parsed
        source_basename = Path(source_path).name

        with snapshot_copy_hashed(target_path) as (output_path, target_sha256), h5py.File(output_path, "a") as f_out:
            # A full read of a different file; ordered after the claim so an
            # unresolvable collision is refused without paying for it (#597).
            source_sha256 = _compute_sha256(source_path)
            entry = make_edit_entry(
                operation="backfill_obs_from_source",
                description=(
                    f"Backfilled {total_filled} missing obs values in "
                    f"{len(fills)} of {len(columns)} columns from {source_basename}"
                ),
                details={
                    "backfill_source_file": source_basename,
                    "backfill_source_sha256": source_sha256,
                    "columns": columns,
                    **overlap,
                    "total_filled": total_filled,
                    "per_column": per_column,
                },
            )
            obs_out = f_out["obs"]
            for col, (fill_rows, fill_values) in fills.items():
                tgt = target["columns"][col]
                if tgt["kind"] == "categorical":
                    _fill_categorical(obs_out, col, tgt, fill_rows, fill_values)  # pyright: ignore[reportArgumentType]
                else:
                    new_values = tgt["values"].copy()
                    new_values[fill_rows] = fill_values
                    replace_string_dataset(obs_out, col, new_values)  # pyright: ignore[reportArgumentType]
            log_result = build_edit_log(target["raw_log"], [entry], target_path, target_sha256)
            if "error" in log_result:
                raise RuntimeError(log_result["error"])
            write_edit_log_h5py(f_out, log_result["json"])

            verify_err = verify_categorical_integrity(f_out, list(fills))
            verify_err = verify_err or _verify_backfill(f_out, per_column, fills, placeholders)
            if verify_err:
                raise RuntimeError(verify_err)

        cleanup_previous_version(target_path, output_path)

        return {
            "output_path": output_path,
            "source": source_basename,
            **overlap,
            "total_filled": total_filled,
            "per_column": per_column,
        }

    except Exception as e:
        # No unlink here: snapshot_copy_hashed removes the snapshot itself.
        return {"error": str(e)}
