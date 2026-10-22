"""Tests for check_source_obs (#793).

Every fixture is a tracker-layout tree under ``tmp_path``: an integrated object
in ``<project>/integrated-objects/tracker-source/`` beside source datasets in
``<project>/source-datasets/tracker-source/``, written through anndata's own
writer from obs columns.
"""

from __future__ import annotations

from pathlib import Path

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pytest

from hca_anndata_tools.source_obs import CELL_TYPE_FIELDS, COMPARED_FIELDS, PAIRS_LIMIT, check_source_obs
from hca_anndata_tools.sources import INTEGRATED_DIR, SOURCE_SUBDIR
from hca_anndata_tools.testing import make_nullable_string_array


def _write(path: Path, ids: list[str], columns: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    obs = pd.DataFrame(columns, index=pd.Index(ids, name="cellID"))
    ad.AnnData(obs=obs).write_h5ad(path)
    return path


class Tree:
    """One tracker-layout project under ``root``."""

    def __init__(self, root: Path):
        project = root / "proj"
        self.integrated = project / INTEGRATED_DIR / "tracker-source"
        self.sources = project / SOURCE_SUBDIR

    def target(self, ids: list[str], **columns) -> Path:
        return _write(self.integrated / "atlas-r1-wip-3.h5ad", ids, columns)

    def source(self, name: str, ids: list[str], **columns) -> Path:
        return _write(self.sources / f"{name}-r1-wip-2.h5ad", ids, columns)


@pytest.fixture
def tree(tmp_path) -> Tree:
    return Tree(tmp_path)


def _ok(result: dict) -> dict:
    assert "error" not in result, result
    return result


def _field(result: dict, name: str) -> dict:
    return next(r for r in result["fields"] if r["field"] == name)


def _codes(result: dict) -> dict[tuple[str, str], dict]:
    return {(f["code"], f["element"]): f for f in result["findings"]}


def test_compared_fields_come_from_the_schema():
    assert {"library_id", "sex_ontology_term_id", "gene_annotation_version", "donor_id"} <= set(COMPARED_FIELDS)
    assert "is_primary_data" not in COMPARED_FIELDS
    assert {"cell_type_ontology_term_id", "author_cell_type"} == CELL_TYPE_FIELDS


def test_matching_files_are_silent(tree):
    ids = ["a1", "a2", "b1"]
    tree.source("srcA", ["a1", "a2", "a9"], donor_id=["D1", "D1", "D9"], library_id=["L1", "L2", "L9"])
    tree.source("srcB", ["b1"], donor_id=["D2"], library_id=["L3"])
    target = tree.target(ids, donor_id=["D1", "D1", "D2"], library_id=["L1", "L2", "L3"])

    result = _ok(check_source_obs(str(target)))

    assert result["partition"] == "exact"
    assert result["cells"] == {"n_obs": 3, "compared": 3, "not_compared": 0}
    assert {s["tracker_name"]: s["cells_compared"] for s in result["sources"]} == {"srcA": 2, "srcB": 1}
    assert _field(result, "donor_id")["agree"] == 3
    assert result["discrepancies"] == []
    assert result["findings"] == []
    assert "sex_ontology_term_id" in result["fields_absent"]


def test_each_outcome_is_counted_and_paired(tree):
    tree.source("srcA", ["c1", "c2", "c3", "c4", "c5"], library_id=["L1", "L2", "L3", None, None])
    target = tree.target(["c1", "c2", "c3", "c4", "c5"], library_id=["L1", "L9", None, "L4", None])

    result = _ok(check_source_obs(str(target)))

    row = _field(result, "library_id")
    assert {k: row[k] for k in ("agree", "differ", "missing_in_object", "missing_in_source", "missing_in_both")} == {
        "agree": 1,
        "differ": 1,
        "missing_in_object": 1,
        "missing_in_source": 1,
        "missing_in_both": 1,
    }
    (discrepancy,) = result["discrepancies"]
    assert discrepancy["source"] == "srcA"
    assert {(p["source_value"], p["object_value"]) for p in discrepancy["pairs"]} == {
        ("L2", "L9"),
        ("L3", None),
        (None, "L4"),
    }
    codes = _codes(result)
    assert codes[("values_differ", "obs/library_id")]["sample_ids"] == ["c2"]
    assert codes[("missing_in_object", "obs/library_id")]["sample_ids"] == ["c3"]
    assert codes[("missing_in_source", "obs/library_id")]["sample_ids"] == ["c4"]


def test_storage_does_not_make_a_difference(tree):
    ids = ["c1", "c2", "c3"]
    source = tree.source(
        "srcA",
        ids,
        sex_ontology_term_id=pd.Categorical(["PATO:0000383", "PATO:0000384", "PATO:0000383"]),
        cell_number_loaded=np.array([5000, 6000, 7000], dtype=np.int64),
        library_id=np.array(["L1", "L2", "L3"], dtype=object),
    )
    with h5py.File(source, "r+") as f:
        make_nullable_string_array(f["obs"], "library_id")  # pyright: ignore[reportArgumentType]
    target = tree.target(
        ids,
        sex_ontology_term_id=["PATO:0000383", "PATO:0000384", "PATO:0000383"],
        cell_number_loaded=np.array([5000.0, 6000.0, 7000.0]),
        library_id=pd.Categorical(["L1", "L2", "L3"]),
    )

    result = _ok(check_source_obs(str(target)))

    assert result["findings"] == []
    for field in ("sex_ontology_term_id", "cell_number_loaded", "library_id"):
        assert _field(result, field)["agree"] == 3


def test_whole_number_text_matches_the_number_and_leading_zeros_stay(tree):
    ids = ["c1", "c2", "c3"]
    tree.source(
        "srcA",
        ids,
        sample_collection_year=pd.Categorical(["2021.0", "2022.0", "2022.0"]),
        library_sequencing_run=["run01", "01", "1.0"],
    )
    target = tree.target(
        ids,
        sample_collection_year=np.array([2021.0, 2022.0, 2022.0]),
        library_sequencing_run=["run1", "1", "1"],
    )

    result = _ok(check_source_obs(str(target)))

    assert _field(result, "sample_collection_year")["agree"] == 3
    run = _field(result, "library_sequencing_run")
    assert (run["agree"], run["differ"]) == (1, 2)


def test_blank_and_nan_text_are_missing_and_unknown_is_a_value(tree):
    tree.source("srcA", ["c1", "c2", "c3"], library_id=["L1", "L2", "nan"])
    target = tree.target(["c1", "c2", "c3"], library_id=["  ", "unknown", None])

    result = _ok(check_source_obs(str(target)))

    row = _field(result, "library_id")
    assert (row["missing_in_object"], row["differ"], row["missing_in_both"]) == (1, 1, 1)


def test_a_field_one_side_lacks_counts_every_cell(tree):
    tree.source("srcA", ["c1", "c2"], library_sequencing_run=["R1", "R1"])
    target = tree.target(["c1", "c2"], donor_id=["D1", "D1"])

    result = _ok(check_source_obs(str(target)))

    run = _field(result, "library_sequencing_run")
    assert (run["in_object"], run["in_sources"], run["missing_in_object"]) == (False, 1, 2)
    donor = _field(result, "donor_id")
    assert (donor["in_object"], donor["in_sources"], donor["missing_in_source"]) == (True, 0, 2)


def test_cell_type_is_reported_apart_and_never_a_finding(tree):
    tree.source("srcA", ["c1"], cell_type_ontology_term_id=["CL:0000236"], donor_id=["D1"])
    target = tree.target(["c1"], cell_type_ontology_term_id=["CL:0000084"], donor_id=["D1"])

    result = _ok(check_source_obs(str(target)))

    assert _field(result, "cell_type_ontology_term_id")["group"] == "cell_type"
    (discrepancy,) = result["discrepancies"]
    assert (discrepancy["group"], discrepancy["differ"]) == ("cell_type", 1)
    assert result["findings"] == []


def test_is_primary_data_is_not_compared(tree):
    tree.source("srcA", ["c1"], is_primary_data=[True])
    target = tree.target(["c1"], is_primary_data=[False])

    result = _ok(check_source_obs(str(target)))

    assert "is_primary_data" not in {r["field"] for r in result["fields"]}
    assert result["findings"] == []


def test_unclaimed_cells_are_not_compared(tree):
    tree.source("srcA", ["c1"], donor_id=["D1"])
    target = tree.target(["c1", "x1"], donor_id=["D1", "D9"])

    result = _ok(check_source_obs(str(target)))

    assert result["partition"] == "incomplete"
    assert result["cells"] == {"n_obs": 2, "compared": 1, "not_compared": 1}
    assert _field(result, "donor_id")["agree"] == 1
    assert [f["code"] for f in result["findings"]] == ["unaccounted_cells"]


def test_pairs_are_capped(tree):
    n = PAIRS_LIMIT + 5
    ids = [f"c{i}" for i in range(n)]
    tree.source("srcA", ids, library_id=[f"S{i}" for i in range(n)])
    target = tree.target(ids, library_id=[f"T{i}" for i in range(n)])

    result = _ok(check_source_obs(str(target)))

    (discrepancy,) = result["discrepancies"]
    assert discrepancy["differ"] == n
    assert len(discrepancy["pairs"]) == PAIRS_LIMIT


@pytest.mark.filterwarnings("ignore:Observation names are not unique")
def test_a_source_with_repeated_ids_is_refused(tree):
    tree.source("srcA", ["c1", "c1"], donor_id=["D1", "D2"])
    target = tree.target(["c1"], donor_id=["D1"])

    result = check_source_obs(str(target))

    assert "duplicate" in result["error"]
    assert "ambiguous" in result["error"]


def test_outside_the_layout_is_refused(tmp_path):
    target = _write(tmp_path / "loose.h5ad", ["c1"], {"donor_id": ["D1"]})

    assert "integrated-objects" in check_source_obs(str(target))["error"]
