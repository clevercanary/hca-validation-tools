"""Drop caller-named obs columns from an h5ad file.

The general-purpose sibling of :mod:`hca_anndata_tools.strip`. That module
encodes *policy* — the two HCA-forbidden privacy column names are baked in and
it takes no arguments — and ``convert_cellxgene_to_hca`` imports its constant
for exactly that purpose. This module holds no policy at all: the caller names
the columns, and the only opinion it enforces is refusing to remove something
the HCA schema names (see :func:`drop_obs_columns`).

That split exists because producers ship the same information under names no
fixed list can anticipate: the breast-v1 source datasets carry ethnicity as
``ethnicity_verbatim``, ``ethnicity_grouped``, ``reported_ethnicity``, ``race``
and ``self_reported_ethnicity_label`` across seven files, and carry derived
ontology labels as ``cell_type_label``, ``assay_label`` and friends that differ
per dataset.
"""

from __future__ import annotations

import contextlib
import shutil
from pathlib import Path

import h5py

from ._io import (
    _decode_bytes,
    read_edit_log_h5py,
    update_column_order,
    write_edit_log_h5py,
)
from .schema.helpers import obs_column_tiers
from .write import (
    build_edit_log,
    cleanup_previous_version,
    generate_output_path,
    make_edit_entry,
    resolve_latest,
)


def _read_batch_condition(uns: h5py.Group | None) -> list[str]:
    """Read ``uns['batch_condition']`` as a list of obs column names.

    The HCA schema types it ``element_type: match_obs_columns``, so every entry
    must name an obs column. Returns an empty list when absent or unreadable —
    an unreadable value is the validator's problem to report, not a reason for
    this tool to refuse a drop.
    """
    if uns is None or "batch_condition" not in uns:
        return []
    try:
        raw = uns["batch_condition"][()]  # pyright: ignore[reportIndexIssue]
    except (OSError, TypeError, ValueError):
        return []
    if isinstance(raw, bytes | str):
        return [_decode_bytes(raw)]
    try:
        return [_decode_bytes(v) for v in raw]
    except TypeError:
        return []


def _validate_request(obs: h5py.Group, uns: h5py.Group | None, columns: list[str]) -> list[str]:
    """Collect every reason the requested columns cannot be dropped.

    Returns a list of human-readable problems, empty when the request is good.
    All checks run to completion rather than short-circuiting: a caller who
    mistyped two names should learn about both in one round trip.
    """
    problems: list[str] = []
    required_named, optional_named = obs_column_tiers()

    # h5py resolves a name containing '/' as an HDF5 link path, not as a dict
    # key: a leading slash resolves from the file root, and inner slashes
    # traverse subgroups. So `"/X" in obs` is True whenever the file has a root
    # X, and `del obs["/X"]` unlinks the expression matrix. Rejecting these
    # up front is what keeps every check below — which compares plain strings —
    # from disagreeing with what the delete would actually do.
    malformed = [c for c in columns if "/" in c or not c.strip()]
    if malformed:
        problems.append(f"not valid obs column names (a column name cannot contain '/' or be blank): {malformed}")

    # The index is a dataset in the obs group like any column, so a caller can
    # name it. Deleting it destroys the file's cell identities.
    index_name = _decode_bytes(obs.attrs.get("_index", "_index"))
    if index_name in columns:
        problems.append(f"'{index_name}' is the obs index, not a column — deleting it would destroy the file")

    required = sorted(c for c in columns if c in required_named)
    if required:
        problems.append(f"HCA schema-required obs columns cannot be dropped: {required}")

    optional = sorted(c for c in columns if c in optional_named)
    if optional:
        problems.append(
            f"schema-described obs columns cannot be dropped: {optional} — "
            f"these are optional per the HCA schema but hold producer data that "
            f"cannot be recovered once removed"
        )

    # Columns that something in uns *references*. A dropped column leaves the
    # reference dangling and turns a valid file invalid, so these are refused
    # rather than repaired — repairing either of them would mean rewriting a
    # claim the file makes, which is a curation decision and not this tool's
    # to take. Contrast `uns['<col>_colors']`, which the column *owns* and which
    # is therefore deleted alongside it (see :func:`drop_obs_columns`).
    batched = sorted(set(columns) & set(_read_batch_condition(uns)))
    if batched:
        problems.append(
            f"referenced by uns['batch_condition']: {batched} — that list declares "
            f"which columns define the experiment's batches, so dropping one changes "
            f"the declaration. Edit uns['batch_condition'] first if that is intended"
        )

    # CAP annotation sets declare themselves in uns['cap_metadata'] and require
    # obs columns named '<set>--<suffix>'. Those names are not schema-named, so
    # nothing above catches them, and dropping one leaves the declared set
    # broken. Keyed on the '--' convention rather than on parsing cap_metadata,
    # which may be stored as either a group or a JSON string: over-refusing a
    # '--' name in a CAP file is the safe direction, and no column this tool
    # targets uses that separator.
    if uns is not None and "cap_metadata" in uns:
        cap_cols = sorted(c for c in columns if "--" in c)
        if cap_cols:
            problems.append(
                f"look like CAP annotation-set columns: {cap_cols} — the set is declared "
                f"in uns['cap_metadata'], which would still require them. Remove the "
                f"annotation set instead of its columns"
            )

    # Membership against the group's direct children, not `c in obs` — the
    # latter would resolve link paths and so accept names that point outside
    # obs entirely (see the malformed check above).
    #
    # Reported last: a caller reading the error wants the schema verdict on the
    # names they meant more than the spelling of the ones they fumbled.
    members = set(obs.keys())
    absent = [c for c in columns if c not in members]
    if absent:
        problems.append(f"not present in obs: {absent}")

    return problems


def drop_obs_columns(path: str, columns: list[str] | tuple[str, ...]) -> dict:
    """Drop the named obs columns from an h5ad file.

    All-or-nothing: the whole request is validated before anything is written,
    and if any column fails any check the file is left untouched and every
    problem is reported together. There is no partial drop and no ``skipped``
    state — unlike :func:`~hca_anndata_tools.strip.strip_forbidden_obs_columns`,
    whose built-in column list makes "neither present" a normal outcome. Here
    the caller named the columns, so a name that isn't there is a mistake worth
    failing on.

    Refuses to drop any column the HCA schema names, whether required or
    optional, as well as the obs index. Dropping a required column would leave
    an invalid file, and dropping an optional one would discard producer data
    that cannot be reconstructed; this tool deliberately offers no way to do
    either. Columns the schema does not name — producer extras, privacy columns
    under non-canonical names, derived labels under non-canonical names — are
    the intended targets and drop freely.

    Derived label columns under their *canonical* names (``cell_type``,
    ``tissue``, ``assay``, ``sex``, ``disease``, ``organism``,
    ``development_stage``) are not guarded: they are outputs that
    ``populate_labels`` regenerates from the matching ``*_ontology_term_id``
    columns, so removing one loses nothing permanently.

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
            edit snapshot before operating. Either layout is fine — unlike
            ``strip_forbidden_obs_columns``, this makes no CellxGENE-layout
            refusal, because removing an arbitrary column is layout-agnostic.
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
    output_path = None
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
            obs = f_in.get("obs")
            if obs is None:
                return {"error": "File has no obs group"}
            if not isinstance(obs, h5py.Group):
                return {"error": "obs is not a group — the file predates the modern h5ad layout"}
            uns = f_in.get("uns")
            if not isinstance(uns, h5py.Group):
                uns = None
            problems = _validate_request(obs, uns, requested)
            # Palettes to remove with their columns. Resolved here, from the
            # same read that validated, so the write phase does no discovery.
            owned_uns_keys = [k for c in requested if (k := f"{c}_colors") in (uns or {})]

        if problems:
            return {"error": "Refusing to drop: " + "; ".join(problems)}

        output_path = generate_output_path(path)
        shutil.copy2(path, output_path)

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
        if output_path and Path(output_path).is_file():
            with contextlib.suppress(OSError):
                Path(output_path).unlink()
        return {"error": str(e)}
