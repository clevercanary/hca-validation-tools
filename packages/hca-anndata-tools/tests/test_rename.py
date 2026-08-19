"""Tests for rename_cell_ids.

The fixture mirrors the defect the tool was built for (#533): two ID
families that share a prefix because one family lost its distinguishing
segment, with the surviving distinction held only in an obs column. The
index is deliberately named ``cellID`` — the breast integrated object's
name — so the default-``_index`` assumption can't creep back in; one test
covers the default name.
"""

from pathlib import Path

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pytest

from hca_anndata_tools import rename_cell_ids
from hca_anndata_tools.testing import create_sample_h5ad

# The collapsed family: B1 cells wearing the N family's prefix. Interleaved
# with the N cells so a correct rename must select by column value, not by
# position.
COLLAPSED_IDS = ["MH_mix_AAA", "MH_mix_CCC", "MH_mix_GGG"]
N_IDS = ["MH_mix_TTT", "MH_mix_ACG", "N1105_epi_AAA", "N1105_epi_CCC"]


def make_hca_h5ad(
    path: Path,
    index_name: str | None = "cellID",
    extra_n_id: str | None = None,
    categorical_sample: bool = True,
) -> Path:
    """Write a small HCA-layout file with the two-family ID shape.

    ``extra_n_id`` appends one more unselected cell, letting a test plant a
    pre-existing ID that a rename would collide with.
    """
    ids = []
    samples = []
    for i, cell_id in enumerate(COLLAPSED_IDS):
        ids.append(cell_id)
        samples.append("B1_0023")
        ids.append(N_IDS[i])
        samples.append("N_0123")
    ids.append(N_IDS[3])
    samples.append("N_0123")
    if extra_n_id is not None:
        ids.append(extra_n_id)
        samples.append("N_0123")

    n_obs = len(ids)
    rng = np.random.default_rng(7)
    obs = pd.DataFrame(
        {
            "sample_id": pd.Categorical(samples) if categorical_sample else samples,
            "n_counts": rng.integers(100, 500, n_obs).astype(np.float32),
        },
        index=pd.Index(ids, name=index_name),
    )
    var = pd.DataFrame(index=pd.Index([f"ENSG{i:011d}" for i in range(5)]))
    adata = ad.AnnData(X=rng.standard_normal((n_obs, 5)).astype(np.float32), obs=obs, var=var)
    adata.obsm["X_umap"] = rng.standard_normal((n_obs, 2)).astype(np.float32)
    adata.uns["title"] = "Test HCA file"  # no schema_version: HCA layout
    adata.write_h5ad(path)
    return path


@pytest.fixture
def hca_path(tmp_path) -> Path:
    return make_hca_h5ad(tmp_path / "test.h5ad")


def test_rename_happy_path(hca_path):
    before = ad.read_h5ad(hca_path)

    result = rename_cell_ids(
        str(hca_path),
        where={"sample_id": "B1_0023"},
        prefix_from="MH_mix_",
        prefix_to="MH_mix_BR1_",
    )

    assert "error" not in result
    assert result["n_selected"] == len(COLLAPSED_IDS)
    assert result["n_renamed"] == result["n_selected"]
    assert result["examples"][0] == ["MH_mix_AAA", "MH_mix_BR1_AAA"]

    after = ad.read_h5ad(result["output_path"])
    # Selected rows renamed, everything else untouched, order preserved.
    expected = [
        "MH_mix_BR1_" + cell_id[len("MH_mix_") :] if sample == "B1_0023" else cell_id
        for cell_id, sample in zip(before.obs_names, before.obs["sample_id"], strict=True)
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
        str(hca_path), where={"sample_id": "B1_0023"}, prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )
    with h5py.File(result["output_path"], "r") as f:
        assert f["obs"].attrs["_index"] == "cellID"
        assert "cellID" in f["obs"]


def test_rename_writes_edit_log(hca_path):
    result = rename_cell_ids(
        str(hca_path), where={"sample_id": "B1_0023"}, prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )
    after = ad.read_h5ad(result["output_path"])
    import json

    log = json.loads(after.uns["provenance"]["edit_history"])
    (entry,) = [e for e in log if e["operation"] == "rename_cell_ids"]
    assert entry["details"]["where"] == {"sample_id": "B1_0023"}
    assert entry["details"]["n_renamed"] == len(COLLAPSED_IDS)


def test_rename_default_index_name(tmp_path):
    """A file whose obs index uses anndata's default ``_index`` name works too."""
    path = make_hca_h5ad(tmp_path / "test.h5ad", index_name=None)
    result = rename_cell_ids(str(path), where={"sample_id": "B1_0023"}, prefix_from="MH_mix_", prefix_to="X_")
    assert "error" not in result
    assert result["n_renamed"] == len(COLLAPSED_IDS)


def test_rename_non_categorical_selector(tmp_path):
    """The selector column read must handle plain string datasets, not just
    categoricals."""
    path = make_hca_h5ad(tmp_path / "test.h5ad", categorical_sample=False)
    result = rename_cell_ids(str(path), where={"sample_id": "B1_0023"}, prefix_from="MH_mix_", prefix_to="MH_mix_BR1_")
    assert "error" not in result
    assert result["n_selected"] == len(COLLAPSED_IDS)


def test_rename_refuses_zero_matches(hca_path):
    result = rename_cell_ids(str(hca_path), where={"sample_id": "nope"}, prefix_from="MH_mix_", prefix_to="X_")
    assert "no rows match" in result["error"]


def test_rename_refuses_missing_column(hca_path):
    result = rename_cell_ids(str(hca_path), where={"donor": "B1_0023"}, prefix_from="MH_mix_", prefix_to="X_")
    assert "not present" in result["error"]


def test_rename_refuses_index_as_selector(hca_path):
    result = rename_cell_ids(str(hca_path), where={"cellID": "MH_mix_AAA"}, prefix_from="MH_mix_", prefix_to="X_")
    assert "obs index" in result["error"]


def test_rename_refuses_prefix_disagreement(hca_path):
    """Selected rows that don't carry prefix_from mean the two witnesses —
    selector and substitution — disagree; nothing may be written."""
    result = rename_cell_ids(str(hca_path), where={"sample_id": "N_0123"}, prefix_from="MH_mix_", prefix_to="X_")
    assert "do not start with" in result["error"]
    assert "2 of 4" in result["error"]  # the two N1105_epi_* cells


def test_rename_refuses_collision(tmp_path):
    """A rename that would produce a duplicate ID is refused and the file left
    untouched — introducing collisions is the defect the tool exists to fix."""
    path = make_hca_h5ad(tmp_path / "test.h5ad", extra_n_id="MH_mix_BR1_AAA")
    before = list(ad.read_h5ad(path).obs_names)

    result = rename_cell_ids(str(path), where={"sample_id": "B1_0023"}, prefix_from="MH_mix_", prefix_to="MH_mix_BR1_")

    assert "duplicate cell IDs" in result["error"]
    assert "MH_mix_BR1_AAA" in result["error"]
    assert list(ad.read_h5ad(path).obs_names) == before


def test_rename_refuses_cellxgene_layout(tmp_path):
    """CellxGENE-layout files (e.g. CAP exports) are refused outright: the
    export's source system is the record of truth, and a local rename forks it."""
    path = create_sample_h5ad(tmp_path / "cxg.h5ad")  # sets uns['schema_version']
    result = rename_cell_ids(str(path), where={"tissue": "brain"}, prefix_from="cell_", prefix_to="c_")
    assert "CellxGENE" in result["error"]


def test_rename_missing_file():
    result = rename_cell_ids("/nonexistent/file.h5ad", where={"a": "b"}, prefix_from="x_", prefix_to="y_")
    assert "File not found" in result["error"]


@pytest.mark.parametrize(
    ("where", "prefix_from", "prefix_to", "expected"),
    [
        ("B1_0023", "MH_mix_", "X_", "exactly one"),  # not a dict
        ({}, "MH_mix_", "X_", "exactly one"),
        ({"a": "b", "c": "d"}, "MH_mix_", "X_", "exactly one"),
        ({"sample_id": 7}, "MH_mix_", "X_", "string value"),
        ({"obs/sample_id": "B1_0023"}, "MH_mix_", "X_", "cannot contain '/'"),
        ({"sample_id": "B1_0023"}, "", "X_", "non-empty"),
        ({"sample_id": "B1_0023"}, "MH_mix_", "MH_mix_", "identical"),
        ({"sample_id": "B1_0023"}, "MH_mix_", 3, "must be a string"),
    ],
)
def test_rename_refuses_malformed_arguments(hca_path, where, prefix_from, prefix_to, expected):
    """Argument shape is checked before any file is opened, and every problem
    is reported — MCP callers arrive as decoded JSON with no type checking."""
    result = rename_cell_ids(str(hca_path), where=where, prefix_from=prefix_from, prefix_to=prefix_to)
    assert expected in result["error"]
    # Nothing was written: no timestamped sibling appeared.
    assert list(hca_path.parent.glob("*.h5ad")) == [hca_path]
