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
import json
from pathlib import Path

import h5py

from ._io import (
    read_column_order,
    read_edit_log_h5py,
    update_column_order,
    write_edit_log_h5py,
)
from .cap import _LEGACY_CAP_MARKERS, CAP_METADATA_KEY, cap_annotation_columns
from .inspect import _read_schema_version
from .write import (
    _copy_with_sha256,
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

# CAP provenance from still-older copy_cap eras: unambiguously CAP-named
# top-level keys (pre-#292 imports), and the whole uns['provenance']['cap']
# block (later legacy imports — the gut-v1 objects carry this). Ambiguous
# legacy keys (description, publication_timestamp, ...) are deliberately NOT
# removed from the top level: they collide with HCA's own uns vocabulary.
_LEGACY_TOP_LEVEL_PROVENANCE: tuple[str, ...] = (
    "cap_dataset_url",
    "cap_publication_title",
    "cap_publication_description",
    "cap_publication_url",
)


def strip_cap_annotations(path: str) -> dict:
    """Remove all CAP annotation material from an HCA-layout h5ad file.

    Deletes whichever CAP-written uns keys are present — the legacy top-level
    ``cellannotation_metadata`` / ``cellannotation_schema_version`` pair, the
    nested ``cap_metadata`` block, the still-older CAP provenance
    (``uns['provenance']['cap']`` and unambiguous top-level ``cap_*`` keys),
    or any mix of those eras — and
    every obs column whose name both contains ``--`` (CAP's separator) and
    ends with a known CAP suffix, along with any ``uns['<column>_colors']``
    palette a removed column owns (an orphaned palette breaks the schema
    validator). A column that merely contains ``--`` without a CAP suffix
    (a producer column like ``CD4--CD8_ratio``) is never deleted — it is
    reported in ``unrecognized_cap_like_columns`` for the curator to judge.
    Everything else is untouched: all other obs columns and uns fields ride
    along unchanged, and the existing edit-log history stays — the original
    ``import_cap_annotations`` entry is history, not debris.

    The gates, in the order a caller hits them:

    * **HCA-layout files only.** A file declaring a CellxGENE
      ``uns['schema_version']`` (e.g. a CAP export) is refused: CAP — not the
      exported file — is the system of record for its annotations, so
      stripping an export mutilates a file CAP would overwrite on its next
      export. Strip CAP material only from HCA curation targets.
    * **Our imports only.** CAP uns metadata is stripped only when the edit
      log carries an ``import_cap_annotations`` entry — this tool undoes what
      our own import wrote. Legacy CAP exports carry the same uns keys but no
      edit history (and no ``schema_version`` for the gate above to catch),
      so this is what keeps a raw export from being mutilated by accident.
    * **Nothing CAP-shaped is an error, not a no-op.** This tool is targeted
      remediation — absence of CAP material signals the wrong file was
      supplied, so it errors without writing rather than producing a
      pointless multi-GB snapshot. (Contrast ``strip_forbidden_obs_columns``,
      an idempotent hygiene pass, which reports ``skipped``.)

    Writes a new timestamped snapshot with an edit-log entry listing exactly
    which uns keys and obs columns were removed, and deletes the previous
    snapshot (never the original), like every other mutating tool. The
    snapshot is not smaller than the input — HDF5 does not reclaim freed
    space in place — so run ``compress_h5ad`` afterwards if size matters.

    The intended sequel is a fresh ``copy_cap_annotations`` run with a
    current nested-layout CAP export as the source; the stripped file is also
    accepted again by the rest of the mutating toolkit, whose legacy-layout
    refusals this tool clears.

    Args:
        path: Path to an HCA-layout .h5ad file. Auto-resolves to the latest
            timestamped edit snapshot before operating.

    Returns:
        Dict with ``output_path``, ``uns_keys_removed``,
        ``obs_columns_removed``, and ``unrecognized_cap_like_columns``
        (``--`` columns left alone for lacking a CAP suffix) on success,
        or ``{"error": ...}``.
    """
    output_path = None
    try:
        path = resolve_latest(path)
        if not Path(path).is_file():
            return {"error": f"File not found: {path}"}

        # Peek first via h5py: layout check + inventory of what is present,
        # without loading the full anndata just to decide whether to mutate.
        with h5py.File(path, "r") as f_in:
            version = _read_schema_version(f_in)
            if version:
                return {
                    "error": (
                        f"Refusing to strip: the file declares CellxGENE schema {version} "
                        f"(e.g. a CAP export). CAP is the system of record for its exports "
                        f"— strip CAP material only from HCA-layout curation targets."
                    )
                }
            obs = f_in.get("obs")
            if obs is None:
                return {"error": "File has no obs group"}
            if not isinstance(obs, h5py.Group):
                return {"error": "obs is not a group — the file predates the modern h5ad layout"}
            obs_columns_present, unrecognized_columns = cap_annotation_columns(read_column_order(obs))
            uns = f_in.get("uns")
            uns_keys_present: list[str] = []
            if uns is not None:
                uns_keys_present += [k for k in _CAP_UNS_KEYS if k in uns]
                uns_keys_present += [k for k in _LEGACY_TOP_LEVEL_PROVENANCE if k in uns]
                # 'provenance/cap' is an HDF5 path, so the shared deletion
                # loop below removes the nested block like any other key.
                prov = uns.get("provenance")
                if isinstance(prov, h5py.Group) and "cap" in prov:
                    uns_keys_present.append("provenance/cap")
            if uns_keys_present:
                # This tool only undoes what our own import wrote. A file
                # carrying CAP uns metadata without an import_cap_annotations
                # edit-log entry did not get it from us — it is a CAP export
                # (or externally annotated), and CAP is the system of record
                # for its exports. Legacy exports have no schema_version, so
                # the CellxGENE gate above cannot catch them; this one does.
                entries = json.loads(read_edit_log_h5py(f_in))
                if not any(isinstance(e, dict) and e.get("operation") == "import_cap_annotations" for e in entries):
                    return {
                        "error": (
                            "Refusing to strip: the file carries CAP uns metadata but its edit log "
                            "has no 'import_cap_annotations' entry, so this toolkit did not put it "
                            "there. The file looks like a CAP export or an externally annotated file "
                            "— strip only removes what our own import wrote."
                        )
                    }
            if uns is not None:
                # A removed categorical column's scanpy palette would be
                # orphaned (the validator flags colors without a matching
                # obs column).
                uns_keys_present += [c + "_colors" for c in obs_columns_present if c + "_colors" in uns]

        if not uns_keys_present and not obs_columns_present:
            # nothing_to_strip lets a caller composing this tool (copy_cap's
            # overwrite pre-strip) tell "clean target" apart from a failure
            # without matching on the message text.
            return {
                "error": (
                    "Nothing to strip: the file has no CAP material (no legacy "
                    "top-level keys, no uns['cap_metadata'], no '--' obs columns) "
                    "— no file was written. Is this the right file?"
                ),
                "nothing_to_strip": True,
            }

        output_path = generate_output_path(path)
        if output_path == path:
            # generate_output_path timestamps to the second (see rename.py):
            # a second edit within the same second would name the output after
            # its own source. Refuse before touching anything.
            return {"error": "An edit snapshot for this second already exists — retry in a moment."}
        # Hash the source in the same streaming read as the snapshot copy;
        # a separate hash pass would re-read the whole multi-GB file.
        source_sha256 = _copy_with_sha256(path, output_path)

        # Defer the malformed-log cleanup until after the with-block closes
        # the output handle (see strip.py for the POSIX/Windows rationale).
        log_error = None
        with h5py.File(output_path, "a") as f_out:
            for key in uns_keys_present:
                del f_out["uns"][key]
            if obs_columns_present:
                for col in obs_columns_present:
                    del f_out["obs"][col]
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
            log_result = build_edit_log(existing_log, [entry], path, source_sha256)
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
            "unrecognized_cap_like_columns": unrecognized_columns,
        }

    except Exception as e:
        if output_path and Path(output_path).is_file():
            with contextlib.suppress(OSError):
                Path(output_path).unlink()
        return {"error": str(e)}
