"""Strip HCA-forbidden obs columns from an HCA-layout h5ad file.

The CellxGENE → HCA conversion path (see :func:`convert_cellxgene_to_hca`)
strips these columns as a side-effect of conversion, because CellxGENE
schemas include ``self_reported_ethnicity`` while HCA forbids it for
privacy (see #370 / #410). Tracker-sourced HCA-layout files that arrive
with the same columns present have no other way to remove them — this
module is the recourse.

The shared helper :func:`_strip_forbidden_obs_columns_h5py` is used by
both this module and :func:`convert_cellxgene_to_hca`, so the column
list (``_OBS_COLUMNS_TO_STRIP``) lives here as the single source of
truth.
"""

from __future__ import annotations

from pathlib import Path

import h5py

from ._io import (
    gate_h5ad_paths,
    read_edit_log_h5py,
    read_group,
    update_column_order,
    write_edit_log_h5py,
)
from .cap import cellxgene_schema_version
from .write import (
    build_edit_log,
    cleanup_previous_version,
    make_edit_entry,
    resolve_latest,
    snapshot_copy,
)

# Obs columns that exist in CellxGENE files but are forbidden in HCA
# (privacy). Source of truth — :func:`convert_cellxgene_to_hca` imports
# this constant rather than redeclaring it. See #370 / #410.
_OBS_COLUMNS_TO_STRIP: tuple[str, ...] = (
    "self_reported_ethnicity_ontology_term_id",
    "self_reported_ethnicity",
)


def _strip_forbidden_obs_columns_h5py(f_out: h5py.File) -> list[str]:
    """Delete forbidden obs columns from an already-open output file.

    Updates the ``obs[column-order]`` attribute so the result still
    round-trips through anndata cleanly. Returns the list of columns
    actually stripped (may be empty), preserving the declared order in
    ``_OBS_COLUMNS_TO_STRIP`` so callers that log the result see stable
    output.

    Shared between :func:`strip_forbidden_obs_columns` (this module) and
    :func:`convert_cellxgene_to_hca` (in ``convert.py``).

    Args:
        f_out: Open h5py File in append mode.

    Returns:
        Ordered list of column names actually deleted.
    """
    stripped: list[str] = []
    for col in _OBS_COLUMNS_TO_STRIP:
        if col in f_out["obs"]:
            del f_out["obs"][col]
            stripped.append(col)
    if stripped:
        update_column_order(f_out, [], set(stripped))
    return stripped


@gate_h5ad_paths
def strip_forbidden_obs_columns(path: str) -> dict:
    """Strip HCA-forbidden obs columns from an HCA-layout h5ad file.

    Removes ``self_reported_ethnicity_ontology_term_id`` and
    ``self_reported_ethnicity`` from ``obs`` (whichever are present),
    updates ``obs[column-order]``, and writes a new timestamped edit
    snapshot with the operation logged in
    ``uns['provenance']['edit_history']``.

    Refuses to run on CellxGENE-layout inputs (presence of
    ``uns['schema_version']``): on those, use
    :func:`convert_cellxgene_to_hca` instead, which strips these columns
    as a side-effect of converting to HCA layout. The strip-only path
    here exists specifically for HCA-layout files (e.g. tracker-sourced
    integrated objects) that already passed through convert upstream or
    were never on the CellxGENE path.

    If neither forbidden column is present, returns
    ``{"skipped": True, "reason": ...}`` without writing a new file —
    the file is already in the desired state.

    Args:
        path: Path to an HCA-layout .h5ad file. Auto-resolves to the
            latest timestamped edit snapshot before operating.

    Returns:
        Dict with ``output_path`` and ``obs_columns_stripped`` on
        success; ``{"skipped": True, "reason": ...}`` if both columns
        were already absent; ``{"error": ...}`` on failure (including
        the CellxGENE-layout refusal).
    """
    try:
        path = resolve_latest(path)
        if not Path(path).is_file():
            return {"error": f"File not found: {path}"}

        # Peek first: layout check + presence check. Both via h5py so we
        # don't load the full anndata just to decide whether to mutate.
        # The layout gate matches rename.py / strip_cap.py: a file is
        # CellxGENE when uns['schema_version'] holds a non-empty string, so
        # an empty or non-string value no longer trips the refusal the way
        # the old bare presence check did.
        with h5py.File(path, "r") as f_in:
            if cellxgene_schema_version(f_in):
                return {
                    "error": (
                        "Input is CellxGENE-layout (uns['schema_version'] "
                        "declares a version). Use convert_cellxgene_to_hca "
                        "instead — it strips these columns as a side-effect "
                        "of converting to HCA layout."
                    )
                }
            obs = read_group(f_in, "obs")
            if obs is None:
                return {"error": "File has no obs group"}
            present = [c for c in _OBS_COLUMNS_TO_STRIP if c in obs]

        if not present:
            return {
                "skipped": True,
                "reason": (
                    f"None of the HCA-forbidden obs columns "
                    f"{list(_OBS_COLUMNS_TO_STRIP)} are present — nothing to strip."
                ),
            }

        with snapshot_copy(path) as output_path:
            # Defer the malformed-log cleanup until after the with-block closes
            # the output file — calling os.remove on an open HDF5 handle works
            # on POSIX (unlinked-but-open inode) but raises on Windows, and even
            # on POSIX the subsequent context __exit__ flush hits a removed
            # inode. Capture the error here, exit the context cleanly, then
            # remove + return.
            log_error = None
            with h5py.File(output_path, "a") as f_out:
                stripped = _strip_forbidden_obs_columns_h5py(f_out)
                # `present` was computed before the copy, so it should match
                # exactly. Use the post-strip return value as truth — that's
                # what we actually mutated.

                entry = make_edit_entry(
                    operation="strip_forbidden_obs_columns",
                    description=(f"Stripped HCA-forbidden obs columns (privacy): {stripped}"),
                    details={"obs_columns_stripped": stripped},
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
            "obs_columns_stripped": stripped,
        }

    except Exception as e:
        return {"error": str(e)}
