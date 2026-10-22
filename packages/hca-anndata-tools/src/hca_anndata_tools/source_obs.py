"""Whether an integrated object's cells carry their source datasets' obs metadata (#793).

Every check so far reads one file, so a value that changed between a source
dataset and an integrated object passes both: kidney v1's reprocessed sources
carry another channel's ``library_id`` on 95,495 cells that the object has
right, and breast v1's object lost the ``library_id`` of 126,227 nee2023 cells.
Each cell is matched to its source by ID through :func:`match_sources`, the
match ``set_source_dataset`` writes, so the object need not carry
``obs['source_dataset']``. The check reports differences; it never says which
side is right, because in kidney the object is right and in HKB26/HKB27 the
source is.
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from anndata.io import read_elem

from ._errors import Refusal
from ._io import check_duplicate_ids, gate_h5ad_paths, obs_index_name, read_index
from .guards import require_obs_group
from .qc import SAMPLE_ID_LIMIT, finding, run_read
from .schema.core import Cell
from .schema.helpers import obs_field_names
from .sources import SourceMatch, match_sources, tracker_name

# A CELLxGENE field with no HCA meaning, so a difference in it is no finding.
EXCLUDED_FIELDS = frozenset({"is_primary_data"})

# An integrated object may re-annotate cell types on purpose, so these are
# reported apart from the donor, sample and library fields and never as findings.
CELL_TYPE_FIELDS = frozenset(Cell.model_fields) & obs_field_names()

COMPARED_FIELDS = tuple(sorted(obs_field_names() - EXCLUDED_FIELDS))
PAIRS_LIMIT = 20

# What a compared cell's field can be, and the finding code of each kind of disagreement.
OUTCOMES = ("agree", "differ", "missing_in_object", "missing_in_source", "missing_in_both")
CODES = {"differ": "values_differ", "missing_in_object": "missing_in_object", "missing_in_source": "missing_in_source"}


def _canonical(values) -> np.ndarray:
    """One comparable text value per cell, None only where the stored value is null.

    Categorical, plain and nullable columns of one value read alike, and a
    whole number reads the same stored as an int, a float or a string. Any
    text is a value, placeholders included: whether a value is allowed in its
    slot is the schema validator's question, not this check's.
    """
    s = pd.Series(values)
    if isinstance(s.dtype, pd.CategoricalDtype):
        categories = np.append(_canonical(s.cat.categories.to_numpy()), np.array([None], dtype=object))
        return categories[s.cat.codes.to_numpy()]  # code -1, a null, picks the trailing None
    if pd.api.types.is_numeric_dtype(s.dtype) and not pd.api.types.is_bool_dtype(s.dtype):
        f = s.to_numpy(dtype=float, na_value=np.nan)
        out = np.full(len(f), None, dtype=object)
        finite = np.isfinite(f)
        whole = finite & (f == np.round(f))
        out[whole] = f[whole].astype(np.int64).astype(str)
        out[finite & ~whole] = f[finite & ~whole].astype(str)
        out[f == np.inf] = "inf"
        out[f == -np.inf] = "-inf"
        return out
    # A whole number written as text keeps pandas' ".0" (pancreas sources carry
    # "2021.0" where the object stores 2021.0); only that suffix is dropped, so
    # "run01" and "01" stay distinct from "1".
    null = s.isna().to_numpy()
    out = s.astype(str).str.replace(r"^(-?\d+)\.0+$", r"\1", regex=True).to_numpy(dtype=object)
    out[null] = None
    return out


def _read_field(f: h5py.File, field: str) -> np.ndarray | None:
    obs = require_obs_group(f)
    return _canonical(read_elem(obs[field])) if field in obs else None


def _source_rows(path: Path, ids: np.ndarray) -> np.ndarray:
    """Each of ``ids``' row in the source at ``path``; repeated source IDs are refused, as their row is ambiguous."""
    with h5py.File(path, "r") as f:
        obs = require_obs_group(f)
        index = pd.Index(read_index(obs, obs_index_name(obs), "obs"))
    if (dup := check_duplicate_ids(index, f"{path.name} cell IDs")) is not None:
        raise Refusal(f"{dup}; which source row an object cell came from is ambiguous")
    return index.get_indexer(ids)


def _compare(source: np.ndarray, target: np.ndarray) -> dict[str, np.ndarray]:
    """Each cell's outcome, as one mask per :data:`OUTCOMES` entry."""
    s_set, t_set = pd.notna(source), pd.notna(target)
    both = s_set & t_set
    same = np.zeros(len(source), dtype=bool)
    same[both] = source[both] == target[both]
    return {
        "agree": both & same,
        "differ": both & ~same,
        "missing_in_object": s_set & ~t_set,
        "missing_in_source": ~s_set & t_set,
        "missing_in_both": ~s_set & ~t_set,
    }


def _pairs(source: np.ndarray, target: np.ndarray) -> list[dict]:
    """The value pairs of the cells that do not agree, most cells first; a missing side is None."""
    pairs = pd.DataFrame({"source_value": source, "object_value": target}).value_counts(dropna=False)
    rows = [
        {"source_value": None if pd.isna(s) else s, "object_value": None if pd.isna(t) else t, "cells": int(n)}
        for (s, t), n in pairs.items()
    ]
    rows.sort(key=lambda r: (-r["cells"], str(r["source_value"]), str(r["object_value"])))
    return rows[:PAIRS_LIMIT]


def _compare_fields(match: SourceMatch) -> tuple[list[dict], list[dict], list[dict], list[dict], list[str]]:
    single = match.claims == 1
    by_source = []
    for position, row in enumerate(match.sources):
        cells = np.flatnonzero(single & (match.owner == position))
        if cells.size:
            path = match.source_dir / row["filename"]
            by_source.append((row["tracker_name"], path, cells, _source_rows(path, match.target_ids[cells])))

    fields, discrepancies, findings, absent = [], [], [], []
    for field in COMPARED_FIELDS:
        with h5py.File(match.target, "r") as f:
            target = _read_field(f, field)
        in_sources = 0
        totals: dict[str, int] = dict.fromkeys(OUTCOMES, 0)
        flagged: dict[str, list[np.ndarray]] = {key: [] for key in CODES}
        group = "cell_type" if field in CELL_TYPE_FIELDS else "metadata"
        for name, path, cells, rows in by_source:
            with h5py.File(path, "r") as f:
                source = _read_field(f, field)
            in_sources += source is not None
            s = source[rows] if source is not None else np.full(cells.size, None, dtype=object)
            t = target[cells] if target is not None else np.full(cells.size, None, dtype=object)
            outcome = _compare(s, t)
            for key, mask in outcome.items():
                totals[key] += int(mask.sum())
            off = outcome["differ"] | outcome["missing_in_object"] | outcome["missing_in_source"]
            if off.any():
                discrepancies.append(
                    {
                        "field": field,
                        "group": group,
                        "source": name,
                        **{key: int(outcome[key].sum()) for key in CODES},
                        "pairs": _pairs(s[off], t[off]),
                    }
                )
                for key in CODES:
                    flagged[key].append(cells[outcome[key]])
        if target is None and not in_sources:
            absent.append(field)
            continue
        fields.append(
            {"field": field, "group": group, "in_object": target is not None, "in_sources": in_sources, **totals}
        )
        if group == "metadata":
            for key, code in CODES.items():
                if totals[key]:
                    where = np.concatenate(flagged[key])
                    findings.append(
                        finding(code, totals[key], match.target_ids[where[:SAMPLE_ID_LIMIT]], f"obs/{field}")
                    )
    discrepancies.sort(key=lambda r: (r["group"] != "metadata", r["field"], r["source"]))
    compared = [
        {"tracker_name": name, "filename": path.name, "cells_compared": int(cells.size)}
        for name, path, cells, _ in by_source
    ]
    return compared, fields, discrepancies, findings, absent


def _check_at_path(path: str) -> dict:
    match = match_sources(path)
    sources, fields, discrepancies, findings, absent = _compare_fields(match)
    single = match.claims == 1
    return {
        "filename": match.target.name,
        "tracker_name": tracker_name(match.target.name),
        "source_dir": str(match.source_dir),
        "partition": "exact" if single.all() else "incomplete",
        "cells": {"n_obs": len(match.target_ids), "compared": int(single.sum()), "not_compared": int((~single).sum())},
        "sources": sources,
        "fields": fields,
        "fields_absent": absent,
        "discrepancies": discrepancies,
        "findings": match.findings() + findings,
    }


@gate_h5ad_paths
def check_source_obs(path: str) -> dict:
    """Compare an integrated object's obs metadata with its source datasets', cell by cell.

    Read-only; reads obs, no matrix. Each object cell is matched by ID to the
    source dataset that holds it, found as ``find_source_datasets`` finds them
    (the sibling ``source-datasets/tracker-source/`` under the tracker layout),
    and every field the HCA schema stores in ``obs`` is compared between the two
    rows by exact value, except ``is_primary_data``. One allowance: a whole
    number stored as an int, a float or ``.0`` text compares as its integer
    text, so ``"2021.0"`` agrees with 2021 and is reported as ``"2021"``.
    Only a stored null is missing; any other text, placeholders
    such as ``"unknown"`` or ``"nan"`` included, is a value, since whether it
    is allowed is the validator's call.
    A cell no single source claims is not compared and is listed in
    ``findings`` as ``find_source_datasets`` lists it.

    The check does not say which side is right. ``cell_type_ontology_term_id``
    and ``author_cell_type`` are reported with ``group`` ``"cell_type"`` and
    never as findings, because an integrated object may re-annotate on purpose.

    Refuses as ``find_source_datasets`` does, and a source dataset whose cell
    IDs repeat, since which of its rows an object cell came from is ambiguous.

    Args:
        path: Integrated-object .h5ad under the tracker layout; auto-resolves to the latest edit snapshot.

    Returns:
        Dict with ``filename``, ``tracker_name``, ``source_dir``, ``partition``
        (``"exact"`` or ``"incomplete"``), ``cells`` (``n_obs``, ``compared``,
        ``not_compared``), ``sources`` (each source holding a compared cell, with
        ``cells_compared``), ``fields`` (one row per field either side carries:
        ``group``, ``in_object``, ``in_sources`` = how many of ``sources`` carry
        it, and cell counts ``agree`` / ``differ`` / ``missing_in_object`` /
        ``missing_in_source`` / ``missing_in_both``), ``fields_absent`` (fields
        neither the object nor any of ``sources`` carries; a source holding no
        compared cell is matched by ID but its fields are not read),
        ``discrepancies`` (one row per field and source with a cell that
        differs or is set on one side only: the three counts and ``pairs`` of
        ``source_value`` / ``object_value`` / ``cells``, a missing side None,
        most cells first, capped at :data:`PAIRS_LIMIT`; metadata
        before cell type) and ``findings`` (``values_differ``,
        ``missing_in_object``, ``missing_in_source`` per metadata field on
        ``obs/<field>``, in the shared shape). On failure, ``error`` is
        returned instead.
    """
    return run_read(path, _check_at_path)
