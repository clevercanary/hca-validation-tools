"""Tests for rename_cell_ids.

The fixture (``create_hca_h5ad`` / ``HCA_TEST_ROWS`` in ``testing.py``)
mirrors the defect the tool was built for (#533): two ID families that share
a prefix because one family lost its distinguishing segment, with the
surviving distinction held only in an obs column. The index is deliberately
named ``cellID`` — the breast integrated object's name — so the
default-``_index`` assumption can't creep back in; one test covers the
default name.
"""

import json
from pathlib import Path

import anndata as ad
import h5py
import numpy as np
import pytest

from hca_anndata_tools import rename_cell_ids
from hca_anndata_tools.testing import HCA_TEST_ROWS, create_hca_h5ad

B1_IDS = [cell_id for cell_id, sample in HCA_TEST_ROWS if sample == "B1_0023"]


@pytest.fixture
def hca_path(tmp_path) -> Path:
    return create_hca_h5ad(tmp_path / "test.h5ad")


def assert_no_snapshot_written(path: Path) -> None:
    assert not list(path.parent.glob("*-edit-*.h5ad"))


def test_rename_happy_path(hca_path):
    before = ad.read_h5ad(hca_path)

    result = rename_cell_ids(
        str(hca_path),
        column="sample_id",
        value="B1_0023",
        prefix_from="MH_mix_",
        prefix_to="MH_mix_BR1_",
    )

    assert "error" not in result
    assert result["n_selected"] == len(B1_IDS)
    assert result["n_renamed"] == result["n_selected"]
    assert result["examples"][0] == ["MH_mix_AAA", "MH_mix_BR1_AAA"]

    after = ad.read_h5ad(result["output_path"])
    # Selected rows renamed, everything else untouched, order preserved.
    expected = [
        "MH_mix_BR1_" + cell_id[len("MH_mix_") :] if sample == "B1_0023" else cell_id
        for cell_id, sample in HCA_TEST_ROWS
    ]
    assert list(after.obs_names) == expected
    # No rows moved: per-row data still aligns by position.
    assert list(after.obs["sample_id"]) == list(before.obs["sample_id"])
    np.testing.assert_array_equal(after.X, before.X)
    np.testing.assert_array_equal(after.obsm["X_umap"], before.obsm["X_umap"])
    # The original file was not modified.
    assert list(ad.read_h5ad(hca_path).obs_names) == list(before.obs_names)


def test_rename_preserves_index_attr_name(hca_path):
    result = rename_cell_ids(
        str(hca_path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )
    with h5py.File(result["output_path"], "r") as f:
        assert f["obs"].attrs["_index"] == "cellID"
        assert "cellID" in f["obs"]


def test_rename_writes_edit_log(hca_path):
    result = rename_cell_ids(
        str(hca_path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )
    after = ad.read_h5ad(result["output_path"])

    log = json.loads(after.uns["provenance"]["edit_history"])
    (entry,) = [e for e in log if e["operation"] == "rename_cell_ids"]
    assert entry["details"]["column"] == "sample_id"
    assert entry["details"]["value"] == "B1_0023"
    assert entry["details"]["n_renamed"] == len(B1_IDS)


def test_rename_default_index_name(tmp_path):
    """A file whose obs index uses anndata's default ``_index`` name works too."""
    path = create_hca_h5ad(tmp_path / "test.h5ad", index_name=None)
    result = rename_cell_ids(str(path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="X_")
    assert "error" not in result
    assert result["n_renamed"] == len(B1_IDS)


def test_rename_non_categorical_selector(tmp_path):
    """The selector column read must handle plain string datasets, not just
    categoricals."""
    path = create_hca_h5ad(tmp_path / "test.h5ad", categorical_sample=False)
    result = rename_cell_ids(
        str(path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )
    assert "error" not in result
    assert result["n_selected"] == len(B1_IDS)


def test_rename_refuses_zero_matches(hca_path):
    result = rename_cell_ids(str(hca_path), column="sample_id", value="nope", prefix_from="MH_mix_", prefix_to="X_")
    assert "no rows match" in result["error"]


def test_rename_refuses_missing_column(hca_path):
    result = rename_cell_ids(str(hca_path), column="donor", value="B1_0023", prefix_from="MH_mix_", prefix_to="X_")
    assert "not present" in result["error"]


def test_rename_refuses_index_as_selector(hca_path):
    result = rename_cell_ids(str(hca_path), column="cellID", value="MH_mix_AAA", prefix_from="MH_mix_", prefix_to="X_")
    assert "obs index" in result["error"]


def test_rename_refuses_prefix_disagreement(hca_path):
    """Selected rows that don't carry prefix_from mean the two witnesses —
    selector and substitution — disagree; nothing may be written."""
    result = rename_cell_ids(str(hca_path), column="sample_id", value="N_0123", prefix_from="MH_mix_", prefix_to="X_")
    assert "do not start with" in result["error"]
    assert "2 of 4" in result["error"]  # the two N1105_epi_* cells
    assert_no_snapshot_written(hca_path)


def test_rename_refuses_collision(tmp_path):
    """A rename that would produce a duplicate ID is refused and the file left
    untouched — introducing collisions is the defect the tool exists to fix."""
    path = create_hca_h5ad(tmp_path / "test.h5ad", extra_rows=[("MH_mix_BR1_AAA", "N_0123")])
    before = list(ad.read_h5ad(path).obs_names)

    result = rename_cell_ids(
        str(path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )

    assert "duplicate cell IDs" in result["error"]
    assert "MH_mix_BR1_AAA" in result["error"]
    assert list(ad.read_h5ad(path).obs_names) == before
    assert_no_snapshot_written(path)


def test_rename_refuses_cellxgene_layout(sample_h5ad):
    """CellxGENE-layout files (e.g. CAP exports) are refused outright: the
    export's source system is the record of truth, and a local rename forks
    it. Read-only, so the session-scoped fixture is safe to share."""
    result = rename_cell_ids(str(sample_h5ad), column="tissue", value="brain", prefix_from="cell_", prefix_to="c_")
    assert "CellxGENE" in result["error"]


def test_rename_missing_file():
    result = rename_cell_ids("/nonexistent/file.h5ad", column="a", value="b", prefix_from="x_", prefix_to="y_")
    assert "File not found" in result["error"]


@pytest.mark.parametrize(
    ("column", "value", "prefix_from", "prefix_to", "expected"),
    [
        (7, "B1_0023", "MH_mix_", "X_", "must be strings"),
        ("sample_id", None, "MH_mix_", "X_", "must be strings"),
        ("obs/sample_id", "B1_0023", "MH_mix_", "X_", "cannot contain '/'"),
        ("  ", "B1_0023", "MH_mix_", "X_", "be blank"),
        ("sample_id", "B1_0023", "", "X_", "non-empty"),
        ("sample_id", "B1_0023", "MH_mix_", "MH_mix_", "identical"),
        ("sample_id", "B1_0023", "MH_mix_", 3, "must be a string"),
    ],
)
def test_rename_refuses_malformed_arguments(hca_path, column, value, prefix_from, prefix_to, expected):
    """Argument shape is checked before any file is opened, and every problem
    is reported — MCP callers arrive as decoded JSON with no type checking."""
    result = rename_cell_ids(str(hca_path), column=column, value=value, prefix_from=prefix_from, prefix_to=prefix_to)
    assert expected in result["error"]
    assert_no_snapshot_written(hca_path)
