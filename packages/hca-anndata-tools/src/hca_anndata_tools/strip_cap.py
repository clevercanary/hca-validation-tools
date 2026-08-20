"""Remove CAP annotation material from an HCA-layout h5ad file.

The remediation counterpart to the toolkit's legacy-layout refusals (#452,
#602): files annotated by the pre-#452 ``copy_cap_annotations`` carry CAP
material as top-level ``uns['cellannotation_metadata']`` /
``uns['cellannotation_schema_version']``, a layout every mutating tool now
refuses rather than normalizes. Those files can be neither re-annotated from
a fresh CAP export nor otherwise curated until that material is removed —
this module is the recourse.

The strip is general across both layout eras: it also removes a nested
``uns['cap_metadata']`` block, so it doubles as the "remove CAP from a file"
tool for imports that will not be replaced (a re-import over a nested-layout
file can alternatively use ``copy_cap_annotations(overwrite=True)``, which
replaces rather than removes).
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
from .cap import _LEGACY_CAP_MARKERS, CAP_METADATA_KEY
from .write import (
    build_edit_log,
    cleanup_previous_version,
    generate_output_path,
    make_edit_entry,
    resolve_latest,
)

# Every CAP-written uns key across both layout eras: the deprecated top-level
# markers and the nested block that replaced them (#452). Built from cap.py's
# constants rather than retyped, so the keys this tool removes stay the keys
# the refusal predicates detect.
_CAP_UNS_KEYS: tuple[str, ...] = (*_LEGACY_CAP_MARKERS, CAP_METADATA_KEY)


def strip_cap_annotations(path: str) -> dict:
    """Remove all CAP annotation material from an HCA-layout h5ad file.

    Deletes whichever CAP-written uns keys are present — the legacy top-level
    ``cellannotation_metadata`` / ``cellannotation_schema_version`` pair, the
    nested ``cap_metadata`` block, or (on a mixed-layout file) both — and
    every obs column whose name contains ``--``, the separator CAP annotation
    columns carry (the same detection ``copy_cap_annotations`` uses for its
    overwrite mode). Everything else is untouched: all other obs columns and
    uns fields ride along unchanged, and the existing edit-log history stays
    — the original ``import_cap_annotations`` entry is history, not debris.

    The gates, in the order a caller hits them:

    * **HCA-layout files only.** A file declaring a CellxGENE
      ``uns['schema_version']`` (e.g. a CAP export) is refused: CAP — not the
      exported file — is the system of record for its annotations, so
      stripping an export mutilates a file CAP would overwrite on its next
      export. Strip CAP material only from HCA curation targets.
    * **Nothing CAP-shaped is an error, not a no-op.** This tool is targeted
      remediation — absence of CAP material signals the wrong file was
      supplied, so it errors without writing rather than producing a
      pointless multi-GB snapshot. (Contrast ``strip_forbidden_obs_columns``,
      an idempotent hygiene pass, which reports ``skipped``.)

    Writes a new timestamped snapshot with an edit-log entry listing exactly
    which uns keys and obs columns were removed, and deletes the previous
    snapshot (never the original), like every other mutating tool.

    The intended sequel is a fresh ``copy_cap_annotations`` run with a
    current nested-layout CAP export as the source; the stripped file is also
    accepted again by the rest of the mutating toolkit, whose legacy-layout
    refusals this tool clears.

    Args:
        path: Path to an HCA-layout .h5ad file. Auto-resolves to the latest
            timestamped edit snapshot before operating.

    Returns:
        Dict with ``output_path``, ``uns_keys_removed``, and
        ``obs_columns_removed`` on success, or ``{"error": ...}``.
    """
    output_path = None
    try:
        path = resolve_latest(path)
        if not Path(path).is_file():
            return {"error": f"File not found: {path}"}

        # Peek first via h5py: layout check + inventory of what is present,
        # without loading the full anndata just to decide whether to mutate.
        with h5py.File(path, "r") as f_in:
            uns = f_in.get("uns")
            if uns is not None and "schema_version" in uns:
                return {
                    "error": (
                        "Refusing to strip: the file declares a CellxGENE "
                        "uns['schema_version'] (e.g. a CAP export). CAP is the system "
                        "of record for its exports — strip CAP material only from "
                        "HCA-layout curation targets."
                    )
                }
            obs = f_in.get("obs")
            if not isinstance(obs, h5py.Group):
                return {"error": "File has no obs group"}
            uns_keys_present = [k for k in _CAP_UNS_KEYS if uns is not None and k in uns]
            all_columns = [_decode_bytes(c) for c in obs.attrs["column-order"]]
            obs_columns_present = [c for c in all_columns if "--" in c]

        if not uns_keys_present and not obs_columns_present:
            return {
                "error": (
                    "Nothing to strip: the file has no CAP material (no legacy "
                    "top-level keys, no uns['cap_metadata'], no '--' obs columns) "
                    "— no file was written. Is this the right file?"
                )
            }

        output_path = generate_output_path(path)
        if output_path == path:
            # generate_output_path timestamps to the second (see rename.py):
            # a second edit within the same second would name the output after
            # its own source. Refuse before touching anything.
            return {"error": "An edit snapshot for this second already exists — retry in a moment."}
        shutil.copy2(path, output_path)

        # Defer the malformed-log cleanup until after the with-block closes
        # the output handle (see strip.py for the POSIX/Windows rationale).
        log_error = None
        with h5py.File(output_path, "a") as f_out:
            for key in uns_keys_present:
                del f_out["uns"][key]
            for col in obs_columns_present:
                del f_out["obs"][col]
            if obs_columns_present:
                update_column_order(f_out, [], set(obs_columns_present))

            entry = make_edit_entry(
                operation="strip_cap_annotations",
                description=(
                    f"Removed CAP annotation material: {len(uns_keys_present)} uns "
                    f"key(s), {len(obs_columns_present)} obs column(s)"
                ),
                details={
                    "uns_keys_removed": uns_keys_present,
                    "obs_columns_removed": obs_columns_present,
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
            "uns_keys_removed": uns_keys_present,
            "obs_columns_removed": obs_columns_present,
        }

    except Exception as e:
        if output_path and Path(output_path).is_file():
            with contextlib.suppress(OSError):
                Path(output_path).unlink()
        return {"error": str(e)}
