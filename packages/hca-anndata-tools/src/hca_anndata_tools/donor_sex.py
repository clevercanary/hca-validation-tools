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

1. **Streaming, not loaded.** CSR and dense stream through
   :func:`qc.iter_matrix_chunks` over the matrix ``check_raw_counts``
   gates; CSC reads the 17 panel columns one at a time. The original loads
   the object, which the 20-30 GB atlas objects forbid.
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
6. **Ensembl version suffixes are stripped** before matching, as
   ``read_var_gene_names`` does; the original matches the index verbatim.
7. **Only the two PATO terms and ``unknown`` are read as an annotation.**
   The original maps anything else to NaN and drops it from the comparison;
   here any other value refuses by name, since a controlled column holding
   a label or a stray term is a schema defect the check should not paper
   over. The verbatim term is carried in each row as ``annotated_term``.
8. **A matrix that is not counts is not judged.** The original assumes
   ``raw.X`` is raw. Here the same classifier ``check_raw_counts`` uses
   decides, and a normalized-only ``X`` returns ``not_applicable``.
"""

from __future__ import annotations

import h5py
import numpy as np
import pandas as pd
from anndata.io import sparse_dataset

from ._errors import Refusal
from ._io import (
    check_duplicate_ids,
    gate_h5ad_paths,
    read_element,
    read_group,
    read_key_column,
    strip_ensembl_version,
)
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
        chunk_nnz: Stored entries per chunk on the streaming formats (CSR,
            dense); bounds their peak memory. CSC reads one panel column at
            a time instead. Must be >= 1.

    Returns:
        Dict with ``filename``, ``matrix``, ``format``, ``dtype``, ``n_obs``,
        ``n_var``, ``nnz``, ``integer_check`` (as ``check_raw_counts``
        reports it), ``gene_panel`` (``status`` ``applied``, or
        ``not_applicable`` with a ``reason``: the matrix is not counts, or
        either gene set is absent from var), ``genes_found`` (``male`` and
        ``female`` symbol lists), ``donors``, and ``findings``.

        ``donors`` has one row per donor — two when a donor has both droplet
        and plate-based libraries, the plate-based row's ``donor_id``
        suffixed ``-smartseq`` and its ``smart_seq`` flag set: ``donor_id``,
        ``smart_seq``, ``cells``, ``male_counts``, ``female_counts``,
        ``total_counts``, ``ratio`` (``null`` when the female sum is zero),
        ``inferred``, ``annotated`` (``male`` / ``female`` / ``unknown``),
        ``annotated_term`` (the obs value verbatim, ``null`` when the column
        is absent), ``verdict``. Verdicts, in precedence order:

        - ``not_applicable`` — the donor is not human
        - ``below_floor`` — fewer than 100 counts across both gene sets
        - ``indeterminate`` — ratio between 0.05 and 0.35, inclusive
        - ``fill_in`` — annotated ``unknown`` (or absent) but the ratio is clear
        - ``agree`` / ``contradiction`` — the ratio's call against the annotation

        Findings, each counting donors and naming them in ``sample_ids``:
        ``sex_contradiction``, ``sex_fillable``, ``sex_below_floor``. Empty
        findings with ``gene_panel.status == "applied"`` means every callable
        donor agrees with its annotation.

        Refused by name, since each is a defect another check owns and a
        call over it would be against an arbitrary value: a donor carrying
        two annotated sexes or two organisms (#680), a missing or unknown
        term in ``sex_ontology_term_id`` or ``organism_ontology_term_id``,
        a panel gene listed twice in var, and a NaN or negative count in a
        panel gene (``check_raw_counts``). On failure, ``error`` is returned
        instead.
    """
    return run_read_check(path, chunk_nnz, _check_donor_sex_at_path)


def _check_donor_sex_at_path(path: str, chunk_nnz: int) -> dict:
    with h5py.File(path, "r") as f:
        cm = open_count_matrix(f)
        result = {**cm.envelope(path), "integer_check": cm.integer_check}
        var_ids = [strip_ensembl_version(v) for v in cm.read_var_ids(f)]
        male_cols, male_found = _locate(var_ids, MALE_GENES)
        female_cols, female_found = _locate(var_ids, FEMALE_GENES)
        result["genes_found"] = {"male": male_found, "female": female_found}
        if (reason := _not_applicable_reason(cm, male_found, female_found)) is not None:
            result.update(gene_panel={"status": VERDICT_NOT_APPLICABLE, "reason": reason}, donors=[], findings=[])
            return result
        result["gene_panel"] = {"status": "applied"}
        panel = {var_ids[c] for c in (*male_cols, *female_cols)}
        if duplicated := check_duplicate_ids([v for v in var_ids if v in panel], cm.var_key):
            raise Refusal(f"a panel gene is listed twice, so its column is ambiguous: {duplicated}")
        obs = read_group(f, "obs")
        # The anndata gate refuses an obs that is not a dataframe group (a compound
        # dataset fails its own read), so this narrows for pyright only.
        assert obs is not None
        if "donor_id" not in obs:
            raise Refusal("obs has no donor_id column, so counts cannot be grouped by donor")
        donor = read_key_column(obs, "donor_id", "obs column")
        annotated = _obs_column(obs, "sex_ontology_term_id")
        assay = _obs_column(obs, "assay_ontology_term_id")
        organism = _obs_column(obs, "organism_ontology_term_id")
        male, female = _sum_gene_sets(f, cm.key, cm.format, cm.n_obs, male_cols, female_cols, chunk_nnz)

    rows = _donor_rows(donor, annotated, assay, organism, male, female)
    result["donors"] = rows
    result["findings"] = _findings(rows, cm.key)
    return result


def _not_applicable_reason(cm, male_found: list[str], female_found: list[str]) -> str | None:
    if cm.integer_check["status"] != "applied":
        return f"{cm.key} is not counts ({cm.integer_check['reason']}), so gene sums cannot be compared"
    if not male_found or not female_found:
        found = set(male_found) | set(female_found)
        missing = [s for s in (*MALE_GENES.values(), *FEMALE_GENES.values()) if s not in found]
        return f"{cm.var_key} lacks every gene of at least one set; missing: {', '.join(missing)}"
    return None


def _refuse_uncountable(values: np.ndarray, panel: str) -> None:
    """Refuse a NaN, Inf, or negative stored value in a panel gene, before it is summed away.

    check_raw_counts owns these defects; a ratio over them would be a number
    with no meaning, and a per-cell sum can hide one behind the other genes.
    """
    if not np.isfinite(values).all():
        raise Refusal(f"a {panel}-gene count is NaN or Inf in {int((~np.isfinite(values)).sum())} stored value(s)")
    if (values < 0).any():
        raise Refusal(f"a {panel}-gene count is negative in {int((values < 0).sum())} stored value(s)")


def _locate(var_ids: list[str], genes: dict[str, str]) -> tuple[list[int], list[str]]:
    """Column positions and symbols of the genes present, in the panel's order."""
    position = {eid: i for i, eid in enumerate(var_ids)}
    found = [(position[eid], symbol) for eid, symbol in genes.items() if eid in position]
    return [col for col, _ in found], [symbol for _, symbol in found]


def _obs_column(obs: h5py.Group, name: str) -> np.ndarray | None:
    """A per-cell obs column as objects (missing values kept as NA), or None when absent.

    The anndata gate has already refused a column whose length differs from obs.
    """
    if name not in obs:
        return None
    return np.asarray(read_element(obs[name]), dtype=object)


def _sum_gene_sets(
    f: h5py.File, key: str, fmt: str, n_obs: int, male_cols: list[int], female_cols: list[int], chunk_nnz: int
) -> tuple[np.ndarray, np.ndarray]:
    """Per-cell count sums over each gene set.

    CSC stores columns contiguously, so each of the 17 panel columns is
    read on its own through anndata's backed class and folded into the
    accumulator: peak memory is one column plus the two per-cell vectors,
    and the other 30,000 columns are never touched. CSR and dense need
    every stored entry once to find the hits, so they stream through
    :func:`qc.iter_matrix_chunks`; that pass is the cost of the check.
    """
    panels = (("male", np.asarray(male_cols)), ("female", np.asarray(female_cols)))
    sums = (np.zeros(n_obs, dtype=np.float64), np.zeros(n_obs, dtype=np.float64))
    if fmt == "csc":
        ds = sparse_dataset(f[key])  # pyright: ignore[reportArgumentType]
        for (panel, cols), into in zip(panels, sums, strict=True):
            for col in cols:
                column = ds[:, int(col) : int(col) + 1]
                _refuse_uncountable(column.data, panel)
                into[column.indices] += column.data
        return sums
    for chunk in iter_matrix_chunks(f, key, chunk_nnz, axis="row"):
        n_rows = chunk.matrix.get_shape()[0]
        rows = slice(chunk.start, chunk.start + n_rows)
        for (panel, cols), into in zip(panels, sums, strict=True):
            block = chunk.matrix[:, cols]
            _refuse_uncountable(block.data, panel)
            into[rows] += np.asarray(block.sum(axis=1), dtype=np.float64).ravel()
    return sums


def _donor_rows(
    donor: np.ndarray,
    annotated: np.ndarray | None,
    assay: np.ndarray | None,
    organism: np.ndarray | None,
    male: np.ndarray,
    female: np.ndarray,
) -> list[dict]:
    """One row per (donor, chemistry), computed on integer codes rather than per-cell strings."""
    donor_codes, donors = pd.factorize(pd.Series(donor).astype(str), sort=True)
    smart = np.zeros(len(donor), dtype=bool)
    if assay is not None:
        smart = pd.Series(assay).isin(SMART_SEQ_ASSAYS).to_numpy()
    sex_term = _per_donor_value(donor_codes, donors, annotated, "sex_ontology_term_id")
    organism_term = _per_donor_value(donor_codes, donors, organism, "organism_ontology_term_id")

    key = donor_codes * 2 + smart  # (donor, chemistry) → one integer per row
    n_keys = len(donors) * 2
    cells = np.bincount(key, minlength=n_keys)
    male_sum = np.bincount(key, weights=male, minlength=n_keys)
    female_sum = np.bincount(key, weights=female, minlength=n_keys)

    rows: list[dict] = []
    for k in np.flatnonzero(cells):
        d, is_smart = divmod(int(k), 2)
        total = float(male_sum[k] + female_sum[k])
        ratio = float(male_sum[k] / female_sum[k]) if female_sum[k] > 0 else None
        inferred = _assign_sex(ratio) if total >= COUNT_FLOOR else None
        annotated_sex = _annotated_sex(sex_term[d], donors[d])
        rows.append(
            {
                "donor_id": f"{donors[d]}{SMART_SEQ_SUFFIX}" if is_smart else str(donors[d]),
                "smart_seq": bool(is_smart),
                "cells": int(cells[k]),
                "male_counts": float(male_sum[k]),
                "female_counts": float(female_sum[k]),
                "total_counts": total,
                "ratio": ratio,
                "inferred": inferred,
                "annotated": annotated_sex,
                "annotated_term": sex_term[d],
                "verdict": _verdict(_is_human(organism_term[d], donors[d]), inferred, annotated_sex),
            }
        )
    return rows


def _per_donor_value(donor_codes: np.ndarray, donors, values: np.ndarray | None, column: str) -> list:
    """The one value each donor carries in ``column`` (None for every donor when the column is absent).

    A donor carrying two values, or a missing one, is refused by name: #680's
    donor-consistency check owns the first, the schema the second, and a
    call over either would be against an arbitrary value.
    """
    if values is None:
        return [None] * len(donors)
    missing = np.flatnonzero(pd.isna(values))
    if missing.size:
        raise Refusal(f"obs['{column}'] has {missing.size} missing value(s); a donor cannot be checked against one")
    value_codes, uniques = pd.factorize(pd.Series(values).astype(str))
    pairs = np.unique(np.stack([donor_codes, value_codes], axis=1), axis=0)
    per_donor = np.bincount(pairs[:, 0], minlength=len(donors))
    if (per_donor > 1).any():
        d = int(np.flatnonzero(per_donor > 1)[0])
        seen = sorted(str(uniques[c]) for c in pairs[pairs[:, 0] == d, 1])
        raise Refusal(f"donor {donors[d]!r} carries several {column} values: {seen}")
    return [str(uniques[c]) for c in pairs[:, 1]]  # one pair per donor, in donor order


def _annotated_sex(term: str | None, donor) -> str:
    if term is None or term == UNKNOWN:
        return UNKNOWN
    if term in ANNOTATED_SEX:
        return ANNOTATED_SEX[term]
    raise Refusal(f"donor {donor!r} has sex_ontology_term_id {term!r}, which is neither a PATO sex term nor 'unknown'")


def _is_human(term: str | None, donor) -> bool:
    if term is None:
        return True  # the schema requires the column; a file without it fails elsewhere
    return term == HUMAN


def _assign_sex(ratio: float | None) -> str:
    """``assign_sex`` in the original; a zero female sum is an infinite ratio there, so male."""
    if ratio is None or ratio > MALE_RATIO:
        return "male"
    if ratio < FEMALE_RATIO:
        return "female"
    return UNKNOWN


def _verdict(human: bool, inferred: str | None, annotated: str) -> str:
    if not human:
        return VERDICT_NOT_APPLICABLE
    if inferred is None:  # below the count floor, so no call was made
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
