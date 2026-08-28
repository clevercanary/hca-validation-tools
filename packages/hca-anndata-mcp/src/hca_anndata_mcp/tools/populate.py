"""MCP wrapper for hca_schema_validator.populate_in_memory.

Per-column fill/verify, and the labeler for HCA-layout h5ad files
generally — not only tracker-imported ones. ``label_h5ad`` fills the same
labels but also writes ``obs['observation_joinid']``, which this module
refuses on from then on — so labeling with it is a one-way door. The
column marks that a joinid-writing labeling pass has run, whether that
was ``cellxgene-schema add-labels`` upstream or ``label_h5ad`` here; it
does not by itself establish CellxGENE origin.

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

from pathlib import Path

from hca_anndata_tools import has_edit_log_operation
from hca_anndata_tools._io import open_h5ad
from hca_anndata_tools.write import forward_encodings_normalized, make_edit_entry, resolve_latest, write_h5ad
from hca_schema_validator import populate_in_memory


def populate_labels(path: str) -> dict:
    """Fill the HCA label columns on an HCA-layout h5ad, verifying as it goes.

    The labeler for HCA curation, whatever state the controlled columns are
    in: it fills missing and all-NaN columns from canonical, and on a partly
    filled one it verifies every populated row first, filling only the NaN
    rows.

    Canonical means two different sources. The 7 obs label columns are
    checked against the ontology label for their ``*_ontology_term_id``; the
    5 ``var['feature_*']`` columns, and their ``raw.var`` mirrors, against
    GENCODE via the Ensembl ID in the index. A populated value disagreeing
    with either one is a refusal, as is a *missing* column whose source
    resolves no canonical value for any row (an empty ``*_ontology_term_id``,
    term IDs the ontology doesn't recognize, or a ``var.index`` that isn't
    Ensembl IDs) — filling there would write an all-NaN column and report it
    as filled. Refusal is
    total: every column is classified before anything is written, so one bad
    column withholds the fills that would have succeeded. Each disagreement
    is reported with row counts.

    Unlike ``label_h5ad`` it never writes ``obs['observation_joinid']``, and
    that matters in one direction: a file carrying that column is refused
    here from then on.

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
        if not Path(path).is_file():
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

        out = {
            "output_path": write_result["output_path"],
            "filled": filled,
            "matched": matched,
        }
        return forward_encodings_normalized(write_result, out)

    except Exception as e:
        return {"error": str(e)}
