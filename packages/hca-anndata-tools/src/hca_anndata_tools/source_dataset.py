"""Record, per cell, the tracker source dataset an integrated object's cells come from (#776).

Integrated objects carry this under eight names or none (#719); this writes it
as ``obs['source_dataset']``, derived from the cell-ID match
:func:`~hca_anndata_tools.sources.match_sources` shares with
``find_source_datasets``. Checking the names against the tracker is the
curate-h5ad skill's job: this package cannot reach the tracker.
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from anndata.io import read_elem, write_elem

from ._errors import failure_result
from ._io import gate_h5ad_paths, read_edit_log_h5py, read_uns, update_column_order, write_edit_log_h5py
from .cap import cellxgene_schema_version
from .guards import legacy_layout_problems
from .sources import SOURCE_DATASET_COLUMN as COLUMN
from .sources import match_sources, tracker_name
from .write import build_edit_log, cleanup_previous_version, make_edit_entry, resolve_latest, snapshot_copy_hashed


def _describe(findings: list[dict]) -> str:
    """The unmatched and double-claimed cells, counted and sampled, as a refusal reads them."""
    said = {"unaccounted_cells": "no source dataset", "cells_claimed_twice": "more than one"}
    return "; ".join(
        f"{f['count']:,} {'cell matches' if f['count'] == 1 else 'cells match'} {said[f['code']]} "
        f"(e.g. {', '.join(f['sample_ids'][:5])})"
        for f in findings
    )


@gate_h5ad_paths
def set_source_dataset(path: str) -> dict:
    """Write ``obs['source_dataset']``: each cell's tracker source dataset, matched by cell ID.

    Refuses an export, which we never write to: a file whose name is not a
    tracker download name (a CAP export is named by its title), or one
    declaring a CellxGENE schema version or the legacy CAP layout. Recomputes
    :func:`~hca_anndata_tools.sources.find_source_datasets`'s match and refuses
    what it refuses; on top of that it writes only a partition, naming the
    cells that match no source or more than one. The value is each
    source's tracker name (``hgca-v1-burclaff-2022`` for
    ``hgca-v1-burclaff-2022-r1-wip-8.h5ad``), as a categorical of the names in
    use, sorted. The column is this tool's own, so an existing one is replaced
    whatever it holds, keeping its position, along with any
    ``uns['source_dataset_colors']``.

    All-or-nothing: every refusal comes before the snapshot, and the column is
    read back before the edit is kept. Writes a timestamped snapshot with an
    edit-log entry and retires the previous one, like every mutating tool.

    Args:
        path: Path to an integrated-object .h5ad under the tracker layout.
            Auto-resolves to the latest timestamped edit snapshot.

    Returns:
        Dict with ``output_path``, ``column``, ``n_obs``, ``replaced`` and
        ``sources`` (``tracker_name``, ``filename``, ``cells`` per candidate,
        most cells first; zero for a source no cell matches), or
        ``{"error": ...}``.
    """
    try:
        path = resolve_latest(path)
        if not Path(path).is_file():
            return {"error": f"File not found: {path}"}

        # CAP is the system of record for its exports, and we never write to one
        # (contract, Scope). A CAP export of an atlas is named by its title, not
        # as a tracker download, and may carry neither marker below — the gut
        # exports carry neither — so the name is the check that catches it.
        name = Path(path).name
        if tracker_name(name) is None:
            return {
                "error": f"Refusing to set {COLUMN}: {name} is not a tracker download name "
                f"(<name>-r<revision>[-wip-<n>].h5ad), so it is not one of the tracker's integrated objects — "
                f"a CAP export, say, which we never write to"
            }
        with h5py.File(path, "r") as f_in:
            if version := cellxgene_schema_version(f_in):
                return {
                    "error": f"Refusing to set {COLUMN}: the file declares CellxGENE schema {version}, so it is an "
                    f"export (a CAP export, say), which we never write to"
                }
            if legacy := legacy_layout_problems(read_uns(f_in)):
                return {"error": f"Refusing to set {COLUMN}: {legacy[0]}"}

        match = match_sources(path)
        if findings := match.findings():
            return {
                "error": f"Refusing to set {COLUMN}: not every cell matches exactly one source dataset: "
                + _describe(findings)
            }

        # On a partition each source's matched count is exactly its cell count.
        sources = [
            {"tracker_name": r["tracker_name"], "filename": r["filename"], "cells": r["matched_by_id"]}
            for r in sorted(match.sources, key=lambda r: (-r["matched_by_id"], r["filename"]))
        ]
        categories = sorted(r["tracker_name"] for r in match.sources if r["matched_by_id"])
        code_of = np.array([categories.index(r["tracker_name"]) if r["matched_by_id"] else -1 for r in match.sources])
        column = pd.Categorical.from_codes(code_of[match.owner], categories=categories)

        with snapshot_copy_hashed(path) as (output_path, source_sha256), h5py.File(output_path, "a") as f_out:
            obs_out = f_out["obs"]
            replaced = COLUMN in obs_out
            if replaced:
                del obs_out[COLUMN]
            uns_out = read_uns(f_out)
            palette = f"{COLUMN}_colors"
            if uns_out is not None and palette in uns_out:
                del uns_out[palette]
            # write_elem, not a hand-rolled codes/categories pair: anndata owns
            # the categorical encoding and its attrs.
            write_elem(obs_out, COLUMN, column)
            update_column_order(f_out, [COLUMN])  # appends; a replaced column keeps its place

            written = read_elem(obs_out[COLUMN])
            if list(written.categories) != categories or not np.array_equal(written.codes, column.codes):
                raise RuntimeError(f"obs['{COLUMN}'] read back differently from what was written")

            entry = make_edit_entry(
                operation="set_source_dataset",
                description=(
                    f"Set obs['{COLUMN}'] from {len(categories)} tracker source datasets, matched by cell ID"
                    + (" (replacing the existing column)" if replaced else "")
                ),
                details={
                    "column": COLUMN,
                    "n_obs": len(column),
                    "replaced": replaced,
                    "sources": {r["tracker_name"]: r["cells"] for r in sources if r["cells"]},
                },
            )
            log_result = build_edit_log(read_edit_log_h5py(f_out), [entry], path, source_sha256)
            if "error" in log_result:
                raise RuntimeError(log_result["error"])
            write_edit_log_h5py(f_out, log_result["json"])

        cleanup_previous_version(path, output_path)
        return {
            "output_path": output_path,
            "column": COLUMN,
            "n_obs": len(column),
            "replaced": replaced,
            "sources": sources,
        }
    except Exception as e:
        return failure_result(e)
