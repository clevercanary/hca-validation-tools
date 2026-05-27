"""MCP wrapper for hca_schema_validator.populate_in_memory.

Per-column fill/verify for HCA-tracker-imported h5ad files — the
tracker-source counterpart to ``label_h5ad`` (which hardline-refuses on
any pre-populated controlled column, the right behavior for
CellxGENE-converted files).

The substantive analysis lives in
:func:`hca_schema_validator.populator.populate_in_memory`. This wrapper
is the thin file-I/O shim around it:

1. Resolve the latest timestamped snapshot.
2. Open the file.
3. Refuse if the edit log contains an ``import_cellxgene`` entry —
   origin-level signal owned by ``hca-anndata-tools``, not the schema
   validator (matches the layering: file-history concerns live in
   tools, data-structure concerns live in the validator).
4. Delegate to ``populate_in_memory(adata)``. Pass through any error
   or skipped result unchanged.
5. On success-with-write: ``write_h5ad`` with a ``populate_labels``
   edit-log entry, return the new ``output_path``.
"""

import os

from hca_anndata_tools import has_edit_log_operation
from hca_anndata_tools._io import open_h5ad
from hca_anndata_tools.write import make_edit_entry, resolve_latest, write_h5ad
from hca_schema_validator import populate_in_memory


def populate_labels(path: str) -> dict:
    """Per-column fill/verify for HCA-tracker-imported h5ad files.

    See :func:`hca_schema_validator.populator.populate_in_memory` for the
    per-column logic and refusal rules. This wrapper adds:

    * Origin refusal: ``import_cellxgene`` in the file's edit log means
      ``cellxgene-schema add-labels`` already populated every controlled
      column upstream during conversion — running this would be a
      redundant pass.
    * The file-I/O snapshot + edit-log conventions every other
      mechanical fix tool uses.

    Args:
        path: Path to an HCA-layout .h5ad file. Auto-resolves to the
            latest timestamped edit snapshot.

    Returns:
        On success-with-write: ``{output_path, filled, matched}``.
        On no-op: ``{skipped: True, reason: ..., matched: [...]}``.
        On refusal / mismatch: ``{error: ..., details: ...}``.
    """
    try:
        path = resolve_latest(path)
        if not os.path.isfile(path):
            return {"error": f"File not found: {path}"}

        # backed="r": populator only mutates obs/var/raw.var (all
        # in-memory DataFrames even in backed mode); X stays on disk
        # and is streamed by anndata's write path. Avoids multi-GB
        # memory spikes on large tracker-source files. Same pattern as
        # label_h5ad.
        with open_h5ad(path, backed="r") as adata:
            # Origin-level refusal: this file came through
            # convert_cellxgene_to_hca, so cellxgene-schema add-labels
            # already populated every controlled column upstream.
            if has_edit_log_operation(adata, "import_cellxgene"):
                return {
                    "error": (
                        "Edit log contains an 'import_cellxgene' entry — file "
                        "was imported via convert_cellxgene_to_hca, which means "
                        "cellxgene-schema add-labels already populated every "
                        "controlled column upstream. Running populate_labels "
                        "would be a redundant pass. If you need to repopulate, "
                        "drop the columns and use label_h5ad instead."
                    )
                }

            result = populate_in_memory(adata)

            # Pass through refusal / skipped sentinels unchanged.
            if "error" in result or result.get("skipped"):
                return result

            # Success path: write a new snapshot with our edit-log entry.
            filled = result["filled"]
            matched = result["matched"]
            entry = make_edit_entry(
                operation="populate_labels",
                description=(
                    f"Populated {len(filled)} controlled column(s) from "
                    f"canonical sources; {len(matched)} already matched "
                    f"(skipped). observation_joinid not written."
                ),
                details={"filled": filled, "matched": matched},
            )

            write_result = write_h5ad(adata, path, [entry])

        if "error" in write_result:
            return write_result

        return {
            "output_path": write_result["output_path"],
            "filled": filled,
            "matched": matched,
        }

    except Exception as e:
        return {"error": str(e)}
