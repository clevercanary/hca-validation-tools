"""Donor sex inferred from expression, compared with the annotation (#678).

A port of ``evaluate_donors_sex`` (with ``check_percent``,
``generate_fm_dict``, ``calculate_sex``, ``assign_sex``) and
``ref_files/sex_analysis_genes.json`` from Lattice Data Coordination's
lattice-tools, ``cellxgene_resources/`` at commit
``8778a14f2a5a7039acf3ce74b3da220c24521905``:
https://github.com/Lattice-Data/lattice-tools/blob/8778a14f2a5a7039acf3ce74b3da220c24521905/cellxgene_resources/cellxgene_mods.py
https://github.com/Lattice-Data/lattice-tools/blob/8778a14f2a5a7039acf3ce74b3da220c24521905/cellxgene_resources/ref_files/sex_analysis_genes.json

    MIT License

    Copyright (c) 2020 Lattice Data Coordination

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

The original, on an in-memory object: subset ``raw.X`` to seven Y-linked
genes and ten X-escapees, sum each set per donor, drop donors with fewer
than 100 counts across both, take ``male / female``, and call male above
0.35, female below 0.05, unknown between. Donors whose libraries are
plate-based (its ``smart_assay_list``) are split off with a ``-smartseq``
suffix because the ratio differs by chemistry. It bails when either gene
set is absent from ``var``. The thresholds are Lattice's empirical cuts;
they are carried, cited, and not re-derived. Measured 2026-09-03 on an
snRNA-seq object (147k nuclei, 27 donors) they separate nuclei as cleanly
as cells, so nothing is adjusted for ``suspension_type``.

Deviations from the original, each with its reason:

1. **Streaming, not loaded.** One pass of :func:`qc.iter_matrix_chunks`
   over the matrix ``check_raw_counts`` gates, in either CSR or CSC; the
   original loads the object, which the 20-30 GB atlas objects forbid.
2. **Organism per donor, from obs.** HCA stores organism in obs, not uns;
   a non-human donor is ``not_applicable`` rather than the whole file bailing.
3. **A verdict per donor, not a plot.** The original returns a dataframe
   and a dotplot for a curator to read; this returns one verdict per donor
   and three findings in the shared shape, so an agent can act on it.
   Lattice's notebook treats an annotated ``unknown`` that is inferable as
   a warning and male-vs-female disagreement as an error; those are the
   ``sex_fillable`` and ``sex_contradiction`` codes.
4. **Below-floor donors are reported, not dropped.** The original removes
   them silently before the ratio; here they are a bucket, since a donor
   with almost no counts in these genes is itself worth a look.
5. **Missing genes are named.** The original prints a percentage found.
"""

from __future__ import annotations

import h5py
import numpy as np
import pandas as pd

from ._errors import Refusal
from ._io import gate_h5ad_paths, obs_index_name, read_element, read_group, read_index
from .qc import DEFAULT_CHUNK_NNZ, finding, iter_matrix_chunks, open_count_matrix, run_read_check

# ``ref_files/sex_analysis_genes.json`` at the pinned commit, keyed by Ensembl ID.
MALE_GENES: dict[str, str] = {
    "ENSG00000067646": "ZFY",
    "ENSG00000114374": "USP9Y",
    "ENSG00000067048": "DDX3Y",
    "ENSG00000183878": "UTY",
    "ENSG00000165246": "NLGN4Y",
    "ENSG00000012817": "KDM5D",
    "ENSG00000198692": "EIF1AY",
}
FEMALE_GENES: dict[str, str] = {
    "ENSG00000130021": "PUDP",
    "ENSG00000006757": "PNPLA4",
    "ENSG00000169249": "ZRSR2",
    "ENSG00000173674": "EIF1AX",
    "ENSG00000005889": "ZFX",
    "ENSG00000147050": "KDM6A",
    "ENSG00000126012": "KDM5C",
    "ENSG00000270641": "TSIX",
    "ENSG00000229807": "XIST",
    "ENSG00000225470": "JPX",
}
# ``assign_sex`` and ``calculate_sex`` in the original.
MALE_RATIO = 0.35  # male / female above this is male
FEMALE_RATIO = 0.05  # below this is female; between is unknown
COUNT_FLOOR = 100  # donors with fewer counts across both sets are not called
# ``smart_assay_list`` in the original: plate-based assays whose ratio differs.
SMART_SEQ_ASSAYS = frozenset(
    {"EFO:0010184", "EFO:0008931", "EFO:0008930", "EFO:0010022", "EFO:0700016", "EFO:0022488", "EFO:0008442"}
)
SMART_SEQ_SUFFIX = "-smartseq"

HUMAN = "NCBITaxon:9606"
ANNOTATED_SEX = {"PATO:0000383": "female", "PATO:0000384": "male"}
UNKNOWN = "unknown"

VERDICT_AGREE = "agree"
VERDICT_CONTRADICTION = "contradiction"
VERDICT_FILL_IN = "fill_in"
VERDICT_BELOW_FLOOR = "below_floor"
VERDICT_INDETERMINATE = "indeterminate"
VERDICT_NOT_APPLICABLE = "not_applicable"


@gate_h5ad_paths
def check_donor_sex(path: str, chunk_nnz: int = DEFAULT_CHUNK_NNZ) -> dict:
    """Infer each donor's sex from Y-linked and X-escapee expression and compare it with obs.

    A port of Lattice's ``evaluate_donors_sex`` (see the module docstring for
    provenance and deviations). Sums raw counts over seven Y-linked and ten
    X-escapee genes per donor in one streaming pass over the matrix
    ``check_raw_counts`` gates — ``raw.X`` when present, otherwise ``X`` —
    and calls male when ``male / female`` exceeds 0.35, female below 0.05.
    Read-only. Report-only: nothing here is a validator error.

    Args:
        path: Path to an .h5ad file.
        chunk_nnz: Stored entries per chunk; bounds peak memory. Must be >= 1.

    Returns:
        Dict with ``filename``, ``matrix``, ``format``, ``dtype``, ``n_obs``,
        ``n_var``, ``nnz``, ``status`` (``applied``, or ``not_applicable``
        with a ``reason`` when either gene set is absent from var),
        ``genes_found`` (``male`` and ``female`` symbol lists), ``donors``
        (one row per donor — per donor *and chemistry* when a donor has both
        droplet and plate-based libraries, the plate-based row suffixed
        ``-smartseq``: ``donor_id``, ``cells``, ``male_counts``,
        ``female_counts``, ``total_counts``, ``ratio`` (``null`` when the
        female sum is zero), ``inferred``, ``annotated``, ``verdict``), and
        ``findings``. Verdicts, in precedence order:

        - ``not_applicable`` — the donor is not human
        - ``below_floor`` — fewer than 100 counts across both gene sets
        - ``fill_in`` — annotated ``unknown`` (or absent) but the ratio is clear
        - ``indeterminate`` — ratio between 0.05 and 0.35, inclusive
        - ``agree`` / ``contradiction`` — the ratio's call against the annotation

        Findings, each counting donors and naming them in ``sample_ids``:
        ``sex_contradiction``, ``sex_fillable``, ``sex_below_floor``. Empty
        findings with ``status == "applied"`` means every callable donor
        agrees with its annotation. On failure, ``error`` is returned instead.
    """
    return run_read_check(path, chunk_nnz, _check_donor_sex_at_path)


def _check_donor_sex_at_path(path: str, chunk_nnz: int) -> dict:
    with h5py.File(path, "r") as f:
        cm = open_count_matrix(f)
        result = cm.envelope(path)
        var = f[cm.var_key]
        var_ids = [_strip_version(v) for v in read_index(var, obs_index_name(var), "var")]
        male_cols, male_found = _locate(var_ids, MALE_GENES)
        female_cols, female_found = _locate(var_ids, FEMALE_GENES)
        result["genes_found"] = {"male": male_found, "female": female_found}
        if not male_cols or not female_cols:
            missing = [s for eid, s in {**MALE_GENES, **FEMALE_GENES}.items() if eid not in set(var_ids)]
            result["status"] = {
                "status": VERDICT_NOT_APPLICABLE,
                "reason": f"{cm.var_key} lacks every gene of at least one set; missing: {', '.join(missing)}",
            }
            result["donors"] = []
            result["findings"] = []
            return result
        result["status"] = {"status": "applied"}
        obs = read_group(f, "obs")
        if obs is None:
            raise Refusal("obs is not a group, so counts cannot be grouped by donor")
        donor = _obs_column(obs, "donor_id", cm.n_obs)
        if donor is None:
            raise Refusal("obs has no donor_id column, so counts cannot be grouped by donor")
        annotated = _obs_column(obs, "sex_ontology_term_id", cm.n_obs)
        assay = _obs_column(obs, "assay_ontology_term_id", cm.n_obs)
        organism = _obs_column(obs, "organism_ontology_term_id", cm.n_obs)
        male, female = _sum_gene_sets(f, cm.key, cm.n_obs, male_cols, female_cols, chunk_nnz)

    rows = _donor_rows(donor, annotated, assay, organism, male, female)
    result["donors"] = rows
    result["findings"] = _findings(rows, cm.key)
    return result


def _strip_version(eid: str) -> str:
    return eid.rsplit(".", 1)[0] if eid.startswith("ENSG") and "." in eid else eid


def _locate(var_ids: list[str], genes: dict[str, str]) -> tuple[list[int], list[str]]:
    position = {eid: i for i, eid in enumerate(var_ids)}
    cols = [position[eid] for eid in genes if eid in position]
    return cols, [genes[eid] for eid in genes if eid in position]


def _obs_column(obs: h5py.Group, name: str, n_obs: int) -> np.ndarray | None:
    if name not in obs:
        return None
    values = np.asarray(read_element(obs[name]), dtype=object)
    if len(values) != n_obs:
        raise Refusal(f"obs['{name}'] has {len(values)} values but the matrix has {n_obs} rows")
    return values


def _sum_gene_sets(
    f: h5py.File, key: str, n_obs: int, male_cols: list[int], female_cols: list[int], chunk_nnz: int
) -> tuple[np.ndarray, np.ndarray]:
    """Per-cell count sums over each gene set, from one pass in either orientation."""
    male = np.zeros(n_obs, dtype=np.float64)
    female = np.zeros(n_obs, dtype=np.float64)
    male_set, female_set = np.asarray(male_cols), np.asarray(female_cols)
    for chunk in iter_matrix_chunks(f, key, chunk_nnz, axis="any"):
        m = chunk.matrix
        n_rows, n_cols = m.get_shape()
        if chunk.axis == "row":
            rows = slice(chunk.start, chunk.start + n_rows)
            male[rows] += np.asarray(m[:, male_set].sum(axis=1)).ravel()
            female[rows] += np.asarray(m[:, female_set].sum(axis=1)).ravel()
        else:
            stop = chunk.start + n_cols
            for cols, into in ((male_set, male), (female_set, female)):
                local = cols[(cols >= chunk.start) & (cols < stop)] - chunk.start
                if local.size:
                    into += np.asarray(m[:, local].sum(axis=1)).ravel()
    return male, female


def _donor_rows(
    donor: np.ndarray,
    annotated: np.ndarray | None,
    assay: np.ndarray | None,
    organism: np.ndarray | None,
    male: np.ndarray,
    female: np.ndarray,
) -> list[dict]:
    key = pd.Series(donor).astype(str)
    if assay is not None:
        key = key.where(~pd.Series(assay).astype(str).isin(SMART_SEQ_ASSAYS), key + SMART_SEQ_SUFFIX)
    frame = pd.DataFrame(
        {
            "key": key.to_numpy(),
            "annotated": _annotated_sex(annotated, len(donor)),
            "human": np.ones(len(donor), dtype=bool) if organism is None else pd.Series(organism).astype(str).eq(HUMAN),
            "male": male,
            "female": female,
        }
    )
    grouped = frame.groupby("key", sort=True)
    rows: list[dict] = []
    for name, g in grouped:
        donor_key = str(name)
        male_sum, female_sum = float(g["male"].sum()), float(g["female"].sum())
        total = male_sum + female_sum
        annotated_sex = _one_value(g["annotated"].to_numpy(), donor_key, "sex_ontology_term_id")
        ratio = male_sum / female_sum if female_sum > 0 else None
        inferred = _assign_sex(ratio) if total >= COUNT_FLOOR else None
        rows.append(
            {
                "donor_id": donor_key,
                "cells": len(g),
                "male_counts": male_sum,
                "female_counts": female_sum,
                "total_counts": total,
                "ratio": ratio,
                "inferred": inferred,
                "annotated": annotated_sex,
                "verdict": _verdict(bool(g["human"].all()), total, inferred, annotated_sex),
            }
        )
    return rows


def _annotated_sex(annotated: np.ndarray | None, n: int) -> np.ndarray:
    if annotated is None:
        return np.full(n, UNKNOWN, dtype=object)
    return np.array([ANNOTATED_SEX.get(str(v), UNKNOWN) for v in annotated], dtype=object)


def _one_value(values_seen: np.ndarray, donor: str, column: str) -> str:
    values = sorted(set(values_seen))
    if len(values) > 1:
        # #680 (donor-level consistency) owns this defect; here the call would be
        # against an arbitrary one of the values, so refuse by name instead.
        raise Refusal(f"donor {donor!r} carries several {column} values: {values}")
    return values[0]


def _assign_sex(ratio: float | None) -> str:
    """``assign_sex`` in the original; a zero female sum is an infinite ratio there, so male."""
    if ratio is None or ratio > MALE_RATIO:
        return "male"
    if ratio < FEMALE_RATIO:
        return "female"
    return UNKNOWN


def _verdict(human: bool, total: float, inferred: str | None, annotated: str) -> str:
    if not human:
        return VERDICT_NOT_APPLICABLE
    if total < COUNT_FLOOR:
        return VERDICT_BELOW_FLOOR
    if inferred == UNKNOWN:
        return VERDICT_INDETERMINATE
    if annotated == UNKNOWN:
        return VERDICT_FILL_IN
    return VERDICT_AGREE if inferred == annotated else VERDICT_CONTRADICTION


def _findings(rows: list[dict], matrix: str) -> list[dict]:
    findings = []
    for code, verdict in (
        ("sex_contradiction", VERDICT_CONTRADICTION),
        ("sex_fillable", VERDICT_FILL_IN),
        ("sex_below_floor", VERDICT_BELOW_FLOOR),
    ):
        donors = [r["donor_id"] for r in rows if r["verdict"] == verdict]
        if donors:
            findings.append(finding(code, len(donors), donors, matrix))
    return findings
