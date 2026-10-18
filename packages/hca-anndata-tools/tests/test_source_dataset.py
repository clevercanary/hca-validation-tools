"""Tests for set_source_dataset (#776).

Every fixture is a tracker-layout tree under ``tmp_path`` — ``<project>/
integrated-objects/tracker-source/`` beside ``<project>/source-datasets/
tracker-source/`` — written through anndata's own writer, so the tool reads
files it did not build.
"""

from __future__ import annotations

import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import pytest

from hca_anndata_tools._io import read_obs_column_names
from hca_anndata_tools.source_dataset import set_source_dataset
from hca_anndata_tools.sources import INTEGRATED_DIR, SOURCE_SUBDIR
from hca_anndata_tools.write import EDIT_LOG_KEY


def _ids(prefix: str, n: int) -> list[str]:
    return [f"{prefix}_{i}" for i in range(n)]


def _write(path: Path, ids: list[str], obs: dict | None = None, uns: dict | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(obs or {}, index=pd.Index(ids, name="cellID"))
    ad.AnnData(X=np.zeros((len(ids), 1), dtype=np.float32), obs=frame, uns=uns or {}).write_h5ad(path)
    return path


class Tree:
    """One tracker-layout project under ``root``."""

    def __init__(self, root: Path):
        self.project = root / "proj"
        self.targets = self.project / INTEGRATED_DIR / "tracker-source"
        self.sources = self.project / SOURCE_SUBDIR

    def target(self, ids: list[str], obs: dict | None = None, uns: dict | None = None) -> Path:
        return _write(self.targets / "atlas-r1-wip-3.h5ad", ids, obs, uns)

    def source(self, name: str, ids: list[str]) -> Path:
        return _write(self.sources / f"{name}.h5ad", ids)

    def snapshots(self) -> list[str]:
        return sorted(p.name for p in self.targets.glob("*-edit-*.h5ad"))


@pytest.fixture
def tree(tmp_path) -> Tree:
    return Tree(tmp_path)


def _ok(result: dict) -> dict:
    assert "error" not in result, result
    return result


# --- Writing ---------------------------------------------------------------


def test_each_cell_gets_its_sources_tracker_name(tree):
    a, b = _ids("a", 3), _ids("b", 2)
    tree.source("hgca-v1-b-r1-wip-2", b)
    tree.source("hgca-v1-a-r1-wip-7", a)
    target = tree.target(b[:1] + a + b[1:], obs={"donor_id": ["d1"] * 5})
    result = _ok(set_source_dataset(str(target)))

    written = ad.read_h5ad(result["output_path"]).obs["source_dataset"]
    assert isinstance(written.dtype, pd.CategoricalDtype)
    assert list(written.cat.categories) == ["hgca-v1-a", "hgca-v1-b"]
    assert list(written) == ["hgca-v1-b", "hgca-v1-a", "hgca-v1-a", "hgca-v1-a", "hgca-v1-b"]
    assert result["column"] == "source_dataset" and result["n_obs"] == 5
    assert result["sources"] == [
        {"tracker_name": "hgca-v1-a", "filename": "hgca-v1-a-r1-wip-7.h5ad", "cells": 3},
        {"tracker_name": "hgca-v1-b", "filename": "hgca-v1-b-r1-wip-2.h5ad", "cells": 2},
    ]


def test_writes_a_snapshot_and_leaves_the_original_alone(tree):
    a = _ids("a", 3)
    tree.source("a-r1-wip-1", a)
    target = tree.target(a, obs={"donor_id": ["d1"] * 3})
    result = _ok(set_source_dataset(str(target)))

    assert Path(result["output_path"]).parent == tree.targets
    assert tree.snapshots() == [Path(result["output_path"]).name]
    assert "source_dataset" not in read_obs_column_names(str(target))
    assert read_obs_column_names(result["output_path"]) == ["donor_id", "source_dataset"]


def test_a_source_no_cell_matches_is_reported_with_zero_cells_and_no_category(tree):
    """The lineage objects hold subsets: a source contributing nothing is listed, not written."""
    a = _ids("a", 3)
    tree.source("a-r1-wip-1", a)
    tree.source("unused-r1-wip-1", _ids("z", 4))
    result = _ok(set_source_dataset(str(tree.target(a))))

    assert result["sources"][-1] == {"tracker_name": "unused", "filename": "unused-r1-wip-1.h5ad", "cells": 0}
    assert list(ad.read_h5ad(result["output_path"]).obs["source_dataset"].cat.categories) == ["a"]


def test_records_the_edit_with_per_source_counts(tree):
    a, b = _ids("a", 3), _ids("b", 1)
    tree.source("a-r1-wip-1", a)
    tree.source("b-r1-wip-1", b)
    tree.source("unused-r1-wip-1", _ids("z", 2))
    result = _ok(set_source_dataset(str(tree.target(a + b))))

    log = json.loads(ad.read_h5ad(result["output_path"]).uns["provenance"][EDIT_LOG_KEY])
    assert log[-1]["operation"] == "set_source_dataset"
    assert log[-1]["details"] == {"column": "source_dataset", "n_obs": 4, "sources": {"a": 3, "b": 1}}


def test_an_entirely_empty_column_is_replaced_in_place(tree):
    a = _ids("a", 3)
    tree.source("a-r1-wip-1", a)
    empty = pd.Categorical([np.nan] * 3, categories=["stale"])
    target = tree.target(a, obs={"source_dataset": empty, "donor_id": ["d1"] * 3})
    result = _ok(set_source_dataset(str(target)))

    assert read_obs_column_names(result["output_path"]) == ["source_dataset", "donor_id"]
    assert list(ad.read_h5ad(result["output_path"]).obs["source_dataset"]) == ["a"] * 3


def test_a_stale_palette_is_dropped(tree):
    """A palette describes the categories it was drawn for, so one left behind would colour the new ones."""
    a = _ids("a", 3)
    tree.source("a-r1-wip-1", a)
    target = tree.target(a, uns={"source_dataset_colors": np.array(["#000000", "#ffffff"], dtype=object)})
    result = _ok(set_source_dataset(str(target)))
    assert "source_dataset_colors" not in ad.read_h5ad(result["output_path"]).uns


def test_an_edit_snapshot_target_is_edited_and_the_previous_snapshot_retired(tree):
    a = _ids("a", 3)
    tree.source("a-r1-wip-1", a)
    original = tree.target(a)
    previous = _write(tree.targets / "atlas-r1-wip-3-edit-2026-01-01-00-00-00.h5ad", a, {"donor_id": ["d2"] * 3})
    result = _ok(set_source_dataset(str(original)))  # resolves to the snapshot

    assert original.is_file() and not previous.exists()
    written = ad.read_h5ad(result["output_path"]).obs
    assert list(written["donor_id"]) == ["d2"] * 3 and list(written["source_dataset"]) == ["a"] * 3


# --- Refusals: each writes nothing ----------------------------------------


def test_cells_no_source_matches_are_refused(tree):
    a = _ids("a", 3)
    tree.source("a-r1-wip-1", a)
    result = set_source_dataset(str(tree.target([*a, "stray_0", "stray_1"])))

    assert set(result) == {"error"}
    assert "2 cells match no source dataset" in result["error"] and "stray_0" in result["error"]
    assert tree.snapshots() == []


def test_cells_two_sources_claim_are_refused(tree):
    a = _ids("a", 3)
    tree.source("a-r1-wip-1", a)
    tree.source("b-r1-wip-1", a[:1])
    result = set_source_dataset(str(tree.target(a)))

    assert set(result) == {"error"}
    assert "1 cell matches more than one" in result["error"] and "a_0" in result["error"]
    assert tree.snapshots() == []


def test_a_column_holding_values_is_refused(tree):
    a = _ids("a", 3)
    tree.source("a-r1-wip-1", a)
    target = tree.target(a, obs={"source_dataset": pd.Categorical(["Study1", np.nan, np.nan])})
    result = set_source_dataset(str(target))

    assert set(result) == {"error"}
    assert "'source_dataset' already exists in obs and holds values" in result["error"]
    assert tree.snapshots() == []


def test_both_refusals_are_reported_together(tree):
    a = _ids("a", 3)
    tree.source("a-r1-wip-1", a)
    target = tree.target([*a, "stray_0"], obs={"source_dataset": pd.Categorical(["x"] * 4)})
    result = set_source_dataset(str(target))
    assert "1 cell matches no source dataset" in result["error"] and "holds values" in result["error"]


def test_a_source_without_a_tracker_name_is_refused(tree):
    a = _ids("a", 3)
    tree.source("renamed-by-hand", a)
    result = set_source_dataset(str(tree.target(a)))

    assert set(result) == {"error"}
    assert "not tracker download names" in result["error"]
    assert tree.snapshots() == []


def test_a_target_outside_the_layout_is_refused(tmp_path):
    target = _write(tmp_path / "loose.h5ad", _ids("a", 3))
    result = set_source_dataset(str(target))
    assert set(result) == {"error"}
    assert "integrated-objects" in result["error"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["loose.h5ad"]


def test_a_missing_file_keeps_the_tools_own_message(tree):
    result = set_source_dataset(str(tree.targets / "absent-r1-wip-1.h5ad"))
    assert set(result) == {"error"}
