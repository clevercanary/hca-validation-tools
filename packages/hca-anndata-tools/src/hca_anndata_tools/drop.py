"""Drop caller-named obs columns from an h5ad file.

The general-purpose sibling of :mod:`hca_anndata_tools.strip`. That module
encodes *policy* — the two HCA-forbidden privacy column names are baked in and
it takes no arguments — and ``convert_cellxgene_to_hca`` imports its constant
for exactly that purpose. This module holds no policy at all: the caller
names the columns, and the tool guarantees only a *coherent* result — no
dangling references, no destroyed cell identities (see
:func:`drop_obs_columns`). Whether the result is *valid* is the validator's
verdict, not this tool's (#614).

That split exists because producers ship the same information under names no
fixed list can anticipate: the breast-v1 source datasets carry ethnicity as
``ethnicity_verbatim``, ``ethnicity_grouped``, ``reported_ethnicity``, ``race``
and ``self_reported_ethnicity_label`` across seven files, and carry derived
ontology labels as ``cell_type_label``, ``assay_label`` and friends that differ
per dataset.
"""

from __future__ import annotations

from pathlib import Path

import h5py

from ._io import (
    direct_members,
    gate_h5ad_paths,
    read_edit_log_h5py,
    read_uns,
    update_column_order,
    write_edit_log_h5py,
)
from .cap import CAP_METADATA_KEY
from .guards import (
    ObsColumnReferences,
    batch_condition_refusal,
    detect_obs_references,
    is_malformed_name,
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


def _validate_request(
    obs: h5py.Group, uns: h5py.Group | None, columns: list[str], refs: ObsColumnReferences
) -> list[str]:
    """Collect every reason the drop cannot proceed.

    Most reasons are per-column, but not all: an unsupported file layout is a
    verdict on the file and holds whatever the request names.

    Returns a list of human-readable problems, empty when the request is good.
    All checks run to completion rather than short-circuiting: a caller who
    mistyped two names should learn about both in one round trip.
    """
    problems: list[str] = []

    malformed = [c for c in columns if is_malformed_name(c)]
    problems += malformed_name_problems(columns)
    problems += obs_index_problems(obs, columns, verbing="deleting")
    problems += legacy_layout_problems(uns)

    # This tool's policy for the two mechanisms it refuses on (#614's
    # repair-or-refuse rule): a drop has no new name to re-point
    # batch_condition at, and CAP material is never patched in place. The
    # third, palettes, cascades — deleted with the column in drop_obs_columns.
    if refs.batch_condition:
        problems.append(batch_condition_refusal(refs.batch_condition, verbing="dropping"))
    if refs.cap_columns:
        problems.append(
            f"look like CAP annotation-set columns: {refs.cap_columns} — the set is declared "
            f"in uns[{CAP_METADATA_KEY!r}], which would still require them. Remove the "
            f"annotation set instead of its columns"
        )

    # Membership against the group's direct children, not `c in obs` — the
    # latter would resolve link paths and so accept names that point outside
    # obs entirely (see the malformed check above).
    #
    # Reported last: a refusal on a name the caller meant matters more than
    # the spelling of one they fumbled.
    #
    # Malformed names are excluded so each bad name is reported once. A name like
    # "/X" is necessarily absent from `obs.keys()` too, and listing it under both
    # problems implied its only fault was being missing — which would have sent a
    # caller looking for a typo rather than reading the path-name rule above.
    members = direct_members(obs)
    absent = [c for c in columns if c not in members and c not in malformed]
    if absent:
        problems.append(f"not present in obs: {absent}")

    return problems


@gate_h5ad_paths
def drop_obs_columns(path: str, columns: list[str] | tuple[str, ...]) -> dict:
    """Drop the named obs columns from an h5ad file.

    All-or-nothing: the whole request is validated before anything is written,
    and if any column fails any check the file is left untouched and every
    problem is reported together. There is no partial drop and no ``skipped``
    state — unlike :func:`~hca_anndata_tools.strip.strip_forbidden_obs_columns`,
    whose built-in column list makes "neither present" a normal outcome. Here
    the caller named the columns, so a name that isn't there is a mistake worth
    failing on.

    Drops any obs column the caller names, including schema-named ones — a
    dropped required column leaves a file the validator will reject, and that
    is the validator's verdict to deliver, not this tool's: the caller may be
    mid-sequence (dropping a column to regenerate it, say), and the original
    (non-timestamped) file always survives the snapshot chain, so nothing is
    unrecoverable (#614, #619). What *is* refused is anything that breaks coherence: the obs
    index (cell identities), names containing ``/`` (they resolve as HDF5 link
    paths), columns referenced by ``uns['batch_condition']``, CAP
    annotation-set columns, and the deprecated top-level CAP layout.

    Deletes ``uns['<column>_colors']`` alongside each dropped column. scanpy
    writes that key for any categorical it plots, and the palette belongs to the
    column rather than standing on its own — leaving it behind would orphan it,
    which the validator reports as "Colors field uns[...] does not have a
    corresponding categorical field in obs". Removing it is finishing the
    deletion the caller asked for. Anything that merely *references* a column
    is treated the other way and refuses the request outright; see
    :func:`_validate_request`.

    Note this does not shrink the file. HDF5 does not reclaim freed space
    in place, so the output is the same size as the input even with columns
    gone; ``compress_h5ad`` repacks and is meant to run last in a curation
    sequence anyway.

    Args:
        path: Path to an .h5ad file. Auto-resolves to the latest timestamped
            edit snapshot before operating. CellxGENE and HCA layouts are both
            fine — unlike ``strip_forbidden_obs_columns``, this makes no
            CellxGENE-layout refusal, because removing an arbitrary column is
            layout-agnostic. (The deprecated top-level CAP layout is the one
            file-shape refusal; see above.)
        columns: Obs column names to drop. Duplicates are ignored; order is
            preserved in the result. Annotated as list-or-tuple rather than
            ``Sequence[str]`` deliberately: ``str`` satisfies ``Sequence[str]``,
            so the looser annotation would stop a type checker from catching
            ``columns="one_name"`` — a slip the runtime has to guard anyway
            because MCP callers are not type-checked at all.

    Returns:
        Dict with ``output_path``, ``obs_columns_dropped`` and
        ``uns_keys_dropped`` on success, or ``{"error": ...}`` if the request
        was rejected or the write failed.
    """
    try:
        # Shape-check the argument before anything reads it. This is an
        # MCP-exposed tool, so `columns` arrives as decoded JSON and may hold
        # numbers or nulls, and every check below assumes strings. Without
        # this, a non-string entry raises inside `"/" in c` and surfaces as
        # "argument of type 'int' is not iterable" — safe, since nothing has
        # been written yet, but it breaks the promise that one error reports
        # every problem.
        if isinstance(columns, str):
            return {
                "error": (
                    "columns must be a list of column names, not a single string — "
                    "a bare string iterates as individual characters."
                )
            }
        try:
            # Dedupe, preserving caller order. A repeated name is harmless, so
            # it isn't worth reporting as a problem.
            requested = list(dict.fromkeys(columns))
        except TypeError:
            return {"error": "columns must be a list of column names."}
        if not requested:
            return {"error": "No columns given — name the obs columns to drop."}
        non_str = [c for c in requested if not isinstance(c, str)]
        if non_str:
            return {"error": f"columns must contain only strings; got: {non_str}"}

        path = resolve_latest(path)
        if not Path(path).is_file():
            return {"error": f"File not found: {path}"}

        with h5py.File(path, "r") as f_in:
            obs = require_obs_group(f_in)
            uns = read_uns(f_in)
            refs = detect_obs_references(uns, requested)
            problems = _validate_request(obs, uns, requested, refs)
            # Palettes to remove with their columns. Resolved here, from the
            # same read that validated, so the write phase does no discovery.
            owned_uns_keys = list(refs.palettes.values())

        if problems:
            return {"error": "Refusing to drop: " + "; ".join(problems)}

        with snapshot_copy(path) as output_path:
            # Defer the malformed-log cleanup until after the with-block closes the
            # output file, matching strip_forbidden_obs_columns: unlinking an open
            # HDF5 handle works on POSIX but raises on Windows, and the context
            # __exit__ flush would hit a removed inode either way.
            log_error = None
            with h5py.File(output_path, "a") as f_out:
                for col in requested:
                    del f_out["obs"][col]
                update_column_order(f_out, [], set(requested))
                for key in owned_uns_keys:
                    del f_out["uns"][key]

                described = f"Dropped obs columns: {requested}"
                if owned_uns_keys:
                    described += f" (and the palettes they own: {owned_uns_keys})"
                entry = make_edit_entry(
                    operation="drop_obs_columns",
                    description=described,
                    details={
                        "obs_columns_dropped": requested,
                        "uns_keys_dropped": owned_uns_keys,
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
            "obs_columns_dropped": requested,
            "uns_keys_dropped": owned_uns_keys,
        }

    except Exception as e:
        return {"error": str(e)}
