"""Tests for check_cap_currency (#781).

Every fixture is a tracker-layout tree under ``tmp_path``: an integrated object
in ``<project>/integrated-objects/tracker-source/`` beside CAP exports in
``<project>/integrated-objects/cap-source/``, written through anndata's own
writer.
"""

from __future__ import annotations

from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import pytest

from hca_anndata_tools.cap_currency import CAP_SOURCE_DIR, check_cap_currency
from hca_anndata_tools.sources import INTEGRATED_DIR
from hca_anndata_tools.testing import create_truncated_h5ad

V4 = "https://celltype.info/project/1030/dataset/3400"
V5 = "https://celltype.info/project/1070/dataset/3548"


def _block(url: str, version: str, timestamp: str) -> dict:
    return {
        "cap_dataset_url": url,
        "publication_version": version,
        "publication_timestamp": timestamp,
        "cellannotation_schema_version": "2.0.1",
        "cellannotation_metadata": {"celltype": {"annotation_method": "manual"}},
    }


AUGUST = _block(V4, "v4", "2026-08-14T14:42:40.697Z")
OCTOBER = _block(V5, "v5", "2026-10-16T13:55:25.963Z")


def _write(path: Path, uns: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    obs = pd.DataFrame(index=pd.Index([f"c{i}" for i in range(3)], name="cellID"))
    ad.AnnData(X=np.zeros((3, 1), dtype=np.float32), obs=obs, uns=uns).write_h5ad(path)
    return path


class Tree:
    def __init__(self, root: Path):
        self.integrated = root / "proj" / INTEGRATED_DIR
        self.caps = self.integrated / CAP_SOURCE_DIR

    def target(self, block: dict | None, uns: dict | None = None) -> Path:
        """The integrated object, carrying ``block`` as its CAP block, or ``uns`` verbatim."""
        if uns is None:
            uns = {"cap_metadata": block} if block else {}
        return _write(self.integrated / "tracker-source" / "atlas-r1-wip-3.h5ad", uns)

    def export(self, title: str, block: dict) -> Path:
        return _write(self.caps / f"{title}.h5ad", {"cap_metadata": block})


@pytest.fixture
def tree(tmp_path) -> Tree:
    return Tree(tmp_path)


def _ok(result: dict) -> dict:
    assert "error" not in result, result
    return result


# --- Statuses --------------------------------------------------------------


def test_an_object_carrying_the_exports_publication_is_current(tree):
    tree.export("Atlas - All Cells", OCTOBER)
    result = _ok(check_cap_currency(str(tree.target(OCTOBER)), V5))
    assert result["status"] == "current"
    assert result["export"]["path"] == str(tree.caps / "Atlas - All Cells.h5ad")
    assert result["object"] == {k: OCTOBER[k] for k in result["object"]}


def test_an_object_on_another_cap_dataset_is_behind(tree):
    """Gut v1: v4 under project 1030 in the object, v5 under project 1070 on the tracker."""
    tree.export("Atlas - All Cells", OCTOBER)
    result = _ok(check_cap_currency(str(tree.target(AUGUST)), V5))
    assert result["status"] == "behind"
    assert result["object"]["publication_version"] == "v4"
    assert result["export"]["publication_version"] == "v5"


def test_an_older_publication_of_the_same_dataset_is_behind(tree):
    tree.export("Atlas", _block(V5, "v6", "2026-11-01T00:00:00.000Z"))
    result = _ok(check_cap_currency(str(tree.target(OCTOBER)), V5))
    assert result["status"] == "behind"


def test_no_export_carrying_the_url_is_a_stale_export(tree):
    tree.export("Atlas - All Cells", AUGUST)
    result = _ok(check_cap_currency(str(tree.target(AUGUST)), V5))
    assert result["status"] == "export_stale"
    assert result["export"] is None
    assert result["exports_checked"] == [{"filename": "Atlas - All Cells.h5ad", "cap_dataset_url": V4}]


def test_an_export_older_than_the_objects_copy_is_stale(tree):
    tree.export("Atlas", _block(V5, "v4", "2026-08-14T14:42:40.697Z"))
    result = _ok(check_cap_currency(str(tree.target(OCTOBER)), V5))
    assert result["status"] == "export_stale"


def test_no_cap_source_directory_is_a_stale_export(tree):
    result = _ok(check_cap_currency(str(tree.target(OCTOBER)), V5))
    assert result["status"] == "export_stale"
    assert result["exports_checked"] == []


def test_an_object_without_a_cap_block_is_absent_and_still_gets_its_export(tree):
    tree.export("Atlas", OCTOBER)
    result = _ok(check_cap_currency(str(tree.target(None)), V5))
    assert result["status"] == "absent"
    assert result["object"] is None
    assert result["export"]["path"] == str(tree.caps / "Atlas.h5ad")


def test_an_export_without_a_nested_block_is_listed_and_never_matched(tree):
    _write(tree.caps / "Old layout.h5ad", {"cellannotation_schema_version": "1.0.2"})
    tree.export("Atlas", OCTOBER)
    result = _ok(check_cap_currency(str(tree.target(OCTOBER)), V5))
    assert result["status"] == "current"
    assert {"filename": "Old layout.h5ad", "cap_dataset_url": None} in result["exports_checked"]


def test_the_latest_edit_snapshot_is_checked(tree):
    tree.export("Atlas", OCTOBER)
    target = tree.target(AUGUST)
    _write(target.with_name("atlas-r1-wip-3-edit-2026-10-18-00-00-00.h5ad"), {"cap_metadata": OCTOBER})
    result = _ok(check_cap_currency(str(target), V5))
    assert result["filename"] == "atlas-r1-wip-3-edit-2026-10-18-00-00-00.h5ad"
    assert result["status"] == "current"


# --- Refusals --------------------------------------------------------------


def test_two_exports_carrying_the_url_are_refused(tree):
    tree.export("Atlas", OCTOBER)
    tree.export("Atlas copy", OCTOBER)
    result = check_cap_currency(str(tree.target(AUGUST)), V5)
    assert set(result) == {"error"}
    assert "2 exports" in result["error"] and "keep one" in result["error"]


def test_a_cap_export_as_the_path_is_refused(tree):
    export = tree.export("Atlas", OCTOBER)
    result = check_cap_currency(str(export), V5)
    assert set(result) == {"error"}
    assert "is a CAP export" in result["error"]


def test_a_legacy_layout_object_is_refused(tree):
    tree.export("Atlas", OCTOBER)
    target = tree.target(None, uns={"cellannotation_schema_version": "1.0.2"})
    result = check_cap_currency(str(target), V5)
    assert set(result) == {"error"}
    assert "deprecated top-level CAP layout" in result["error"]


def test_an_export_that_cannot_be_read_is_listed_and_never_matched(tree):
    """A download still in progress does not block the check; the current export simply is not there yet."""
    good = tree.export("Atlas", OCTOBER)
    create_truncated_h5ad(tree.caps / "Partial.h5ad", source=good)
    good.unlink()
    result = _ok(check_cap_currency(str(tree.target(AUGUST)), V5))
    assert result["status"] == "export_stale"
    [row] = result["exports_checked"]
    assert row["filename"] == "Partial.h5ad" and row["cap_dataset_url"] is None and row["error"]


def test_a_broken_unrelated_export_does_not_block_the_match(tree):
    good = tree.export("Atlas", OCTOBER)
    create_truncated_h5ad(tree.caps / "Other lineage.h5ad", source=good)
    assert _ok(check_cap_currency(str(tree.target(OCTOBER)), V5))["status"] == "current"


def test_a_matched_export_in_the_legacy_layout_is_refused(tree):
    """copy_cap_annotations refuses it as a source, so it cannot be the fix."""
    _write(tree.caps / "Mixed.h5ad", {"cap_metadata": OCTOBER, "cellannotation_schema_version": "2.0.1"})
    result = check_cap_currency(str(tree.target(AUGUST)), V5)
    assert set(result) == {"error"}
    assert "Mixed.h5ad carries" in result["error"] and "re-exported from CAP" in result["error"]


def test_another_dataset_is_behind_without_reading_timestamps(tree):
    tree.export("Atlas", OCTOBER)
    no_time = {k: v for k, v in AUGUST.items() if k != "publication_timestamp"}
    assert _ok(check_cap_currency(str(tree.target(no_time)), V5))["status"] == "behind"


def test_a_missing_timestamp_on_the_same_dataset_is_refused(tree):
    tree.export("Atlas", OCTOBER)
    no_time = {k: v for k, v in OCTOBER.items() if k != "publication_timestamp"}
    result = check_cap_currency(str(tree.target(no_time)), V5)
    assert set(result) == {"error"}
    assert "object's CAP block has no publication_timestamp" in result["error"]


def test_a_path_outside_the_layout_is_refused(tmp_path):
    result = check_cap_currency(str(_write(tmp_path / "loose.h5ad", {})), V5)
    assert set(result) == {"error"}
    assert "integrated-objects" in result["error"]


def test_a_missing_file_keeps_the_tools_own_message(tree):
    result = check_cap_currency(str(tree.integrated / "absent.h5ad"), V5)
    assert set(result) == {"error"}
    assert "File not found" in result["error"]
