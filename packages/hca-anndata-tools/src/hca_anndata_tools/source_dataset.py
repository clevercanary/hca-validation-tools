"""Record, per cell, the tracker source dataset an integrated object's cells come from (#776).

Integrated objects carry this fact under eight different names, or not at
all (#719). This writes it under one, ``obs['source_dataset']``, holding each
source's tracker name, and derives it rather than taking it from the caller:
the source is the one whose obs index holds the cell's ID
(:func:`~hca_anndata_tools.sources.match_sources`, the same match
``find_source_datasets`` reports), and its tracker name is read off its
download name.

Nothing here checks the names against the tracker; this package cannot reach
it. The curate-h5ad skill previews with ``find_source_datasets`` and checks
each name and cell count against the tracker's list for the atlas version
before running this.
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from anndata.io import read_elem, write_elem

from ._errors import failure_result
from ._io import gate_h5ad_paths, read_edit_log_h5py, read_uns, update_column_order, write_edit_log_h5py
from .sources import SOURCE_DATASET_COLUMN, match_sources
from .write import build_edit_log, cleanup_previous_version, make_edit_entry, resolve_latest, snapshot_copy_hashed

COLUMN = SOURCE_DATASET_COLUMN


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

    The candidates and the match are :func:`~hca_anndata_tools.sources.find_source_datasets`'s,
    recomputed here rather than taken from a preview, and they refuse what it
    refuses — a target outside the tracker layout, a source file that is not a
    tracker download name, two copies of one source. On top of that this
    writes only a partition: it refuses unless every cell matches exactly one
    source, naming the cells that match none or more than one. A source no cell
    matches is reported with zero cells and gets no category.

    The value is the source's tracker name (``hgca-v1-burclaff-2022`` for
    ``hgca-v1-burclaff-2022-r1-wip-8.h5ad``), as a categorical whose
    categories are the names in use, sorted. The column is this tool's to
    write, so an existing ``source_dataset`` is replaced whatever it holds,
    keeping its position, and running again simply recomputes it. Any
    ``uns['source_dataset_colors']`` goes with it, since a palette describes the
    categories it was drawn for.

    All-or-nothing: every refusal comes before the snapshot, and the written
    column is read back and compared before the edit is kept. Writes a new
    timestamped snapshot with an edit-log entry and deletes the previous
    snapshot (never the original), like every other mutating tool.

    Args:
        path: Path to an integrated-object .h5ad under the tracker layout.
            Auto-resolves to the latest timestamped edit snapshot.

    Returns:
        Dict with ``output_path``, ``column``, ``n_obs``, ``replaced`` (whether
        a ``source_dataset`` column was already there) and ``sources`` (one row
        per candidate — ``tracker_name``, ``filename``, ``cells`` — most cells
        first, as ``find_source_datasets`` orders them) on success, or
        ``{"error": ...}``.
    """
    try:
        path = resolve_latest(path)
        if not Path(path).is_file():
            return {"error": f"File not found: {path}"}

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
