"""Tests for the donor sex check (#678).

Fixtures are built from a dense matrix whose var index carries the real
Ensembl IDs of Lattice's 17 genes plus fillers, written through anndata's
own writer (``testing.write_matrix_h5ad``) and converted to the format under
test — never through the readers under test (contract, principle 17). Each
defect fixture is the clean two-donor base plus one change.
"""

from __future__ import annotations

import json

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pytest

from hca_anndata_tools.donor_sex import (
    COUNT_FLOOR,
    FEMALE_GENES,
    FEMALE_RATIO,
    MALE_GENES,
    MALE_RATIO,
    SMART_SEQ_ASSAYS,
    VERDICTS,
    _assign_sex,
    _verdict,
    check_donor_sex,
)
from hca_anndata_tools.qc import SAMPLE_ID_LIMIT
from hca_anndata_tools.testing import (
    MATRIX_FORMATS,
    make_plain_string_column,
    write_h5ad_with_nullable_strings,
    write_matrix_h5ad,
)

MALE_IDS = list(MALE_GENES)
FEMALE_IDS = list(FEMALE_GENES)
FILLERS = ["ENSG00000000003", "ENSG00000000005", "ENSG00000000419"]
VAR = MALE_IDS + FEMALE_IDS + FILLERS  # 7 + 10 + 3 = 20 genes
MALE, FEMALE = "PATO:0000384", "PATO:0000383"
HUMAN = "NCBITaxon:9606"
DROPLET = "EFO:0009922"
SMART = min(SMART_SEQ_ASSAYS)
OBS_COLUMNS = ("donor_id", "sex_ontology_term_id", "assay_ontology_term_id", "organism_ontology_term_id")


def _donor(male_per_gene, female_per_gene, *, donor="d", sex=MALE, n=4, assay=DROPLET, organism=HUMAN, filler=3.0):
    """``n`` cells of one donor; each male gene holds ``male_per_gene`` counts, each female gene ``female_per_gene``."""
    cells = np.zeros((n, len(VAR)), dtype=np.float32)
    cells[:, : len(MALE_IDS)] = male_per_gene
    cells[:, len(MALE_IDS) : len(MALE_IDS) + len(FEMALE_IDS)] = female_per_gene
    cells[:, -len(FILLERS) :] = filler
    return cells, (donor, sex, assay, organism)


def _male(**kw):
    return _donor(10, 10, **{"donor": "m1", "sex": MALE, **kw})  # 70 / 100 per cell → ratio 0.7


def _female(**kw):
    return _donor(0, 20, **{"donor": "f1", "sex": FEMALE, **kw})  # 0 / 200 per cell → ratio 0


def _write(path, donors, fmt="csr", *, var=None, as_raw=False):
    X = np.vstack([cells for cells, _ in donors])
    sizes = [len(cells) for cells, _ in donors]
    obs = pd.DataFrame(
        {col: pd.Categorical(np.repeat([meta[i] for _, meta in donors], sizes)) for i, col in enumerate(OBS_COLUMNS)},
        index=[f"c{i}" for i in range(X.shape[0])],  # pyright: ignore[reportArgumentType]
    )
    return write_matrix_h5ad(
        path, np.log1p(X) if as_raw else X, fmt, raw=X if as_raw else None, obs=obs, var_index=var or VAR
    )


def _drop_obs_column(path, name):
    adata = ad.read_h5ad(path)
    del adata.obs[name]
    adata.write_h5ad(path)
    return path


def _rows(result):
    assert "error" not in result, result
    return {r["donor_id"]: r for r in result["donors"]}


def _codes(result):
    return {f["code"]: f for f in result["findings"]}


def _counts(**verdicts):
    """The full ``verdict_counts`` map: every verdict present, zero unless named."""
    return {v: verdicts.get(v, 0) for v in VERDICTS}


@pytest.mark.parametrize("fmt", MATRIX_FORMATS)
def test_clean_two_donors_agree(tmp_path, fmt):
    result = check_donor_sex(_write(tmp_path / "a.h5ad", [_male(), _female()], fmt))
    assert result["gene_panel"] == {"status": "applied"}
    assert result["genes_found"] == {"male": list(MALE_GENES.values()), "female": list(FEMALE_GENES.values())}
    assert result["verdict_counts"] == _counts(agree=2)
    assert result["donors"] == []  # agreeing donors are counted, never listed (#700)
    assert result["integer_check"]["status"] == "applied"
    assert result["findings"] == []
    json.dumps(result)  # every value is a native type


def test_raw_x_is_the_matrix_when_present(tmp_path):
    # m1 is annotated female so its row is a contradiction and stays listed; agreeing rows are not (#700).
    result = check_donor_sex(_write(tmp_path / "a.h5ad", [_male(sex=FEMALE), _female()], as_raw=True))
    assert result["matrix"] == "raw/X"
    assert _rows(result)["m1"]["male_counts"] == 280.0  # counts, not the log1p X


def test_male_annotated_with_no_y_expression_is_a_contradiction(tmp_path):
    result = check_donor_sex(_write(tmp_path / "a.h5ad", [_female(sex=MALE)]))
    assert result["donors"] == [
        {
            "donor_id": "f1",
            "smart_seq": False,
            "cells": 4,
            "male_counts": 0.0,
            "female_counts": 800.0,
            "total_counts": 800.0,
            "ratio": 0.0,
            "inferred": "female",
            "annotated": "male",
            "annotated_term": MALE,
            "verdict": "contradiction",
        }
    ]
    assert result["verdict_counts"] == _counts(contradiction=1)
    assert _codes(result)["sex_contradiction"]["sample_ids"] == ["f1"]
    json.dumps(result)  # every value is a native type


def test_female_annotated_with_male_ratio_is_a_contradiction(tmp_path):
    assert _rows(check_donor_sex(_write(tmp_path / "a.h5ad", [_male(sex=FEMALE)])))["m1"]["verdict"] == "contradiction"


def test_zero_female_counts_is_male_with_null_ratio(tmp_path):
    # Lattice divides by zero to +inf and calls it male; the ratio is reported as null. Annotated
    # female so the row is a contradiction and stays listed; an agreeing row is not (#700).
    row = _rows(check_donor_sex(_write(tmp_path / "a.h5ad", [_donor(20, 0, n=3, sex=FEMALE)])))["d"]
    assert (row["ratio"], row["inferred"], row["verdict"]) == (None, "male", "contradiction")


def test_annotated_unknown_but_inferable_is_fill_in(tmp_path):
    result = check_donor_sex(_write(tmp_path / "a.h5ad", [_male(sex="unknown")]))
    assert _rows(result)["m1"]["verdict"] == "fill_in"
    assert _codes(result)["sex_fillable"]["sample_ids"] == ["m1"]


def test_absent_sex_column_reads_as_unknown(tmp_path):
    path = _drop_obs_column(_write(tmp_path / "a.h5ad", [_male()]), "sex_ontology_term_id")
    row = _rows(check_donor_sex(path))["m1"]
    assert (row["annotated"], row["annotated_term"], row["verdict"]) == ("unknown", None, "fill_in")


@pytest.mark.parametrize("term", ["female", "PATO:0001340", "na", ""])
def test_sex_term_outside_the_vocabulary_is_refused_by_name(tmp_path, term):
    # A label or stray term in a controlled column is a schema defect, not an unknown.
    result = check_donor_sex(_write(tmp_path / "a.h5ad", [_male(sex=term)]))
    assert "error" in result and f"donor 'm1' has sex_ontology_term_id {term!r}" in result["error"], result


def test_missing_sex_term_is_refused_not_read_as_unknown(tmp_path):
    path = _write(tmp_path / "a.h5ad", [_male()])
    adata = ad.read_h5ad(path)
    adata.obs["sex_ontology_term_id"] = pd.Categorical([MALE, MALE, None, None])
    adata.write_h5ad(path)
    result = check_donor_sex(path)
    assert "error" in result and "sex_ontology_term_id'] has 2 missing value" in result["error"], result


def test_normalized_only_x_is_not_applicable(tmp_path):
    # No raw, and X classifies as normalized: the sums would be log values, not counts.
    X = np.vstack([cells for cells, _ in [_male(), _female()]])
    normalized = np.log1p(X / X.sum(axis=1, keepdims=True) * 1e4).astype(np.float32)
    path = _write(tmp_path / "a.h5ad", [(normalized[:4], _male()[1]), (normalized[4:], _female()[1])])
    result = check_donor_sex(path)
    assert "error" not in result, result
    assert result["integer_check"]["status"] == "not_applicable"
    assert result["gene_panel"]["status"] == "not_applicable" and "not counts" in result["gene_panel"]["reason"]
    assert result["verdict_counts"] == _counts() and result["donors"] == [] and result["findings"] == []


def test_below_floor(tmp_path):
    result = check_donor_sex(_write(tmp_path / "a.h5ad", [_donor(1, 1, n=2)]))  # 17 per cell, 34 total
    row = _rows(result)["d"]
    assert row["total_counts"] == 34.0 < COUNT_FLOOR
    assert (row["inferred"], row["verdict"]) == (None, "below_floor")
    assert _codes(result)["sex_below_floor"]["sample_ids"] == ["d"]


def test_exactly_the_floor_is_called(tmp_path):
    # 100 counts: 7 male genes x 10 + 10 female genes x 3 = 70 + 30, one cell. Annotated unknown so
    # the row is a fill_in and stays listed; an agreeing row is not (#700).
    row = _rows(check_donor_sex(_write(tmp_path / "a.h5ad", [_donor(10, 3, n=1, sex="unknown")])))["d"]
    assert row["total_counts"] == COUNT_FLOOR == 100.0
    assert (row["inferred"], row["verdict"]) == ("male", "fill_in")


def test_ratio_between_the_cuts_is_indeterminate(tmp_path):
    row = _rows(check_donor_sex(_write(tmp_path / "a.h5ad", [_donor(10, 35)])))["d"]  # 70 / 350 = 0.2
    assert (row["ratio"], row["inferred"], row["verdict"]) == (0.2, "unknown", "indeterminate")


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [
        (MALE_RATIO + 0.001, "male"),
        (MALE_RATIO, "unknown"),
        (MALE_RATIO - 0.001, "unknown"),
        (FEMALE_RATIO + 0.001, "unknown"),
        (FEMALE_RATIO, "unknown"),
        (FEMALE_RATIO - 0.001, "female"),
        (None, "male"),
    ],
)
def test_assign_sex_at_the_cuts(ratio, expected):
    # Lattice's cuts are strict on both sides: > 0.35 male, < 0.05 female.
    assert _assign_sex(ratio) == expected


def test_donor_with_droplet_and_smart_seq_libraries_is_two_rows(tmp_path):
    # The droplet half is indeterminate (70 / 350 = 0.2) rather than agreeing, so both rows stay listed.
    donors = [_donor(10, 35, donor="d", assay=DROPLET), _female(donor="d", sex=MALE, assay=SMART)]
    result = check_donor_sex(_write(tmp_path / "a.h5ad", donors))
    assert result["verdict_counts"] == _counts(indeterminate=1, contradiction=1)  # counts rows, not donor names
    assert {k: (v["smart_seq"], v["verdict"]) for k, v in _rows(result).items()} == {
        "d": (False, "indeterminate"),
        "d-smartseq": (True, "contradiction"),
    }


def test_two_sexes_across_chemistries_is_still_refused(tmp_path):
    # The consistency check runs on the donor, not on the (donor, chemistry) row.
    donors = [_male(donor="d", sex=MALE, assay=DROPLET), _male(donor="d", sex=FEMALE, assay=SMART)]
    result = check_donor_sex(_write(tmp_path / "a.h5ad", donors))
    assert "error" in result and "donor 'd' carries several sex_ontology_term_id values" in result["error"], result


def test_donor_named_like_a_suffixed_key_is_refused_by_name(tmp_path):
    # Grouping is on (donor, chemistry), but the display ID and findings would not tell the plate
    # row of "X" from the droplet donor literally named "X-smartseq".
    donors = [_male(donor="X-smartseq", assay=DROPLET), _female(donor="X", assay=SMART)]
    result = check_donor_sex(_write(tmp_path / "a.h5ad", donors))
    assert "error" in result and "['X'] have plate-based libraries" in result["error"], result


def test_suffixed_name_without_a_plate_donor_is_fine(tmp_path):
    donors = [_male(donor="X-smartseq", assay=DROPLET), _female(donor="X", assay=DROPLET)]
    result = check_donor_sex(_write(tmp_path / "a.h5ad", donors))
    assert result["verdict_counts"] == _counts(agree=2) and _rows(result) == {}


def test_absent_organism_column_is_refused_by_name(tmp_path):
    result = check_donor_sex(_drop_obs_column(_write(tmp_path / "a.h5ad", [_male()]), "organism_ontology_term_id"))
    assert "error" in result and "no organism_ontology_term_id column" in result["error"], result


def test_donor_with_two_organisms_is_refused_by_name(tmp_path):
    donors = [_male(donor="d"), _male(donor="d", organism="NCBITaxon:10090")]
    result = check_donor_sex(_write(tmp_path / "a.h5ad", donors))
    assert "error" in result and "donor 'd' carries several organism_ontology_term_id values" in result["error"]


def test_non_human_donor_is_not_applicable(tmp_path):
    donors = [_male(), _male(donor="mouse", organism="NCBITaxon:10090")]
    result = check_donor_sex(_write(tmp_path / "a.h5ad", donors))
    assert result["verdict_counts"] == _counts(agree=1, not_applicable=1)
    assert {k: v["verdict"] for k, v in _rows(result).items()} == {"mouse": "not_applicable"}


def test_var_missing_every_male_gene_is_not_applicable(tmp_path):
    var = [f"ENSG0000099999{i}" for i in range(7)] + FEMALE_IDS + FILLERS  # male slots renamed to fillers
    result = check_donor_sex(_write(tmp_path / "a.h5ad", [_male(), _female()], var=var))
    assert "error" not in result
    assert result["gene_panel"]["status"] == "not_applicable"
    assert "ZFY" in result["gene_panel"]["reason"] and "PUDP" not in result["gene_panel"]["reason"]
    assert result["genes_found"] == {"male": [], "female": list(FEMALE_GENES.values())}
    assert result["verdict_counts"] == _counts() and result["donors"] == [] and result["findings"] == []


def test_panel_gene_listed_twice_is_refused_by_name(tmp_path):
    var = VAR[:-1] + [MALE_IDS[0]]  # ZFY appears at column 0 and again at the last column
    result = check_donor_sex(_write(tmp_path / "a.h5ad", [_male(), _female()], var=var))
    assert "error" in result and "listed twice" in result["error"] and MALE_IDS[0] in result["error"], result


@pytest.mark.parametrize("bad", [np.nan, -2.0])
def test_nan_or_negative_panel_count_is_refused_by_name(tmp_path, bad):
    # raw.X is counts by assertion (the classifier does not run on it), so a defect there is
    # refused rather than summed; on a lone X the classifier would call it not counts first.
    cells, meta = _male()
    cells[0, 0] = bad  # ZFY in the first cell
    result = check_donor_sex(_write(tmp_path / "a.h5ad", [(cells, meta)], as_raw=True))
    assert "error" in result and "male-gene count is" in result["error"] and "1 stored value" in result["error"], result


def test_lone_x_with_a_nan_is_not_counts(tmp_path):
    cells, meta = _male()
    cells[0, 0] = np.nan
    result = check_donor_sex(_write(tmp_path / "a.h5ad", [(cells, meta)]))
    assert "error" not in result and result["gene_panel"]["status"] == "not_applicable", result


def test_ensembl_version_suffixes_are_ignored(tmp_path):
    var = [f"{g}.{i + 1}" for i, g in enumerate(VAR)]
    result = check_donor_sex(_write(tmp_path / "a.h5ad", [_male(), _female()], var=var))
    assert result["gene_panel"] == {"status": "applied"}
    assert result["verdict_counts"] == _counts(agree=2) and _rows(result) == {}


def test_verdicts_lists_every_verdict_the_check_can_give():
    # `verdict_counts` keys on VERDICTS, so a verdict `_verdict` can return but VERDICTS lacks would
    # vanish from the map and break "values sum to rows evaluated".
    produced = {
        _verdict(human, inferred, annotated)
        for human in (True, False)
        for inferred in (None, "unknown", "male", "female")
        for annotated in ("unknown", "male", "female")
    }
    assert produced == set(VERDICTS) and len(VERDICTS) == len(set(VERDICTS))


def test_agreeing_donors_are_counted_not_listed(tmp_path):
    # More agreeing donors than any sample list carries (#700): a 300-donor atlas must fit in one
    # tool result, so `donors` holds only the rows that need a reader, and `verdict_counts` holds
    # the totals — per row, so a donor's plate-based split counts twice, like the table it stands for.
    agreeing = [_male(donor=f"a{i:02d}") for i in range(SAMPLE_ID_LIMIT + 5)]
    donors = [*agreeing, _male(donor="a00", assay=SMART), _female(donor="c", sex=MALE), _male(donor="u", sex="unknown")]
    result = check_donor_sex(_write(tmp_path / "a.h5ad", donors))
    assert "error" not in result, result
    assert result["verdict_counts"] == _counts(agree=len(agreeing) + 1, contradiction=1, fill_in=1)
    assert sum(result["verdict_counts"].values()) == len(donors)
    assert [(r["donor_id"], r["verdict"]) for r in result["donors"]] == [("c", "contradiction"), ("u", "fill_in")]
    assert _codes(result).keys() == {"sex_contradiction", "sex_fillable"}


def test_each_listed_verdict_is_capped_at_the_sample_limit(tmp_path):
    # Any verdict can dominate an atlas (every donor of a pre-curation source is `fill_in` when the sex
    # column is missing), so each one lists at most SAMPLE_ID_LIMIT rows, in donor order, and
    # `verdict_counts` holds the total the reader cites.
    fillable = [_male(donor=f"u{i:02d}", sex="unknown") for i in range(SAMPLE_ID_LIMIT + 5)]
    result = check_donor_sex(_write(tmp_path / "a.h5ad", [*fillable, _female(donor="c", sex=MALE)]))
    assert result["verdict_counts"] == _counts(fill_in=len(fillable), contradiction=1)
    assert [r["donor_id"] for r in result["donors"]] == ["c", *(f"u{i:02d}" for i in range(SAMPLE_ID_LIMIT))]
    assert _codes(result)["sex_fillable"]["count"] == len(fillable)


def test_csc_direct_read_matches_the_csr_pass(tmp_path):
    # CSC takes a separate code path (each panel column read on its own), so pin it against CSR
    # on a fixture with every verdict bucket a clean file can hold and the panel columns scattered
    # through var the way a real atlas has them.
    rng = np.random.default_rng(678)
    order = rng.permutation(len(VAR))
    var = [VAR[i] for i in order]
    donors = [_male(), _female(), _male(donor="u", sex="unknown"), _donor(1, 1, donor="low", n=2)]
    donors = [(cells[:, order], meta) for cells, meta in donors]
    csr = check_donor_sex(_write(tmp_path / "csr.h5ad", donors, "csr", var=var))
    csc = check_donor_sex(_write(tmp_path / "csc.h5ad", donors, "csc", var=var))
    assert csc["donors"] == csr["donors"] and csc["findings"] == csr["findings"]
    assert csc["verdict_counts"] == csr["verdict_counts"] == _counts(agree=2, fill_in=1, below_floor=1)
    assert _rows(csr)["u"]["male_counts"] == 280.0


@pytest.mark.parametrize("fmt", ["csr", "dense"])
def test_chunk_boundary_sums_a_donor_across_chunks(tmp_path, fmt):
    # 4 cells x 20 genes, every entry stored: 80 entries; chunk_nnz=30 forces several chunks
    # through one donor on the streaming formats. (CSC reads whole columns and ignores chunk_nnz.)
    # Annotated female so the row is a contradiction and stays listed; an agreeing row is not (#700).
    path = _write(tmp_path / f"{fmt}.h5ad", [_male(donor="d", sex=FEMALE)], fmt)
    whole = _rows(check_donor_sex(path))["d"]
    chunked = _rows(check_donor_sex(path, chunk_nnz=30))["d"]
    assert chunked == whole
    assert chunked["male_counts"] == 280.0


def test_donor_with_two_annotated_sexes_is_refused_by_name(tmp_path):
    result = check_donor_sex(_write(tmp_path / "a.h5ad", [_male(donor="d", sex=MALE), _male(donor="d", sex=FEMALE)]))
    assert "error" in result and "several sex_ontology_term_id values" in result["error"]


def test_missing_donor_id_is_refused_by_name(tmp_path):
    result = check_donor_sex(_drop_obs_column(_write(tmp_path / "a.h5ad", [_male()]), "donor_id"))
    assert "error" in result and "donor_id" in result["error"]


def test_raw_x_without_raw_var_is_refused_by_name(tmp_path):
    path = _write(tmp_path / "a.h5ad", [_male()], as_raw=True)
    with h5py.File(path, "r+") as f:
        del f["raw/var"]
    result = check_donor_sex(path)
    assert "error" in result and "raw/X is present but raw/var is not" in result["error"], result


def test_var_shorter_than_the_matrix_is_refused_by_name(tmp_path):
    # anndata's backed open does not check var against the matrix width (as open_count_matrix
    # notes for obs), so a shortened var would otherwise mis-locate the panel columns.
    path = _write(tmp_path / "a.h5ad", [_male()])
    with h5py.File(path, "r+") as f:
        var = f["var"]
        assert isinstance(var, h5py.Group)
        index = str(var.attrs["_index"])
        ids = [v.decode() for v in var[index][...][:-1]]  # pyright: ignore[reportIndexIssue]
        del var[index]
        make_plain_string_column(var, index, ids)
    result = check_donor_sex(path)
    assert "error" in result and "has 19 IDs but X has 20 columns" in result["error"], result


def test_masked_donor_id_is_refused_not_grouped(tmp_path):
    # A masked donor would otherwise become the literal donor "<NA>" (#637); the key column refuses it.
    path = _write(tmp_path / "a.h5ad", [_male(), _female()])
    adata = ad.read_h5ad(path)
    adata.obs["donor_id"] = pd.array(["m1", "m1", None, None, "f1", "f1", "f1", "f1"], dtype="string")
    write_h5ad_with_nullable_strings(adata, path)
    result = check_donor_sex(path)
    assert "error" in result and "obs column 'donor_id' has 2 missing value" in result["error"], result


def test_handler_refusals_reach_the_caller(tmp_path):
    path = _write(tmp_path / "a.h5ad", [_male()])
    assert "chunk_nnz must be a positive int" in check_donor_sex(path, chunk_nnz=0)["error"]
    assert "not found" in check_donor_sex(str(tmp_path / "nope.h5ad"))["error"].lower()
