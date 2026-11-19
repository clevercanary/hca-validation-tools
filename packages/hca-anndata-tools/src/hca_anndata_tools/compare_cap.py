"""Whether a CAP export fits a tracker file, before ``copy_cap_annotations`` writes anything (#749)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import h5py

from . import cap_pair as checks
from ._errors import failure_result
from ._gencode import load_gencode_reference
from ._io import check_duplicate_ids, gate_h5ad_paths, read_column_order, read_obs_column_names
from .cap_currency import _read_cap
from .guards import require_obs_group
from .marker_genes import human_gate_failure, marker_symbols, markers_against_var
from .write import resolve_latest

# Gene lists can run to thousands; the counts carry the rest.
GENE_EXAMPLES = 25

# Keyed by (has deprecated top-level CAP keys, has a nested cap_metadata group); a cap_metadata that is
# not a group is "malformed", the same reading as the source_cap_block check.
_LAYOUTS = {(False, True): "nested", (True, True): "mixed", (True, False): "legacy", (False, False): "absent"}

# The one check the copy waives with overwrite=True, after stripping the target's CAP.
EXISTING_CAP_CHECK = "target_has_no_cap"
CELL_CHECK = "cell_overlap"
_STRIP_NOTE = (
    " With overwrite=True the copy first runs strip_cap_annotations, which makes checks of its own"
    " that this report does not run."
)


@dataclass(frozen=True)
class Check:
    """One of the copy's checks: ``message`` is its refusal when failed, the reason when not run."""

    name: str
    status: Literal["pass", "fail", "not_run"]
    message: str | None = None


@dataclass(frozen=True)
class _Pair:
    checks: list[Check]
    annotation_sets: list[str]
    source_cells: list[str]
    target_cells: list[str]
    source_genes: set[str]
    target_genes: set[str]
    cells: dict


def _check(name: str, failure: str | None) -> Check:
    return Check(name, "fail" if failure else "pass", failure)


def _not_run(names: tuple[str, ...], reason: str) -> list[Check]:
    return [Check(n, "not_run", reason) for n in names]


def _assess(source_path: str, target_path: str) -> _Pair:
    """Every check of the copy, in its order; a check runs whenever the data it needs could be read."""
    same = checks.SAME_FILE_ERROR if Path(source_path).samefile(target_path) else None
    out = [_check("distinct_files", same)]

    with h5py.File(source_path, "r") as f:
        cap = checks.read_source_cap(f)
        out += [
            _check("source_layout", checks.source_layout_failure(cap)),
            _check("source_cap_block", checks.source_block_failure(cap)),
        ]
        sets: list[str] = []
        if cap.block is None:
            names = ("source_cap_metadata", "source_schema_version", "source_annotation_sets")
            out += _not_run(names, "the source has no usable uns['cap_metadata']")
        else:
            sets = checks.annotation_sets(cap.block)
            out += [
                _check("source_cap_metadata", checks.source_metadata_failure(cap.block)),
                _check("source_schema_version", checks.source_schema_version_failure(cap.block)),
                _check("source_annotation_sets", checks.annotation_sets_failure(sets)),
            ]
        obs_group = require_obs_group(f)
        columns = checks.columns_to_copy(sets, read_column_order(obs_group))
        if sets:
            out += [
                _check("source_columns_categorical", checks.non_categorical_failure(obs_group, columns)),
                _check("source_columns_present", checks.columns_failure(columns)),
            ]
        else:
            names = ("source_columns_categorical", "source_columns_present")
            out += _not_run(names, "the source declares no annotation sets")
        source_cells, source_genes = checks.read_ids(f, "CAP")

    with h5py.File(target_path, "r") as f:
        target_cells, target_genes = checks.read_ids(f, "HCA")
        target_cap = checks.read_target_cap(f, read_column_order(require_obs_group(f)))

    cells = checks.compute_axis_overlap(set(source_cells), set(target_cells))
    out += [
        _check("source_cell_ids_unique", check_duplicate_ids(source_cells, "CAP cells")),
        _check("source_gene_ids_unique", check_duplicate_ids(source_genes, "CAP genes")),
        _check("target_cell_ids_unique", check_duplicate_ids(target_cells, "HCA cells")),
        _check("target_gene_ids_unique", check_duplicate_ids(target_genes, "HCA genes")),
        _check("target_layout", checks.target_layout_failure(target_cap)),
        _check(EXISTING_CAP_CHECK, checks.existing_cap_failure(target_cap)),
        _check(CELL_CHECK, checks.cell_overlap_failure(cells)),
    ]
    return _Pair(out, sets, source_cells, target_cells, set(source_genes), set(target_genes), cells)


def _cap(path: str) -> dict:
    with h5py.File(path, "r") as f:
        cap = checks.read_source_cap(f)
    layout = "malformed" if cap.present and cap.block is None else _LAYOUTS[cap.legacy, cap.block is not None]
    return {"layout": layout, "fields": _read_cap(Path(path))[1]}


def _cells(pair: _Pair) -> dict:
    cell_check = next(c for c in pair.checks if c.name == CELL_CHECK)
    return {**pair.cells, "within_copy_limit": cell_check.status == "pass"}


def _genes(pair: _Pair) -> dict:
    return {
        **checks.compute_axis_overlap(pair.source_genes, pair.target_genes),
        "missing_from_hca_examples": sorted(pair.source_genes - pair.target_genes)[:GENE_EXAMPLES],
        "missing_from_cap_examples": sorted(pair.target_genes - pair.source_genes)[:GENE_EXAMPLES],
    }


def _with_ensembl_ids(markers: dict) -> dict:
    """``markers`` with each ``missing_from_var`` entry given its symbol's GENCODE ``ensembl_ids``."""
    _, name_to_ids = load_gencode_reference()

    def add(entries: list[dict]) -> list[dict]:
        return [{**e, "ensembl_ids": name_to_ids[e["marker_gene"]]} for e in entries]

    details = {s: {**d, "missing_from_var": add(d["missing_from_var"])} for s, d in markers["details"].items()}
    return {**markers, "missing_from_var": add(markers["missing_from_var"]), "details": details}


def _markers(source_path: str, target_path: str, sets: list[str]) -> dict:
    """The markers of the sets the copy would copy, checked against the target's var."""
    if failure := human_gate_failure(target_path, read_obs_column_names(target_path)):
        return {"error": failure}
    return _with_ensembl_ids(markers_against_var(marker_symbols(source_path, sets), target_path))


def _verdict(found: list[Check]) -> dict:
    failed = [c for c in found if c.status == "fail"]
    blocking = [c for c in failed if c.name != EXISTING_CAP_CHECK]
    if blocking:
        return {"copy_would_accept": "no", "refused_by": blocking[0].name, "message": blocking[0].message}
    if failed:
        message = f"{failed[0].message}{_STRIP_NOTE}"
        return {"copy_would_accept": "with_overwrite", "refused_by": failed[0].name, "message": message}
    return {"copy_would_accept": "yes", "refused_by": None, "message": None}


@gate_h5ad_paths
def compare_cap_export(source_path: str, target_path: str) -> dict:
    """Report whether ``copy_cap_annotations`` would accept a CAP export and a target, and how they differ.

    Writes nothing, and reads no matrix. ``source_path`` is the CAP export and
    ``target_path`` the file it would annotate, as in the copy; the target
    resolves to its latest snapshot. The copy's checks all run, where the
    copy stops at its first refusal.

    Returns:
        Dict with ``cells`` (overlap and ``within_copy_limit``), ``genes`` (overlap and up to 25 sorted IDs
        missing each way), ``marker_genes`` (the export's markers against the
        target's var; a marker the target does not measure carries its GENCODE
        ``ensembl_ids``), ``cap`` (each file's CAP ``layout``: nested, mixed,
        legacy, malformed or absent, and its ``fields``),
        ``checks`` (each with ``status`` pass, fail or not_run) and
        ``verdict`` (``copy_would_accept`` yes, with_overwrite or no, the
        ``refused_by`` check and its ``message``), or ``{"error": ...}``.
    """
    try:
        target_path = resolve_latest(target_path)
        pair = _assess(source_path, target_path)
        return {
            "source": source_path,
            "target": target_path,
            "cells": _cells(pair),
            "genes": _genes(pair),
            "marker_genes": _markers(source_path, target_path, pair.annotation_sets),
            "cap": {"export": _cap(source_path), "target": _cap(target_path)},
            "checks": [asdict(c) for c in pair.checks],
            "verdict": _verdict(pair.checks),
        }
    except Exception as e:
        return failure_result(e)
