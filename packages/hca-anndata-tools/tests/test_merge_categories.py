"""Tests for merge_obs_categories."""

import json
from pathlib import Path

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pytest

from hca_anndata_tools._io import read_edit_log_h5py
from hca_anndata_tools.merge_categories import merge_obs_categories

# The real split this tool exists for, from nee2023's tissue_label (#527):
# 11,635 cells under a misspelling of the category above them.
_VALUES = ["Prophylactic Mastectomy"] * 5 + ["Prophylatctic Mastectomy"] * 3 + ["Contralateral"] * 2
_TYPO = "Prophylatctic Mastectomy"
_CORRECT = "Prophylactic Mastectomy"


def _make(path, column="tissue_label", values=None, compression="gzip", **extra_obs):
    obs = pd.DataFrame(
        {column: pd.Categorical(values if values is not None else _VALUES), **extra_obs},
        index=pd.Index([f"c{i}" for i in range(len(values if values is not None else _VALUES))], name="cellID"),
    )
    n = len(obs)
    adata = ad.AnnData(X=np.zeros((n, 2), dtype=np.float32), obs=obs)
    adata.write_h5ad(path, compression=compression)
    return path


def _no_snapshot(path):
    return not any("-edit-" in p.name for p in Path(path).parent.iterdir())


# --- the happy path ----------------------------------------------------------


def test_merge_folds_the_typo_into_its_correct_sibling(tmp_path):
    path = _make(tmp_path / "nee.h5ad")

    result = merge_obs_categories(str(path), "tissue_label", _TYPO, _CORRECT)

    assert "error" not in result
    out = ad.read_h5ad(result["output_path"])
    assert _TYPO not in out.obs["tissue_label"].cat.categories
    assert (out.obs["tissue_label"] == _CORRECT).sum() == 8  # 5 + the 3 recoded
    assert len(out.obs) == 10, "cell count is preserved — a merge recodes, it never drops rows"


def test_merge_reports_the_recoded_count(tmp_path):
    """The caller confirms the split was the size they expected — for nee2023,
    11,635 cells."""
    path = _make(tmp_path / "nee.h5ad")

    result = merge_obs_categories(str(path), "tissue_label", _TYPO, _CORRECT)

    assert result["cells_recoded"] == 3
    assert result["categories_remaining"] == 2
    assert result["from_value"] == _TYPO and result["to_value"] == _CORRECT


def test_merge_preserves_compression(tmp_path):
    """replace_categorical_column carries the codes dataset's storage settings
    across the delete-and-recreate."""
    path = _make(tmp_path / "nee.h5ad", compression="gzip")

    result = merge_obs_categories(str(path), "tissue_label", _TYPO, _CORRECT)

    with h5py.File(result["output_path"], "r") as f:
        assert f["obs/tissue_label/codes"].compression == "gzip"


def test_merge_writes_an_edit_log_entry(tmp_path):
    path = _make(tmp_path / "nee.h5ad")

    result = merge_obs_categories(str(path), "tissue_label", _TYPO, _CORRECT)

    with h5py.File(result["output_path"], "r") as f:
        entry = json.loads(read_edit_log_h5py(f))[-1]
    assert entry["operation"] == "merge_obs_categories"
    assert entry["details"] == {
        "column": "tissue_label",
        "from_value": _TYPO,
        "to_value": _CORRECT,
        "cells_recoded": 3,
    }


def test_merge_keeps_the_original(tmp_path):
    """The snapshot chain: the source survives, so a wrong merge is re-runnable
    from it (#619)."""
    path = _make(tmp_path / "nee.h5ad")

    merge_obs_categories(str(path), "tissue_label", _TYPO, _CORRECT)

    assert Path(path).is_file()
    assert _TYPO in ad.read_h5ad(path).obs["tissue_label"].cat.categories


# --- refusals ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("from_value", "to_value", "expected"),
    [
        ("Nonexistent", _CORRECT, "Nonexistent"),
        (_TYPO, "Nonexistent", "Nonexistent"),
        ("Nope", "Nope2", "Nope"),
    ],
)
def test_merge_refuses_an_absent_value(tmp_path, from_value, to_value, expected):
    """Both must already exist: creating a category is a different operation,
    and a missing value is a caller mistake, not a silent no-op."""
    path = _make(tmp_path / "nee.h5ad")

    result = merge_obs_categories(str(path), "tissue_label", from_value, to_value)

    assert "error" in result
    assert expected in result["error"]
    assert _no_snapshot(path)


def test_merge_refuses_a_non_categorical_column(tmp_path):
    """This edits the categories array, not values row by row."""
    path = _make(tmp_path / "nee.h5ad", n_counts=np.arange(10, dtype=float))

    result = merge_obs_categories(str(path), "n_counts", "1.0", "2.0")

    assert "error" in result
    assert "not a categorical column" in result["error"]
    assert _no_snapshot(path)


def test_merge_refuses_a_derived_label_with_its_term_id_present(tmp_path):
    """The coherence guard: merging a label alone desyncs it from the term ID
    it is derived from, and populate_labels regenerates *from* the term ID."""
    path = _make(
        tmp_path / "nee.h5ad",
        column="cell_type",
        values=["T cell"] * 5 + ["T cel"] * 3 + ["B cell"] * 2,
        cell_type_ontology_term_id=pd.Categorical(["CL:0000084"] * 10),
    )

    result = merge_obs_categories(str(path), "cell_type", "T cel", "T cell")

    assert "error" in result
    assert "cell_type_ontology_term_id" in result["error"]
    assert "populate_labels" in result["error"]
    assert _no_snapshot(path)


def test_merge_refuses_a_column_carrying_a_palette(tmp_path):
    """uns['<col>_colors'] is positionally aligned to the categories, so
    dropping one shifts every colour after it — and the validator only checks
    the palette's length, so a silently recoloured file can still pass."""
    path = _make(tmp_path / "nee.h5ad")
    adata = ad.read_h5ad(path)
    adata.uns["tissue_label_colors"] = np.array(["#111", "#222", "#333"], dtype=object)
    adata.write_h5ad(path)

    result = merge_obs_categories(str(path), "tissue_label", _TYPO, _CORRECT)

    assert "error" in result
    assert "tissue_label_colors" in result["error"]
    assert _no_snapshot(path)


def test_merge_allows_a_column_named_by_batch_condition(tmp_path):
    """Unlike a drop or a rename, a merge leaves the column's name and identity
    intact, so the declaration still names a real column — nothing dangles."""
    path = _make(tmp_path / "nee.h5ad")
    adata = ad.read_h5ad(path)
    adata.uns["batch_condition"] = np.array(["tissue_label"], dtype=object)
    adata.write_h5ad(path)

    result = merge_obs_categories(str(path), "tissue_label", _TYPO, _CORRECT)

    assert "error" not in result
    out = ad.read_h5ad(result["output_path"])
    assert list(out.uns["batch_condition"]) == ["tissue_label"], "declaration untouched"


def test_merge_refuses_the_obs_index(tmp_path):
    path = _make(tmp_path / "nee.h5ad")

    result = merge_obs_categories(str(path), "cellID", "c1", "c2")

    assert "error" in result
    assert "obs index" in result["error"]
    assert _no_snapshot(path)


def test_merge_refuses_a_slash_name(tmp_path):
    """h5py resolves a '/' name as a link path — the check every obs mutation
    owes (guards.malformed_name_problems)."""
    path = _make(tmp_path / "nee.h5ad")

    result = merge_obs_categories(str(path), "/X", "a", "b")

    assert "error" in result
    assert "/X" in result["error"]
    assert _no_snapshot(path)


def test_merge_refuses_identical_values(tmp_path):
    path = _make(tmp_path / "nee.h5ad")

    result = merge_obs_categories(str(path), "tissue_label", _CORRECT, _CORRECT)

    assert "error" in result
    assert "nothing to merge" in result["error"]
    assert _no_snapshot(path)


def test_merge_refuses_an_absent_column(tmp_path):
    path = _make(tmp_path / "nee.h5ad")

    result = merge_obs_categories(str(path), "no_such_column", "a", "b")

    assert "error" in result
    assert "not present in obs" in result["error"]
    assert _no_snapshot(path)


def test_merge_refuses_non_string_arguments(tmp_path):
    """MCP-exposed, so arguments arrive as decoded JSON and may hold numbers."""
    path = _make(tmp_path / "nee.h5ad")

    result = merge_obs_categories(str(path), "tissue_label", 1, _CORRECT)  # pyright: ignore[reportArgumentType]

    assert "error" in result
    assert "must be strings" in result["error"]


def test_merge_missing_file():
    result = merge_obs_categories("/nonexistent/file.h5ad", "col", "a", "b")
    assert "error" in result
    assert "File not found" in result["error"]
