"""Tests for the donor sex check (#678).

Fixtures are built from a dense matrix whose var index carries the real
Ensembl IDs of Lattice's 17 genes plus fillers, written through anndata's
own writer and converted to the format under test — never through the
readers under test (contract, principle 17). Each defect fixture is the
clean two-donor base plus one change.
"""

from __future__ import annotations

import anndata as ad
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp

from hca_anndata_tools.donor_sex import (
    COUNT_FLOOR,
    FEMALE_GENES,
    MALE_GENES,
    SMART_SEQ_ASSAYS,
    check_donor_sex,
)

FORMATS = ["csr", "csc", "dense"]
MALE_IDS = list(MALE_GENES)
FEMALE_IDS = list(FEMALE_GENES)
FILLERS = ["ENSG00000000003", "ENSG00000000005", "ENSG00000000419"]
VAR = MALE_IDS + FEMALE_IDS + FILLERS  # 7 + 10 + 3 = 20 genes
MALE, FEMALE = "PATO:0000384", "PATO:0000383"
DROPLET = "EFO:0009922"
SMART = next(iter(sorted(SMART_SEQ_ASSAYS)))


def _cells(n, male_per_gene, female_per_gene, filler=3.0):
    """``n`` cells whose male genes hold ``male_per_gene`` counts each, female genes ``female_per_gene``."""
    block = np.zeros((n, len(VAR)), dtype=np.float32)
    block[:, : len(MALE_IDS)] = male_per_gene
    block[:, len(MALE_IDS) : len(MALE_IDS) + len(FEMALE_IDS)] = female_per_gene
    block[:, -len(FILLERS) :] = filler
    return block


def _write(path, blocks, fmt="csr", *, var=None, as_raw=False):
    """``blocks``: list of (cells, donor, sex, assay, organism)."""
    X = np.vstack([b[0] for b in blocks])
    n = X.shape[0]
    obs = pd.DataFrame(
        {
            "donor_id": pd.Categorical([b[1] for b in blocks for _ in range(len(b[0]))]),
            "sex_ontology_term_id": pd.Categorical([b[2] for b in blocks for _ in range(len(b[0]))]),
            "assay_ontology_term_id": pd.Categorical([b[3] for b in blocks for _ in range(len(b[0]))]),
            "organism_ontology_term_id": pd.Categorical([b[4] for b in blocks for _ in range(len(b[0]))]),
        },
        index=[f"c{i}" for i in range(n)],  # pyright: ignore[reportArgumentType]
    )
    as_format = {"csr": sp.csr_matrix, "csc": sp.csc_matrix, "dense": np.asarray}
    var_index = var if var is not None else VAR
    adata = ad.AnnData(X=as_format[fmt](X), obs=obs, var=pd.DataFrame(index=var_index))  # pyright: ignore[reportArgumentType]
    if as_raw:
        adata.raw = adata
        adata.X = as_format[fmt](np.log1p(X))
    adata.write_h5ad(path)
    return path


def _male_donor(donor="m1", sex=MALE, n=4, assay=DROPLET, organism="NCBITaxon:9606"):
    return (_cells(n, male_per_gene=10, female_per_gene=10), donor, sex, assay, organism)  # ratio 0.7


def _female_donor(donor="f1", sex=FEMALE, n=4, assay=DROPLET, organism="NCBITaxon:9606"):
    return (_cells(n, male_per_gene=0, female_per_gene=20), donor, sex, assay, organism)  # ratio 0


def _rows(result):
    assert "error" not in result, result
    return {r["donor_id"]: r for r in result["donors"]}


def _codes(result):
    return {f["code"]: f for f in result["findings"]}


@pytest.mark.parametrize("fmt", FORMATS)
def test_clean_two_donors_agree(tmp_path, fmt):
    result = check_donor_sex(_write(tmp_path / "a.h5ad", [_male_donor(), _female_donor()], fmt))
    rows = _rows(result)
    assert result["status"] == {"status": "applied"}
    assert result["genes_found"] == {"male": list(MALE_GENES.values()), "female": list(FEMALE_GENES.values())}
    assert rows["m1"]["verdict"] == "agree" and rows["m1"]["inferred"] == "male" and rows["m1"]["ratio"] == 0.7
    assert rows["f1"]["verdict"] == "agree" and rows["f1"]["inferred"] == "female" and rows["f1"]["ratio"] == 0.0
    assert rows["m1"]["cells"] == 4 and rows["m1"]["male_counts"] == 280.0 and rows["m1"]["female_counts"] == 400.0
    assert result["findings"] == []


def test_raw_x_is_the_matrix_when_present(tmp_path):
    result = check_donor_sex(_write(tmp_path / "a.h5ad", [_male_donor(), _female_donor()], as_raw=True))
    assert result["matrix"] == "raw/X"
    assert _rows(result)["m1"]["male_counts"] == 280.0  # counts, not the log1p X


def test_male_annotated_with_no_y_expression_is_a_contradiction(tmp_path):
    result = check_donor_sex(_write(tmp_path / "a.h5ad", [_female_donor(donor="d", sex=MALE)]))
    rows = _rows(result)
    assert rows["d"]["inferred"] == "female" and rows["d"]["annotated"] == "male"
    assert rows["d"]["verdict"] == "contradiction"
    assert _codes(result)["sex_contradiction"]["sample_ids"] == ["d"]


def test_female_annotated_with_male_ratio_is_a_contradiction(tmp_path):
    result = check_donor_sex(_write(tmp_path / "a.h5ad", [_male_donor(donor="d", sex=FEMALE)]))
    assert _rows(result)["d"]["verdict"] == "contradiction"


def test_zero_female_counts_is_male_with_null_ratio(tmp_path):
    # Lattice divides by zero to +inf and calls it male; we report the ratio as null.
    block = (_cells(3, male_per_gene=20, female_per_gene=0), "d", MALE, DROPLET, "NCBITaxon:9606")
    row = _rows(check_donor_sex(_write(tmp_path / "a.h5ad", [block])))["d"]
    assert row["ratio"] is None and row["inferred"] == "male" and row["verdict"] == "agree"


def test_annotated_unknown_but_inferable_is_fill_in(tmp_path):
    result = check_donor_sex(_write(tmp_path / "a.h5ad", [_male_donor(donor="d", sex="unknown")]))
    assert _rows(result)["d"]["verdict"] == "fill_in"
    assert _codes(result)["sex_fillable"]["sample_ids"] == ["d"]


def test_absent_sex_column_reads_as_unknown(tmp_path):
    path = _write(tmp_path / "a.h5ad", [_male_donor(donor="d")])
    adata = ad.read_h5ad(path)
    del adata.obs["sex_ontology_term_id"]
    adata.write_h5ad(path)
    row = _rows(check_donor_sex(path))["d"]
    assert row["annotated"] == "unknown" and row["verdict"] == "fill_in"


def test_below_floor(tmp_path):
    block = (_cells(2, male_per_gene=1, female_per_gene=1), "d", MALE, DROPLET, "NCBITaxon:9606")  # 34 counts
    result = check_donor_sex(_write(tmp_path / "a.h5ad", [block]))
    row = _rows(result)["d"]
    assert row["total_counts"] == 34.0 < COUNT_FLOOR
    assert row["inferred"] is None and row["verdict"] == "below_floor"
    assert _codes(result)["sex_below_floor"]["sample_ids"] == ["d"]


def test_ratio_between_the_cuts_is_indeterminate(tmp_path):
    block = (_cells(4, male_per_gene=10, female_per_gene=35), "d", MALE, DROPLET, "NCBITaxon:9606")  # 70/350 = 0.2
    row = _rows(check_donor_sex(_write(tmp_path / "a.h5ad", [block])))["d"]
    assert row["ratio"] == 0.2 and row["inferred"] == "unknown" and row["verdict"] == "indeterminate"


def test_donor_with_droplet_and_smart_seq_libraries_is_two_rows(tmp_path):
    blocks = [_male_donor(donor="d", assay=DROPLET), _female_donor(donor="d", sex=MALE, assay=SMART)]
    rows = _rows(check_donor_sex(_write(tmp_path / "a.h5ad", blocks)))
    assert set(rows) == {"d", "d-smartseq"}
    assert rows["d"]["verdict"] == "agree"
    assert rows["d-smartseq"]["verdict"] == "contradiction"


def test_non_human_donor_is_not_applicable(tmp_path):
    blocks = [_male_donor(), _male_donor(donor="mouse", organism="NCBITaxon:10090")]
    rows = _rows(check_donor_sex(_write(tmp_path / "a.h5ad", blocks)))
    assert rows["m1"]["verdict"] == "agree" and rows["mouse"]["verdict"] == "not_applicable"


def test_var_missing_every_male_gene_is_not_applicable(tmp_path):
    var = [f"ENSG0000099999{i}" for i in range(7)] + FEMALE_IDS + FILLERS  # male slots renamed to fillers
    result = check_donor_sex(_write(tmp_path / "a.h5ad", [_male_donor(), _female_donor()], var=var))
    assert "error" not in result
    assert result["status"]["status"] == "not_applicable"
    assert "ZFY" in result["status"]["reason"] and "PUDP" not in result["status"]["reason"]
    assert result["genes_found"]["male"] == [] and len(result["genes_found"]["female"]) == 10
    assert result["donors"] == [] and result["findings"] == []


def test_ensembl_version_suffixes_are_ignored(tmp_path):
    var = [f"{g}.{i + 1}" for i, g in enumerate(VAR)]
    result = check_donor_sex(_write(tmp_path / "a.h5ad", [_male_donor(), _female_donor()], var=var))
    assert result["status"] == {"status": "applied"}
    assert _rows(result)["m1"]["verdict"] == "agree"


@pytest.mark.parametrize("fmt", ["csc", "dense"])
def test_other_formats_match_csr(tmp_path, fmt):
    blocks = [_male_donor(), _female_donor(), _male_donor(donor="u", sex="unknown")]
    csr = check_donor_sex(_write(tmp_path / "csr.h5ad", blocks, "csr"))
    other = check_donor_sex(_write(tmp_path / f"{fmt}.h5ad", blocks, fmt))
    assert other["donors"] == csr["donors"] and other["findings"] == csr["findings"]


def test_chunk_boundary_sums_a_donor_across_chunks(tmp_path):
    # 4 cells x 20 genes, every entry stored: 80 entries; chunk_nnz=30 forces several chunks
    # through one donor in every format.
    for fmt in FORMATS:
        path = _write(tmp_path / f"{fmt}.h5ad", [_male_donor(donor="d", n=4)], fmt)
        whole = _rows(check_donor_sex(path))["d"]
        chunked = _rows(check_donor_sex(path, chunk_nnz=30))["d"]
        assert chunked == whole, fmt
        assert chunked["male_counts"] == 280.0


def test_donor_with_two_annotated_sexes_is_refused_by_name(tmp_path):
    blocks = [_male_donor(donor="d", sex=MALE), _male_donor(donor="d", sex=FEMALE)]
    result = check_donor_sex(_write(tmp_path / "a.h5ad", blocks))
    assert "error" in result and "several sex_ontology_term_id values" in result["error"]


def test_missing_donor_id_is_refused_by_name(tmp_path):
    path = _write(tmp_path / "a.h5ad", [_male_donor()])
    adata = ad.read_h5ad(path)
    del adata.obs["donor_id"]
    adata.write_h5ad(path)
    result = check_donor_sex(path)
    assert "error" in result and "donor_id" in result["error"]


def test_handler_refusals_reach_the_caller(tmp_path):
    assert (
        "chunk_nnz must be a positive int"
        in check_donor_sex(_write(tmp_path / "a.h5ad", [_male_donor()]), chunk_nnz=0)["error"]
    )
    assert "not found" in check_donor_sex(str(tmp_path / "nope.h5ad"))["error"].lower()
