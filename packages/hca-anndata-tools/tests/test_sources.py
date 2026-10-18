"""Tests for find_source_datasets (#705).

Every fixture is a tracker-layout tree under ``tmp_path`` — ``<project>/
integrated-objects/...`` beside ``<project>/source-datasets/tracker-source/``
— whose files are obs indexes written through anndata's own writer from ID
lists. The tool reads nothing but those indexes, and the CSC case proves it.
"""

from __future__ import annotations

import os
from pathlib import Path

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp
from anndata.io import write_elem

from hca_anndata_tools.qc import SAMPLE_ID_LIMIT
from hca_anndata_tools.sources import (
    EXISTING_STATES,
    INTEGRATED_DIR,
    PARTITIONS,
    SOURCE_SUBDIR,
    WRONG_VALUES_LIMIT,
    find_source_datasets,
    tracker_name,
)
from hca_anndata_tools.testing import create_truncated_h5ad, make_nullable_string_array


def _ids(prefix: str, n: int) -> list[str]:
    return [f"{prefix}_{i}" for i in range(n)]


def _write(path: Path, ids: list[str], X=None, columns: dict | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    obs = pd.DataFrame(columns or {}, index=pd.Index(ids, name="cellID"))
    ad.AnnData(X=X, obs=obs).write_h5ad(path)  # pyright: ignore[reportArgumentType]
    return path


class Tree:
    """One tracker-layout project under ``root``."""

    def __init__(self, root: Path):
        self.project = root / "proj"
        self.integrated = self.project / INTEGRATED_DIR
        self.sources = self.project / SOURCE_SUBDIR

    def target(
        self,
        ids: list[str],
        where: str = "tracker-source",
        name: str = "atlas-r1-wip-3.h5ad",
        X=None,
        columns: dict | None = None,
    ) -> Path:
        return _write(self.integrated / where / name, ids, X, columns)

    def source(self, name: str, ids: list[str]) -> Path:
        return _write(self.sources / f"{name}.h5ad", ids)


@pytest.fixture
def tree(tmp_path) -> Tree:
    return Tree(tmp_path)


def _ok(result: dict) -> dict:
    assert "error" not in result, result
    return result


def _rows(result: dict) -> dict[str, dict]:
    return {r["filename"]: r for r in result["sources"]}


# --- Partition ------------------------------------------------------------


def test_exact_partition(tree):
    a, b = _ids("a", 30), _ids("b", 10)
    tree.source("a-r1-wip-1", a)
    tree.source("b-r1-wip-1", b)
    result = _ok(find_source_datasets(str(tree.target(a + b))))

    assert result["source_dir"] == str(tree.sources)
    assert result["partition"] == "exact"
    assert result["target"] == {"n_obs": 40, "accounted": 40, "unaccounted": 0, "claimed_twice": 0}
    assert result["findings"] == []
    assert [r["filename"] for r in result["sources"]] == ["a-r1-wip-1.h5ad", "b-r1-wip-1.h5ad"]
    assert _rows(result)["a-r1-wip-1.h5ad"] == {
        "filename": "a-r1-wip-1.h5ad",
        "tracker_name": "a",
        "n_obs": 30,
        "matched_by_id": 30,
        "fraction_of_target": 0.75,
    }


def test_zero_match_candidate_is_listed_last_with_zeros(tree):
    a = _ids("a", 10)
    tree.source("a-r1-wip-1", a)
    tree.source("unrelated-r1-wip-1", _ids("z", 5))
    result = _ok(find_source_datasets(str(tree.target(a))))

    assert result["partition"] == "exact"
    assert [r["filename"] for r in result["sources"]] == ["a-r1-wip-1.h5ad", "unrelated-r1-wip-1.h5ad"]
    assert _rows(result)["unrelated-r1-wip-1.h5ad"] == {
        "filename": "unrelated-r1-wip-1.h5ad",
        "tracker_name": "unrelated",
        "n_obs": 5,
        "matched_by_id": 0,
        "fraction_of_target": 0.0,
    }


def test_ordering_is_by_fraction_then_filename(tree):
    tree.source("small-r1-wip-1", _ids("a", 2))
    tree.source("big-r1-wip-1", _ids("a", 2) + _ids("b", 6))
    tree.source("also-small-r1-wip-1", _ids("c", 2))
    result = _ok(find_source_datasets(str(tree.target(_ids("a", 2) + _ids("b", 6) + _ids("c", 2)))))
    assert [r["filename"] for r in result["sources"]] == [
        "big-r1-wip-1.h5ad",
        "also-small-r1-wip-1.h5ad",
        "small-r1-wip-1.h5ad",
    ]


def test_unaccounted_cells(tree):
    a = _ids("a", 5)
    missing = _ids("m", SAMPLE_ID_LIMIT + 3)
    tree.source("a-r1-wip-1", a)
    result = _ok(find_source_datasets(str(tree.target(a + missing))))

    n = len(missing)
    assert result["target"] == {"n_obs": 5 + n, "accounted": 5, "unaccounted": n, "claimed_twice": 0}
    assert result["partition"] == "incomplete"
    assert [f["code"] for f in result["findings"]] == ["unaccounted_cells"]
    f = result["findings"][0]
    assert f["count"] == n
    assert f["sample_ids"] == missing[:SAMPLE_ID_LIMIT]
    assert f["element"] == "obs/cellID"


def test_cells_claimed_twice(tree):
    a, b = _ids("a", 6), _ids("b", 4)
    tree.source("a-r1-wip-1", a)
    tree.source("b-r1-wip-1", b + a[:2])  # b re-ingested two of a's cells
    result = _ok(find_source_datasets(str(tree.target(a + b))))

    assert result["target"] == {"n_obs": 10, "accounted": 10, "unaccounted": 0, "claimed_twice": 2}
    assert result["partition"] == "incomplete"
    assert [f["code"] for f in result["findings"]] == ["cells_claimed_twice"]
    assert result["findings"][0]["sample_ids"] == a[:2]
    assert _rows(result)["b-r1-wip-1.h5ad"]["matched_by_id"] == 6


def test_unaccounted_and_claimed_twice_both_reported(tree):
    a = _ids("a", 4)
    tree.source("a-r1-wip-1", a)
    tree.source("a-again-r1-wip-1", a)
    result = _ok(find_source_datasets(str(tree.target(a + _ids("m", 1)))))
    assert result["partition"] == "incomplete"
    assert result["target"] == {"n_obs": 5, "accounted": 4, "unaccounted": 1, "claimed_twice": 4}
    assert [(f["code"], f["count"]) for f in result["findings"]] == [
        ("unaccounted_cells", 1),
        ("cells_claimed_twice", 4),
    ]


def test_partition_is_always_a_known_code(tree):
    a = _ids("a", 2)
    tree.source("a-r1-wip-1", a)
    for target_ids in (a, a + _ids("m", 1)):
        result = _ok(find_source_datasets(str(tree.target(target_ids))))
        assert result["partition"] in PARTITIONS


@pytest.mark.filterwarnings("ignore:Observation names are not unique")
def test_candidate_duplicates_count_as_a_set(tree):
    a = _ids("a", 3)
    tree.source("a-r1-wip-1", a + a)  # a source with every ID twice
    result = _ok(find_source_datasets(str(tree.target(a))))
    assert _rows(result)["a-r1-wip-1.h5ad"] == {
        "filename": "a-r1-wip-1.h5ad",
        "tracker_name": "a",
        "n_obs": 6,
        "matched_by_id": 3,
        "fraction_of_target": 1.0,
    }
    assert result["partition"] == "exact"


# --- Reads the index only --------------------------------------------------


def test_csc_target_succeeds_because_no_matrix_is_read(tree):
    a = _ids("a", 8)
    tree.source("a-r1-wip-1", a)
    X = sp.random(8, 5, density=0.5, format="csc", dtype=np.float32, random_state=np.random.default_rng(705))  # pyright: ignore[reportCallIssue]
    result = _ok(find_source_datasets(str(tree.target(a, X=X))))
    assert result["partition"] == "exact"


# --- Layout ---------------------------------------------------------------


@pytest.mark.parametrize("where", ["", "tracker-source", "cap-source", "archive"])
def test_target_found_from_every_position_under_integrated_objects(tree, where):
    a = _ids("a", 4)
    tree.source("a-r1-wip-1", a)
    result = _ok(find_source_datasets(str(tree.target(a, where=where))))
    assert result["partition"] == "exact"
    assert result["source_dir"] == str(tree.sources)


def test_nearest_integrated_objects_ancestor_wins(tmp_path):
    """A project nested under another project's ``integrated-objects`` resolves to its own sources."""
    outer = Tree(tmp_path)
    inner = Tree(outer.integrated / "nested")
    a = _ids("a", 3)
    outer.source("outer-r1-wip-1", _ids("z", 3))
    inner.source("inner-r1-wip-1", a)
    result = _ok(find_source_datasets(str(inner.target(a))))
    assert result["source_dir"] == str(inner.sources)
    assert result["partition"] == "exact"


def test_target_outside_layout_is_refused_by_name(tmp_path):
    target = _write(tmp_path / "loose" / "atlas.h5ad", _ids("a", 3))
    result = find_source_datasets(str(target))
    assert "error" in result
    assert INTEGRATED_DIR in result["error"] and str(target) in result["error"]


def test_dotdot_hop_out_of_the_layout_is_refused(tree):
    """``integrated-objects/../loose/x.h5ad`` names a file outside the layout; the walk sees the normalised path."""
    tree.source("a-r1-wip-1", _ids("a", 3))
    tree.integrated.mkdir(parents=True)
    loose = _write(tree.project / "loose" / "atlas.h5ad", _ids("a", 3))
    hop = tree.integrated / ".." / "loose" / "atlas.h5ad"
    assert hop.exists() and hop.samefile(loose)
    result = find_source_datasets(str(hop))
    assert "error" in result and INTEGRATED_DIR in result["error"]


def test_dotdot_hop_within_the_layout_still_resolves(tree):
    a = _ids("a", 3)
    tree.source("a-r1-wip-1", a)
    tree.target(a)
    hop = tree.integrated / "cap-source" / ".." / "tracker-source" / "atlas-r1-wip-3.h5ad"
    (tree.integrated / "cap-source").mkdir()
    result = _ok(find_source_datasets(str(hop)))
    assert result["partition"] == "exact" and result["filename"] == "atlas-r1-wip-3.h5ad"


def test_missing_source_dir_is_refused_by_name(tree):
    result = find_source_datasets(str(tree.target(_ids("a", 3))))
    assert result["error"] == f"source directory {tree.sources} does not exist"


def test_source_dir_that_is_a_file_is_refused_by_name(tree):
    tree.sources.parent.mkdir(parents=True)
    tree.sources.write_text("not a directory")
    result = find_source_datasets(str(tree.target(_ids("a", 3))))
    assert result["error"] == f"source directory {tree.sources} is not a directory"


def test_empty_source_dir_is_refused_by_name(tree):
    tree.sources.mkdir(parents=True)
    (tree.sources / "notes.md").write_text("not a dataset")
    (tree.sources / "nested").mkdir()
    _write(tree.sources / "nested" / "deep.h5ad", _ids("a", 3))  # not top-level, so not a candidate
    result = find_source_datasets(str(tree.target(_ids("a", 3))))
    assert result["error"] == f"source directory {tree.sources} holds no .h5ad file"


def test_non_file_entries_named_h5ad_are_not_candidates(tree):
    """A directory or a dangling symlink named ``*.h5ad`` is not a dataset; the gate's own ``is_file`` rule applies."""
    a = _ids("a", 5)
    tree.source("a-r1-wip-1", a)
    (tree.sources / "dir.h5ad").mkdir()
    (tree.sources / "dangling.h5ad").symlink_to(tree.sources / "gone.h5ad")
    result = _ok(find_source_datasets(str(tree.target(a))))
    assert [r["filename"] for r in result["sources"]] == ["a-r1-wip-1.h5ad"]
    assert result["partition"] == "exact"


def test_source_dir_holding_only_a_directory_named_h5ad_is_empty(tree):
    tree.sources.mkdir(parents=True)
    (tree.sources / "dir.h5ad").mkdir()
    result = find_source_datasets(str(tree.target(_ids("a", 3))))
    assert result["error"] == f"source directory {tree.sources} holds no .h5ad file"


def test_candidate_that_is_the_target_is_refused(tree):
    a = _ids("a", 3)
    tree.source("other-r1-wip-1", _ids("z", 2))
    target = tree.target(a)
    (tree.sources / "self-r1-wip-1.h5ad").symlink_to(target)
    result = find_source_datasets(str(target))
    assert "error" in result
    assert "self-r1-wip-1.h5ad" in result["error"] and "is the target itself" in result["error"]


def test_hard_link_to_the_target_is_refused(tree):
    a = _ids("a", 3)
    tree.source("other-r1-wip-1", _ids("z", 2))
    target = tree.target(a)
    os.link(target, tree.sources / "copy-r1-wip-1.h5ad")
    result = find_source_datasets(str(target))
    assert "error" in result
    assert "copy-r1-wip-1.h5ad" in result["error"] and "is the target itself" in result["error"]


def test_edit_variants_collapse_to_the_latest(tree):
    a = _ids("a", 4)
    tree.source("a-r1-wip-2", _ids("old", 4))
    tree.source("a-r1-wip-2-edit-2026-01-01-00-00-00", _ids("older-edit", 4))
    tree.source("a-r1-wip-2-edit-2026-02-01-00-00-00", a)
    result = _ok(find_source_datasets(str(tree.target(a))))

    assert [r["filename"] for r in result["sources"]] == ["a-r1-wip-2-edit-2026-02-01-00-00-00.h5ad"]
    assert result["partition"] == "exact"


def test_target_edit_variant_resolves_within_the_layout(tree):
    """The target resolves to its latest snapshot, which sits in the same directory, so the layout still holds."""
    a = _ids("a", 4)
    tree.source("a-r1-wip-1", a)
    tree.target(_ids("stale", 4))
    tree.target(a, name="atlas-r1-wip-3-edit-2026-03-01-00-00-00.h5ad")
    result = _ok(find_source_datasets(str(tree.integrated / "tracker-source" / "atlas-r1-wip-3.h5ad")))
    assert result["filename"] == "atlas-r1-wip-3-edit-2026-03-01-00-00-00.h5ad"
    assert result["partition"] == "exact"


# --- Tracker names (#776) -------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("hgca-v1-burclaff-2022-r1-wip-8.h5ad", "hgca-v1-burclaff-2022"),
        ("hgca-v1-burclaff-2022-r1-wip-8-edit-2026-10-14-01-02-03.h5ad", "hgca-v1-burclaff-2022"),
        ("published-r2.h5ad", "published"),
        # Only the trailing revision is the tracker's; one inside the name is part of it.
        ("study-r1-extra-r3-wip-4.h5ad", "study-r1-extra"),
        ("plain.h5ad", None),
        ("Integrated Human Breast Cell Atlas v1.0 - all cells.h5ad", None),
        ("a-r1-wip-2.h5ad.bak", None),
        ("a-wip-2.h5ad", None),
    ],
)
def test_tracker_name_reads_the_download_name(filename, expected):
    assert tracker_name(filename) == expected


def test_rows_and_target_carry_tracker_names(tree):
    a = _ids("a", 4)
    tree.source("hgca-v1-a-r1-wip-7-edit-2026-01-01-00-00-00", a)
    result = _ok(find_source_datasets(str(tree.target(a, name="hgca-v1-all-r1-wip-11.h5ad"))))
    assert result["tracker_name"] == "hgca-v1-all"
    assert [r["tracker_name"] for r in result["sources"]] == ["hgca-v1-a"]


def test_target_without_a_tracker_name_is_reported_not_refused(tree):
    """The target's name is only reported, so a CAP export's name does not stop the preview."""
    a = _ids("a", 4)
    tree.source("a-r1-wip-1", a)
    result = _ok(find_source_datasets(str(tree.target(a, where="cap-source", name="Atlas - all cells.h5ad"))))
    assert result["tracker_name"] is None
    assert result["partition"] == "exact"


def test_candidate_without_a_tracker_name_is_refused_by_name(tree):
    a = _ids("a", 4)
    tree.source("a-r1-wip-1", a)
    tree.source("renamed-by-hand", _ids("b", 2))
    result = find_source_datasets(str(tree.target(a)))
    assert set(result) == {"error"}
    assert "not tracker download names" in result["error"] and "renamed-by-hand.h5ad" in result["error"]


def test_two_copies_of_one_tracker_source_are_refused(tree):
    a = _ids("a", 4)
    tree.source("a-r1-wip-1", a)
    tree.source("a-r1-wip-2", a)
    result = find_source_datasets(str(tree.target(a)))
    assert set(result) == {"error"}
    assert "more than one copy" in result["error"]
    assert "a-r1-wip-1.h5ad" in result["error"] and "a-r1-wip-2.h5ad" in result["error"]


# --- The existing source_dataset column (#776) -----------------------------


@pytest.fixture
def two_sources(tree):
    """Five cells: three from source a, two from source b."""
    tree.source("a-r1-wip-1", _ids("a", 3))
    tree.source("b-r1-wip-1", _ids("b", 2))
    return _ids("a", 3) + _ids("b", 2)


def test_no_column_is_absent(tree, two_sources):
    result = _ok(find_source_datasets(str(tree.target(two_sources))))
    assert result["source_dataset"] == {"status": "absent"}


def test_a_column_matching_the_match_is_correct(tree, two_sources):
    column = pd.Categorical(["a", "a", "a", "b", "b"])
    result = _ok(find_source_datasets(str(tree.target(two_sources, columns={"source_dataset": column}))))
    assert result["source_dataset"] == {
        "status": "correct",
        "agree": 5,
        "unset": 0,
        "wrong": 0,
        "wrong_values": [],
        "wrong_sample_ids": [],
    }


def test_empty_and_blank_cells_are_incomplete(tree, two_sources):
    column = np.array(["a", None, "a", " ", "b"], dtype=object)
    result = _ok(find_source_datasets(str(tree.target(two_sources, columns={"source_dataset": column}))))
    existing = result["source_dataset"]
    assert (existing["status"], existing["agree"], existing["unset"], existing["wrong"]) == ("incomplete", 3, 2, 0)


def test_other_values_are_wrong_and_listed_with_what_they_should_be(tree, two_sources):
    """The team's own labels, say: right cells, wrong names."""
    column = pd.Categorical(["StudyA", "StudyA", "a", "StudyB", np.nan])
    result = _ok(find_source_datasets(str(tree.target(two_sources, columns={"source_dataset": column}))))
    existing = result["source_dataset"]
    assert (existing["status"], existing["agree"], existing["unset"], existing["wrong"]) == ("wrong", 1, 1, 3)
    assert existing["wrong_values"] == [
        {"value": "StudyA", "expected": "a", "cells": 2},
        {"value": "StudyB", "expected": "b", "cells": 1},
    ]
    assert existing["wrong_sample_ids"] == ["a_0", "a_1", "b_0"]


@pytest.mark.parametrize("nullable", [False, True], ids=["plain-strings", "nullable-strings"])
def test_a_string_column_is_read_like_a_categorical(tree, two_sources, nullable):
    """anndata writes object columns as categoricals, so the string encodings are built by hand."""
    target = tree.target(two_sources, columns={"other": ["v"] * 5})
    with h5py.File(target, "r+") as f:
        write_elem(f["obs"], "source_dataset", np.array(["a", "a", "a", "b", "x"], dtype=object))
        if nullable:
            make_nullable_string_array(f["obs"], "source_dataset")  # pyright: ignore[reportArgumentType]
    existing = _ok(find_source_datasets(str(target)))["source_dataset"]
    assert existing["status"] == "wrong"
    assert existing["wrong_values"] == [{"value": "x", "expected": "b", "cells": 1}]


def test_cells_no_single_source_claims_are_left_to_the_partition_findings(tree, two_sources):
    column = np.array(["a", "a", "a", "b", "b", "anything"], dtype=object)
    target = tree.target([*two_sources, "stray_0"], columns={"source_dataset": column})
    result = _ok(find_source_datasets(str(target)))
    assert result["partition"] == "incomplete"
    assert result["source_dataset"]["status"] == "correct"


def test_wrong_values_are_capped(tree):
    n = WRONG_VALUES_LIMIT + 5
    tree.source("a-r1-wip-1", _ids("a", n))
    column = np.array([f"label{i}" for i in range(n)], dtype=object)
    existing = _ok(find_source_datasets(str(tree.target(_ids("a", n), columns={"source_dataset": column}))))[
        "source_dataset"
    ]
    assert existing["wrong"] == n
    assert len(existing["wrong_values"]) == WRONG_VALUES_LIMIT


def test_existing_status_is_always_a_known_state(tree, two_sources):
    result = _ok(find_source_datasets(str(tree.target(two_sources))))
    assert result["source_dataset"]["status"] in EXISTING_STATES


# --- Target and candidate faults ------------------------------------------


@pytest.mark.filterwarnings("ignore:Observation names are not unique")
def test_duplicate_target_ids_are_refused(tree):
    a = _ids("a", 3)
    tree.source("a-r1-wip-1", a)
    result = find_source_datasets(str(tree.target(a + a[:1])))
    assert "error" in result
    assert "duplicate IDs" in result["error"] and "a_0" in result["error"]


def test_unopenable_candidate_fails_the_run_in_anndatas_words(tree):
    a = _ids("a", 5)
    good = tree.source("a-r1-wip-1", a)
    create_truncated_h5ad(tree.sources / "broken-r1-wip-1.h5ad", source=good)
    result = find_source_datasets(str(tree.target(a)))
    assert set(result) == {"error"}  # a refusal: no traceback, no partial result
    assert result["error"].startswith("broken-r1-wip-1.h5ad: ")


def test_candidate_anndata_rejects_but_h5py_opens_is_refused_not_matched(tree):
    """Pins the candidate-side Scope gate: a masked categorical in a non-index
    column is a file h5py reads happily and anndata refuses. Without the gate
    the candidate would match every cell; with it the run is refused, naming
    the column."""
    a = _ids("a", 5)
    tree.source("a-r1-wip-1", a)
    bad = tree.sources / "masked-r1-wip-1.h5ad"
    obs = pd.DataFrame({"family": pd.Categorical(["x", "y", "x", "y", "x"])}, index=pd.Index(a, name="cellID"))
    ad.AnnData(obs=obs).write_h5ad(bad)
    with h5py.File(bad, "r+") as f:
        make_nullable_string_array(f["obs/family"], "categories", masked=1)  # pyright: ignore[reportArgumentType]
    result = find_source_datasets(str(tree.target(a)))
    assert set(result) == {"error"}
    assert result["error"].startswith("masked-r1-wip-1.h5ad: ") and "obs column 'family'" in result["error"]


def _store_index_as_int64(path: Path) -> None:
    """Rewrite a file's obs index dataset as int64 in place — the shape a producer's ``RangeIndex`` leaves behind."""
    with h5py.File(path, "r+") as f:
        obs = f["obs"]
        assert isinstance(obs, h5py.Group)
        name = obs.attrs["_index"]
        n = obs[name].shape[0]  # pyright: ignore[reportAttributeAccessIssue]
        del obs[name]
        ds = obs.create_dataset(name, data=np.arange(n, dtype=np.int64))
        ds.attrs["encoding-type"] = "array"  # what anndata stamps on a numeric dataset
        ds.attrs["encoding-version"] = "0.2.0"


@pytest.mark.filterwarnings("ignore:Transforming to str index")
def test_integer_target_index_is_refused_not_converted(tree):
    a = _ids("a", 3)
    tree.source("a-r1-wip-1", a)
    target = tree.target(a)
    _store_index_as_int64(target)
    result = find_source_datasets(str(target))
    assert set(result) == {"error"}
    assert (
        result["error"] == f"{target.name} obs index is stored as int64, not strings; cell IDs must be strings to match"
    )


@pytest.mark.filterwarnings("ignore:Transforming to str index")
def test_integer_candidate_index_is_refused_not_converted(tree):
    a = _ids("a", 3)
    bad = tree.source("ints-r1-wip-1", a)
    _store_index_as_int64(bad)
    result = find_source_datasets(str(tree.target(a)))
    assert set(result) == {"error"}
    assert result["error"].startswith("ints-r1-wip-1.h5ad obs index is stored as int64")


def test_missing_target_keeps_the_tools_own_message(tree):
    tree.source("a-r1-wip-1", _ids("a", 2))
    result = find_source_datasets(str(tree.integrated / "absent.h5ad"))
    assert result["error"].startswith("File not found")
