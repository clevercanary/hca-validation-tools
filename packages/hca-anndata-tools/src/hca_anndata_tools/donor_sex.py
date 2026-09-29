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
   (tallied in ``verdict_counts``; listed in ``donors``, capped per
   verdict, when it is not ``agree``) and three findings in the shared
   shape, so an agent can act on it.
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
9. **The per-gene evidence is kept.** The original's second return value is a
   dotplot of each panel gene across donors, which is what lets a curator see
   that a call rests on one gene. Returning only the ratio dropped that, and
   the ratio alone cannot distinguish a real contradiction from a gametolog
   cross-mapping (#707). Each row carries its per-gene counts, and
   ``panel_summary`` carries each gene's separation across the file.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

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
from .qc import DEFAULT_CHUNK_NNZ, SAMPLE_ID_LIMIT, finding, iter_matrix_chunks, open_count_matrix, run_read_check

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
# Every verdict, in the precedence order ``_verdict`` applies them; ``verdict_counts`` keys on this.
VERDICTS = (
    VERDICT_NOT_APPLICABLE,
    VERDICT_BELOW_FLOOR,
    VERDICT_INDETERMINATE,
    VERDICT_FILL_IN,
    VERDICT_AGREE,
    VERDICT_CONTRADICTION,
)


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
        ``female`` symbol lists), ``verdict_counts``, ``panel_summary``,
        ``donors``, and ``findings``.

        ``verdict_counts`` maps every verdict below to the number of donor
        rows that received it (zero included), so its values sum to the
        number of rows evaluated; every value is zero when ``gene_panel``
        is ``not_applicable``. One row is evaluated per donor — two when a
        donor has both droplet and plate-based libraries, the plate-based
        row's ``donor_id`` suffixed ``-smartseq`` and its ``smart_seq`` flag
        set (the suffixed row is dropped only when that would collide with a
        donor literally so named, which is then refused).

        ``donors`` carries only the rows whose verdict is not ``agree``, at
        most 20 per verdict in donor order (#700): an atlas with hundreds of
        agreeing donors would otherwise return a table that fits no tool
        result, and ``verdict_counts`` holds the totals, so cite it rather
        than the table's length. A split donor's agreeing chemistry row is
        omitted like any other ``agree`` row. Each row: ``donor_id``, ``smart_seq``,
        ``cells``, ``male_counts``, ``female_counts``, ``total_counts``,
        ``ratio`` (``null`` when the female sum is zero), ``inferred``,
        ``annotated`` (``male`` / ``female`` / ``unknown``),
        ``annotated_term`` (the obs value verbatim, ``null`` when the column
        is absent), ``verdict``, and the per-gene evidence: ``per_gene`` (one
        entry per panel gene present — ``symbol``, ``panel``, ``counts``,
        ``per_cell``), ``xist_counts`` and ``xist_per_cell`` (``null`` when
        ``XIST`` is absent from var), and ``male_dominant_gene`` with
        ``male_dominant_share``, the male-panel gene carrying the largest
        share of the male sum and that share (both ``null`` when the male sum
        is zero). Verdicts, in precedence order:

        - ``not_applicable`` — the donor is not human
        - ``below_floor`` — fewer than 100 counts across both gene sets
        - ``indeterminate`` — ratio between 0.05 and 0.35, inclusive
        - ``fill_in`` — annotated ``unknown`` (or absent) but the ratio is clear
        - ``agree`` / ``contradiction`` — the ratio's call against the annotation

        ``panel_summary`` has one entry per panel gene present —
        ``gene_id``, ``symbol``, ``panel``, ``mean_per_cell_annotated_male``,
        ``mean_per_cell_annotated_female``, and their ratio as ``separation``
        (``null`` when the female mean is zero or either side has no donors).
        It is keyed on the *annotated* sex, so it says how well each gene
        actually separates the sexes **in this file**: a male-panel gene that
        discriminates separates them by orders of magnitude, and one that has
        stopped — as four of the seven do on intron-inclusive remaps, where
        gametolog homology misassigns reads between the X and Y copies —
        sits near or below 1. Empty when ``gene_panel`` is ``not_applicable``.
        A contradiction should be read against it before it is relayed (#707).

        Findings, each counting donors and naming them in ``sample_ids``:
        ``sex_contradiction``, ``sex_fillable``, ``sex_below_floor``. Empty
        findings with ``gene_panel.status == "applied"`` means every callable
        donor agrees with its annotation.

        Refused by name, since each is a defect another check owns and a
        call over it would be against an arbitrary value: a donor carrying
        two annotated sexes or two organisms (#680), a missing or unknown
        term in ``sex_ontology_term_id``, a missing term or absent column
        for ``organism_ontology_term_id`` (the schema requires it), a
        ``donor_id`` that collides with another donor's ``-smartseq`` row,
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
        male_cols, male_found, male_ids = _locate(var_ids, MALE_GENES)
        female_cols, female_found, female_ids = _locate(var_ids, FEMALE_GENES)
        result["genes_found"] = {"male": male_found, "female": female_found}
        if (reason := _not_applicable_reason(cm, male_found, female_found)) is not None:
            result["gene_panel"] = {"status": VERDICT_NOT_APPLICABLE, "reason": reason}
            result.update(verdict_counts=dict.fromkeys(VERDICTS, 0), panel_summary=[], donors=[], findings=[])
            return result
        result["gene_panel"] = {"status": "applied"}
        panel = {var_ids[c] for c in (*male_cols, *female_cols)}
        if duplicated := check_duplicate_ids([v for v in var_ids if v in panel], f"{cm.var_key} panel genes"):
            raise Refusal(f"a sex-panel gene is listed twice, so its column is ambiguous: {duplicated}")
        obs = read_group(f, "obs")
        # The anndata gate refuses an obs that is not a dataframe group (a compound
        # dataset fails its own read), so this narrows for pyright only.
        assert obs is not None
        if "donor_id" not in obs:
            raise Refusal("obs has no donor_id column, so counts cannot be grouped by donor")
        donor = read_key_column(obs, "donor_id", "obs column")
        annotated = _obs_column(obs, "sex_ontology_term_id")
        assay = _obs_column(obs, "assay_ontology_term_id")
        if "organism_ontology_term_id" not in obs:
            raise Refusal("obs has no organism_ontology_term_id column, so the panel cannot be known to apply")
        organism = _obs_column(obs, "organism_ontology_term_id")
        # Grouped before the matrix is touched, so every per-donor refusal is
        # raised without streaming a 20 GB object first.
        grouping = _donor_grouping(donor, annotated, assay, organism)
        per_gene = _sum_panel_genes(f, cm.key, cm.format, male_cols, female_cols, chunk_nnz, grouping)

    panel_genes = _panel_genes(male_ids, male_found, female_ids, female_found)
    rows = _donor_rows(grouping, per_gene, panel_genes, len(male_cols))
    tally = Counter(r["verdict"] for r in rows)
    result["verdict_counts"] = {v: tally[v] for v in VERDICTS}
    result["panel_summary"] = _panel_summary(rows, panel_genes)
    result["donors"] = _listed_rows(rows)
    result["findings"] = _findings(rows, cm.key)
    return result


def _listed_rows(rows: list[dict]) -> list[dict]:
    """The rows a reader needs: never ``agree``, and at most SAMPLE_ID_LIMIT per verdict, in donor order.

    A few hundred rows overflow a tool result (#700); ``verdict_counts`` carries the totals.
    """
    seen: Counter[str] = Counter()
    listed = []
    for row in rows:
        if row["verdict"] == VERDICT_AGREE:
            continue
        seen[row["verdict"]] += 1
        if seen[row["verdict"]] <= SAMPLE_ID_LIMIT:
            listed.append(row)
    return listed


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


def _locate(var_ids: list[str], genes: dict[str, str]) -> tuple[list[int], list[str], list[str]]:
    """Column positions, symbols, and Ensembl IDs of the genes present, in the panel's order."""
    position = {eid: i for i, eid in enumerate(var_ids)}
    found = [(position[eid], symbol, eid) for eid, symbol in genes.items() if eid in position]
    return [col for col, _, _ in found], [symbol for _, symbol, _ in found], [eid for _, _, eid in found]


def _obs_column(obs: h5py.Group, name: str) -> np.ndarray | None:
    """A per-cell obs column as objects (missing values kept as NA), or None when absent.

    The anndata gate has already refused a column whose length differs from obs.
    """
    if name not in obs:
        return None
    return np.asarray(read_element(obs[name]), dtype=object)


@dataclass(frozen=True)
class _Grouping:
    """Cells grouped into one row per (donor, chemistry), with the per-donor values each row is judged against.

    ``key`` maps each cell to its row, so the matrix pass can accumulate
    straight into row order; ``n_keys`` is ``2 * len(donors)`` because every
    donor reserves a droplet and a plate-based row, and the empty ones are
    dropped when rows are built.
    """

    key: np.ndarray
    n_keys: int
    donors: np.ndarray | pd.Index
    sex_term: list
    organism_term: list


def _donor_grouping(
    donor: np.ndarray, annotated: np.ndarray | None, assay: np.ndarray | None, organism: np.ndarray | None
) -> _Grouping:
    """Group cells by (donor, chemistry) and settle every per-donor refusal.

    Done before the matrix is read so that a donor carrying two annotated
    sexes, two organisms, or a name that collides with a ``-smartseq`` row is
    refused without first streaming the matrix.
    """
    donor_codes, donors = pd.factorize(pd.Series(donor).astype(str), sort=True)
    smart = np.zeros(len(donor), dtype=bool)
    if assay is not None:
        smart = pd.Series(assay).isin(SMART_SEQ_ASSAYS).to_numpy()
    sex_term = _per_donor_value(donor_codes, donors, annotated, "sex_ontology_term_id")
    organism_term = _per_donor_value(donor_codes, donors, organism, "organism_ontology_term_id")
    _refuse_suffix_collisions(donors, smart, donor_codes)
    return _Grouping(
        key=(donor_codes * 2 + smart).astype(np.intp),  # (donor, chemistry) -> one integer per row
        n_keys=len(donors) * 2,
        donors=donors,
        sex_term=sex_term,
        organism_term=organism_term,
    )


def _sum_panel_genes(
    f: h5py.File, key: str, fmt: str, male_cols: list[int], female_cols: list[int], chunk_nnz: int, grouping: _Grouping
) -> np.ndarray:
    """Count sums per (donor row, panel gene), as an ``n_keys`` x 17 array.

    CSC stores columns contiguously, so each of the 17 panel columns is
    read on its own through anndata's backed class and folded into the
    accumulator: peak memory is one column plus the accumulator, and the
    other 30,000 columns are never touched. CSR and dense need every stored
    entry once to find the hits, so they stream through
    :func:`qc.iter_matrix_chunks`; that pass is the cost of the check.

    Accumulating per gene rather than folding straight into two panel totals
    is what lets a reader see which genes carry a donor's signal (#707), and
    it costs nothing: the accumulator is sized by donors, not by cells, so it
    replaces two per-cell vectors with an array that does not grow with the
    file. The male and female panels are still read as separate blocks, so a
    NaN or negative count is refused against the panel it belongs to.
    """
    panels = (("male", np.asarray(male_cols)), ("female", np.asarray(female_cols)))
    acc = np.zeros((grouping.n_keys, len(male_cols) + len(female_cols)), dtype=np.float64)
    if fmt == "csc":
        ds = sparse_dataset(f[key])  # pyright: ignore[reportArgumentType]
        j = 0
        for panel, cols in panels:
            for col in cols:
                column = ds[:, int(col) : int(col) + 1]
                _refuse_uncountable(column.data, panel)
                acc[:, j] += np.bincount(grouping.key[column.indices], weights=column.data, minlength=grouping.n_keys)
                j += 1
        return acc
    for chunk in iter_matrix_chunks(f, key, chunk_nnz, axis="row"):
        n_rows = chunk.matrix.get_shape()[0]
        keys = grouping.key[chunk.start : chunk.start + n_rows]
        offset = 0
        for panel, cols in panels:
            block = chunk.matrix[:, cols]
            _refuse_uncountable(block.data, panel)
            coo = block.tocoo()
            # (row, gene) pairs flattened into a single index so one bincount
            # scatters the whole block; the accumulator is reshaped back after.
            flat = keys[coo.row] * len(cols) + coo.col
            acc[:, offset : offset + len(cols)] += np.bincount(
                flat, weights=coo.data, minlength=grouping.n_keys * len(cols)
            ).reshape(grouping.n_keys, len(cols))
            offset += len(cols)
    return acc


def _panel_genes(
    male_ids: list[str], male_found: list[str], female_ids: list[str], female_found: list[str]
) -> list[dict]:
    """The panel genes present, in accumulator column order: male panel then female."""
    return [
        {"gene_id": eid, "symbol": symbol, "panel": panel}
        for panel, ids, symbols in (("male", male_ids, male_found), ("female", female_ids, female_found))
        for eid, symbol in zip(ids, symbols, strict=True)
    ]


def _donor_rows(grouping: _Grouping, per_gene: np.ndarray, panel_genes: list[dict], n_male: int) -> list[dict]:
    """One row per (donor, chemistry), from the per-gene sums the matrix pass accumulated."""
    cells = np.bincount(grouping.key, minlength=grouping.n_keys)
    male_sum = per_gene[:, :n_male].sum(axis=1)
    female_sum = per_gene[:, n_male:].sum(axis=1)

    rows: list[dict] = []
    for k in np.flatnonzero(cells):
        d, is_smart = divmod(int(k), 2)
        total = float(male_sum[k] + female_sum[k])
        ratio = float(male_sum[k] / female_sum[k]) if female_sum[k] > 0 else None
        inferred = _assign_sex(ratio) if total >= COUNT_FLOOR else None
        annotated_sex = _annotated_sex(grouping.sex_term[d], grouping.donors[d])
        gene_rows = _per_gene_rows(per_gene[k], panel_genes, int(cells[k]))
        dominant_gene, dominant_share = _male_dominance(gene_rows[:n_male], float(male_sum[k]))
        xist = next((g for g in gene_rows if g["symbol"] == "XIST"), None)
        rows.append(
            {
                "donor_id": f"{grouping.donors[d]}{SMART_SEQ_SUFFIX}" if is_smart else str(grouping.donors[d]),
                "smart_seq": bool(is_smart),
                "cells": int(cells[k]),
                "male_counts": float(male_sum[k]),
                "female_counts": float(female_sum[k]),
                "total_counts": total,
                "ratio": ratio,
                "inferred": inferred,
                "annotated": annotated_sex,
                "annotated_term": grouping.sex_term[d],
                "verdict": _verdict(_is_human(grouping.organism_term[d], grouping.donors[d]), inferred, annotated_sex),
                "xist_counts": xist["counts"] if xist else None,
                "xist_per_cell": xist["per_cell"] if xist else None,
                "male_dominant_gene": dominant_gene,
                "male_dominant_share": dominant_share,
                "per_gene": gene_rows,
            }
        )
    return rows


def _per_gene_rows(sums: np.ndarray, panel_genes: list[dict], n_cells: int) -> list[dict]:
    """Each panel gene's counts for one row, as a sum and as a per-cell mean.

    Both, because they answer different questions: the sum is what the ratio
    and the 100-count floor are expressed in, and the per-cell mean is what
    makes one donor comparable with another.
    """
    return [
        {"symbol": g["symbol"], "panel": g["panel"], "counts": float(s), "per_cell": float(s) / n_cells}
        for g, s in zip(panel_genes, sums, strict=True)
    ]


def _male_dominance(male_genes: list[dict], male_sum: float) -> tuple[str | None, float | None]:
    """The male-panel gene carrying the largest share of the male sum, and that share.

    A male call resting on a single gene is the signature of gametolog
    cross-mapping (#707): all seven Y-linked genes have an X copy, homology
    runs through the introns, and on intron-inclusive counting four of them
    stop discriminating. On the file that prompted #707, ``ZFY`` alone carried
    61% of a female donor's male signal. Reported, never acted on: which genes
    are trustworthy is a property of how the file was aligned, not of the tool.
    """
    if male_sum <= 0:
        return None, None
    top = max(male_genes, key=lambda g: g["counts"])
    return top["symbol"], top["counts"] / male_sum


def _panel_summary(rows: list[dict], panel_genes: list[dict]) -> list[dict]:
    """Each panel gene's mean per-cell count in donors annotated male against donors annotated female.

    Split on the *annotated* sex rather than the inferred one. The inference is
    the thing in question, and on the file that prompted #707 every donor
    inferred male, so an inferred split would have shown nothing. Against the
    annotation, a male-panel gene that still discriminates separates the two by
    orders of magnitude and one that has stopped sits near or below 1 — which
    is the whole diagnosis, and it needs no threshold tuned to any dataset.

    Means are weighted by cells, so a donor contributes in proportion to what it
    actually measured. Donors annotated ``unknown``, and non-human donors whose
    panel does not apply, are in neither column.
    """
    totals = {}
    for sex in ("male", "female"):
        subset = [r for r in rows if r["annotated"] == sex and r["verdict"] != VERDICT_NOT_APPLICABLE]
        cells = sum(r["cells"] for r in subset)
        totals[sex] = (cells, [sum(r["per_gene"][j]["counts"] for r in subset) for j in range(len(panel_genes))])

    summary = []
    for j, gene in enumerate(panel_genes):
        means = {sex: (total[j] / cells if cells else None) for sex, (cells, total) in totals.items()}
        male_mean, female_mean = means["male"], means["female"]
        summary.append(
            {
                **gene,
                "mean_per_cell_annotated_male": male_mean,
                "mean_per_cell_annotated_female": female_mean,
                "separation": (male_mean / female_mean) if male_mean is not None and female_mean else None,
            }
        )
    return summary


def _refuse_suffix_collisions(donors, smart: np.ndarray, donor_codes: np.ndarray) -> None:
    """A plate-based row is named ``<donor>-smartseq``; refuse when a donor is literally so named.

    Rows are keyed on (donor, chemistry), so the check itself is unambiguous;
    the display ID and the finding's ``sample_ids`` would not be.
    """
    plate_donors = {str(donors[d]) for d in np.unique(donor_codes[smart])}
    collisions = sorted(name for name in plate_donors if f"{name}{SMART_SEQ_SUFFIX}" in set(map(str, donors)))
    if collisions:
        raise Refusal(
            f"donor(s) {collisions} have plate-based libraries, and a donor named "
            f"'<donor>{SMART_SEQ_SUFFIX}' also exists, so the split rows cannot be told apart"
        )


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
    assert term is not None, "the organism column's absence is refused before grouping"
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
