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

import contextlib
import shutil
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from ._io import (
    _decode_bytes,
    check_duplicate_ids,
    read_categorical_data,
    read_edit_log_h5py,
    replace_categorical_column,
    replace_string_dataset,
    verify_categorical_integrity,
    write_edit_log_h5py,
)
from .cap import LEGACY_LAYOUT_DESCRIPTION, is_legacy_cap_layout
from .edit import _DEFAULT_PLACEHOLDERS
from .write import (
    _compute_sha256,
    build_edit_log,
    cleanup_previous_version,
    generate_output_path,
    make_edit_entry,
    resolve_latest,
)

# Cap on the conflict examples quoted per column, so a large disagreement
# stays readable in the result and the edit log.
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
        if not isinstance(col, str) or "/" in col or not col.strip():
            problems.append(f"not a valid obs column name (must be a non-blank string without '/'): {col!r}")
    if len(set(columns)) != len(columns):
        problems.append("columns contains duplicates")
    return problems


def _is_missing_str(value: str, placeholders: set[str]) -> bool:
    """True if a string value means "no data": empty/whitespace or a placeholder."""
    s = value.strip()
    return not s or s.lower() in placeholders


def _read_column(obs: h5py.Group, col: str, placeholders: set[str], side: str) -> tuple[dict | None, str | None]:
    """Read one obs column into a uniform shape: (column dict, error).

    The dict holds ``kind`` ('categorical' or 'string'), per-row ``values``
    (object array of strings, None where NaN), and a ``missing`` mask (NaN,
    empty, or placeholder). Categorical columns also carry ``cats``/``codes``.
    Any other layout (numeric, boolean, nullable-dtype groups) has no missing
    vocabulary this tool understands, so it is refused rather than guessed at.
    """
    item = obs[col]
    if isinstance(item, h5py.Group) and "categories" in item:
        cats, codes = read_categorical_data(item)  # pyright: ignore[reportArgumentType]
        cat_values = np.array(list(cats), dtype=object)
        cat_missing = np.array([_is_missing_str(c, placeholders) for c in cats], dtype=bool)
        valid = codes >= 0
        values = np.full(len(codes), None, dtype=object)
        missing = ~valid
        if len(cats):
            values[valid] = cat_values[codes[valid]]
            hit = np.zeros(len(codes), dtype=bool)
            hit[valid] = cat_missing[codes[valid]]
            missing = missing | hit
        return {"kind": "categorical", "cats": list(cats), "codes": codes, "values": values, "missing": missing}, None
    if isinstance(item, h5py.Group):
        return None, (
            f"{side} column '{col}' uses a nullable-dtype layout, which is not supported — "
            "only categorical and string obs columns can be backfilled"
        )
    if h5py.check_string_dtype(item.dtype) is None:  # pyright: ignore[reportAttributeAccessIssue]
        return None, (
            f"{side} column '{col}' is not categorical or string — only those obs column types can be backfilled"
        )
    values = np.asarray(item.asstr()[:], dtype=object)  # pyright: ignore[reportAttributeAccessIssue]
    missing = np.fromiter((_is_missing_str(v, placeholders) for v in values), dtype=bool, count=len(values))
    return {"kind": "string", "values": values, "missing": missing}, None


def _read_obs_for_backfill(
    path: str, columns: list[str], placeholders: set[str], side: str
) -> tuple[dict | None, dict | None]:
    """Read the obs index and the requested columns from one file.

    Returns (data, error_result); exactly one is set. ``data`` holds ``ids``
    (list of cell IDs), ``columns`` (column name → the dict from
    :func:`_read_column`), and for the target side ``raw_log``.
    """
    with h5py.File(path, "r") as f:
        obs = f.get("obs")
        if not isinstance(obs, h5py.Group):
            return None, {"error": f"{side} file has no obs group: {path}"}
        if side == "Target":
            uns = f.get("uns")
            if isinstance(uns, h5py.Group) and is_legacy_cap_layout(uns):
                # Parity with drop.py / rename.py (#552): mutating tools
                # refuse the deprecated top-level CAP layout.
                return None, {
                    "error": (
                        f"Refusing to backfill: the target uses {LEGACY_LAYOUT_DESCRIPTION}, which is not supported"
                    )
                }
        index_name = _decode_bytes(obs.attrs.get("_index", "_index"))
        obs_keys = set(obs.keys())
        for col in columns:
            if col == index_name:
                return None, {
                    "error": f"'{index_name}' is the {side.lower()} obs index (the join key), not a backfillable column"
                }
            if col not in obs_keys:
                return None, {"error": f"{side} file has no obs column '{col}'"}
        ids = [_decode_bytes(v) for v in obs[index_name][:]]  # pyright: ignore[reportIndexIssue]
        dupe_err = check_duplicate_ids(ids, f"{side} cells")
        if dupe_err:
            return None, {"error": dupe_err}
        col_data = {}
        for col in columns:
            data, err = _read_column(obs, col, placeholders, side)
            if err:
                return None, {"error": err}
            col_data[col] = data
        result = {"ids": ids, "columns": col_data}
        if side == "Target":
            result["raw_log"] = read_edit_log_h5py(f)
        return result, None


def _codes_dtype(n_categories: int, original: np.dtype) -> np.dtype:
    """Smallest signed dtype holding the new category count, never narrower
    than the original codes dtype (extending categories can overflow int8)."""
    if np.iinfo(original).max >= max(n_categories - 1, 0):
        return original
    for dt in (np.int8, np.int16, np.int32):
        if np.iinfo(dt).max >= n_categories - 1 and np.dtype(dt).itemsize >= original.itemsize:
            return np.dtype(dt)
    return np.dtype(np.int64)


def _fill_categorical(obs: h5py.Group, col: str, data: dict, fill_rows: np.ndarray, fill_values: np.ndarray) -> None:
    """Rewrite a categorical column with the fills applied.

    Extends the categories with any new fill values, then drops categories
    the fills left unused (the placeholder being replaced, typically) —
    matching replace_placeholder_values' cleanup behavior.
    """
    cats: list[str] = data["cats"]
    codes: np.ndarray = data["codes"]
    new_cats = cats + sorted(set(fill_values) - set(cats))
    cat_pos = {c: i for i, c in enumerate(new_cats)}
    # Work in int64: the new category positions can overflow the original
    # codes dtype before the unused-category remap shrinks the range.
    work = codes.astype(np.int64)
    work[fill_rows] = [cat_pos[v] for v in fill_values]

    used = sorted(set(work[work >= 0]))
    final_cats = [new_cats[i] for i in used]
    lookup = np.full(len(new_cats), -1, dtype=np.int64)
    for new_idx, old_idx in enumerate(used):
        lookup[old_idx] = new_idx
    valid = work >= 0
    final_codes = np.full_like(work, -1)
    final_codes[valid] = lookup[work[valid]]

    replace_categorical_column(obs, col, final_cats, final_codes.astype(_codes_dtype(len(final_cats), codes.dtype)))


def _verify_backfill(f: h5py.File, per_column: dict, fills: dict, placeholders: set[str]) -> str | None:
    """Re-read every filled column from the output and check the result.

    Two independent checks per column: the filled rows hold exactly the
    values the source supplied, and the missing count landed on the predicted
    ``missing_after``. Returns an error message, or None if all pass.
    """
    obs = f["obs"]
    for col, (fill_rows, fill_values) in fills.items():
        data, err = _read_column(obs, col, placeholders, "Output")  # pyright: ignore[reportArgumentType]
        if err:
            return err
        if data is None:
            return f"Verification failed: could not re-read column '{col}'"
        written = data["values"][fill_rows]
        if not (written == fill_values).all():
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
    output_path = None
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

        placeholders = {v.lower() for v in _DEFAULT_PLACEHOLDERS}

        target, err = _read_obs_for_backfill(target_path, columns, placeholders, "Target")
        if err or target is None:
            return err or {"error": "Failed to read target"}
        source, err = _read_obs_for_backfill(source_path, columns, placeholders, "Source")
        if err or source is None:
            return err or {"error": "Failed to read source"}

        target_ids: list[str] = target["ids"]
        n_target = len(target_ids)
        n_source = len(source["ids"])

        # --- Join on cell ID ---
        indexer = pd.Index(source["ids"]).get_indexer(pd.Index(target_ids))
        matched = indexer >= 0
        n_matched = int(matched.sum())
        if n_matched == 0:
            return {
                "error": (
                    f"No source cells match the target on cell ID (source has {n_source}, "
                    f"target has {n_target}, 0 shared) — is this the right source file?"
                )
            }
        matched_rows = np.flatnonzero(matched)
        source_rows = indexer[matched_rows]

        # --- Per-column stats and fill plan (nothing written yet) ---
        per_column: dict[str, dict] = {}
        fills: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        expected_valid_counts: dict[str, int] = {}
        total_filled = 0
        for col in columns:
            tgt = target["columns"][col]
            src = source["columns"][col]

            src_missing_at = np.ones(n_target, dtype=bool)
            src_values_at = np.full(n_target, None, dtype=object)
            src_missing_at[matched_rows] = src["missing"][source_rows]
            src_values_at[matched_rows] = src["values"][source_rows]

            tgt_missing: np.ndarray = tgt["missing"]
            fill_mask = matched & tgt_missing & ~src_missing_at
            already_set_mask = matched & ~tgt_missing
            conflict_rows = np.flatnonzero(already_set_mask & ~src_missing_at)
            conflict_rows = conflict_rows[tgt["values"][conflict_rows] != src_values_at[conflict_rows]]

            fill_rows = np.flatnonzero(fill_mask)
            filled = len(fill_rows)
            missing_before = int(tgt_missing.sum())
            missing_after = missing_before - filled
            per_column[col] = {
                "filled": filled,
                "already_set": int(already_set_mask.sum()),
                "conflicts": len(conflict_rows),
                "conflict_examples": [
                    [target_ids[i], tgt["values"][i], src_values_at[i]] for i in conflict_rows[:_N_EXAMPLES]
                ],
                "source_missing": int((matched & tgt_missing & src_missing_at).sum()),
                "unmatched": int((~matched & tgt_missing).sum()),
                "missing_before": missing_before,
                "missing_after": missing_after,
                "pct_full_after": round(100.0 * (n_target - missing_after) / n_target, 1) if n_target else 0.0,
            }
            if filled:
                total_filled += filled
                fills[col] = (fill_rows, src_values_at[fill_rows])
                if tgt["kind"] == "categorical":
                    # Fills onto placeholder-coded rows don't change the
                    # valid-code count; fills onto NaN (code -1) rows do.
                    codes: np.ndarray = tgt["codes"]
                    expected_valid_counts[col] = int((codes >= 0).sum()) + int((codes[fill_rows] < 0).sum())

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

        # --- Edit log, then copy-and-patch ---
        source_basename = Path(source_path).name
        entry = make_edit_entry(
            operation="backfill_obs_from_source",
            description=(
                f"Backfilled {total_filled} missing obs values in "
                f"{len(fills)} of {len(columns)} columns from {source_basename}"
            ),
            details={
                "backfill_source_file": source_basename,
                "backfill_source_sha256": _compute_sha256(source_path),
                "columns": columns,
                **overlap,
                "total_filled": total_filled,
                "per_column": per_column,
            },
        )
        log_result = build_edit_log(target["raw_log"], [entry], target_path, _compute_sha256(target_path))
        if "error" in log_result:
            return log_result

        output_path = generate_output_path(target_path)
        if output_path == target_path:
            # generate_output_path timestamps to the second (see rename.py):
            # a second edit within the same second would name the output after
            # its own source. Refuse before touching anything.
            return {"error": "An edit snapshot for this second already exists — retry in a moment."}
        shutil.copy2(target_path, output_path)

        with h5py.File(output_path, "a") as f_out:
            obs_out = f_out["obs"]
            for col, (fill_rows, fill_values) in fills.items():
                tgt = target["columns"][col]
                if tgt["kind"] == "categorical":
                    _fill_categorical(obs_out, col, tgt, fill_rows, fill_values)  # pyright: ignore[reportArgumentType]
                else:
                    new_values = tgt["values"].copy()
                    new_values[fill_rows] = fill_values
                    replace_string_dataset(obs_out, col, new_values)  # pyright: ignore[reportArgumentType]
            write_edit_log_h5py(f_out, log_result["json"])

            verify_err = verify_categorical_integrity(f_out, list(fills), expected_valid_counts)
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
        if output_path and Path(output_path).is_file():
            with contextlib.suppress(OSError):
                Path(output_path).unlink()
        return {"error": str(e)}
