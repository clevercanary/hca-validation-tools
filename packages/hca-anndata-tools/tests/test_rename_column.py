"""Tests for rename_obs_column."""

import json

import anndata as ad
import h5py
import numpy as np
import pandas as pd

from hca_anndata_tools._io import read_obs_column_names
from hca_anndata_tools.rename_column import rename_obs_column
from hca_anndata_tools.write import EDIT_LOG_KEY


def _make(path, columns=None, uns=None):
    """Write a small HCA-layout h5ad with the given obs columns."""
    n = 3
    base = {"donor_id": pd.Categorical(["d1", "d2", "d1"])}
    base.update(columns or {})
    obs = pd.DataFrame(base, index=pd.Index([f"c{i}" for i in range(n)], name="cellID"))
    adata = ad.AnnData(X=np.zeros((n, 2), dtype=np.float32), obs=obs)
    adata.uns.update(uns or {})
    adata.write_h5ad(path, compression="gzip")
    return str(path)


def _no_snapshot(path):
    return not any("-edit-" in p.name for p in path.parent.iterdir())


# --- the happy path ----------------------------------------------------------


def test_rename_preserves_values_dtype_categories_and_position(tmp_path):
    """A rename is invisible to everything except the name."""
    path = _make(
        tmp_path / "t.h5ad",
        {
            "before": pd.Categorical(["x", "y", "x"]),
            "cell_type_label": pd.Categorical(["T cell", "B cell", "T cell"]),
            "after": pd.Categorical(["p", "q", "p"]),
        },
    )
    order_before = read_obs_column_names(path)

    result = rename_obs_column(path, "cell_type_label", "author_cell_type")

    assert "error" not in result
    out = ad.read_h5ad(result["output_path"])
    col = out.obs["author_cell_type"]
    assert list(col) == ["T cell", "B cell", "T cell"]
    assert isinstance(col.dtype, pd.CategoricalDtype)
    assert set(col.cat.categories) == {"T cell", "B cell"}
    assert "cell_type_label" not in out.obs.columns
    # Position preserved, not appended.
    expected = [("author_cell_type" if c == "cell_type_label" else c) for c in order_before]
    assert read_obs_column_names(result["output_path"]) == expected


def test_rename_preserves_compression(tmp_path):
    """An HDF5 link rename moves no data, so the filter settings ride along."""
    path = _make(tmp_path / "t.h5ad", {"producer": pd.Categorical(["a", "b", "a"])})
    with h5py.File(path, "r") as f:
        before = f["obs"]["producer"]["codes"].compression
    assert before == "gzip", "fixture must be compressed or this test proves nothing"

    result = rename_obs_column(path, "producer", "renamed")

    assert "error" not in result
    with h5py.File(result["output_path"], "r") as f:
        assert f["obs"]["renamed"]["codes"].compression == before


def test_rename_moves_the_palette_the_column_owns(tmp_path):
    """A palette left under the old key is orphaned, which the schema
    validator reports as a colors field with no matching obs column."""
    path = _make(
        tmp_path / "t.h5ad",
        {"tissue_label": pd.Categorical(["a", "b", "a"])},
        uns={"tissue_label_colors": np.array(["#111111", "#222222"], dtype=object)},
    )

    result = rename_obs_column(path, "tissue_label", "surgical_procedure")

    assert "error" not in result
    assert result["uns_key_renamed"] == "surgical_procedure_colors"
    out = ad.read_h5ad(result["output_path"])
    assert "tissue_label_colors" not in out.uns
    assert list(out.uns["surgical_procedure_colors"]) == ["#111111", "#222222"]


def test_rename_into_a_schema_named_column_is_allowed(tmp_path):
    """The motivating case: cell_type_label holds the authors' own calls, and
    author_cell_type is the schema's name for exactly that. Unlike a drop, a
    rename loses nothing, so no schema-tier refusal applies."""
    path = _make(tmp_path / "t.h5ad", {"cell_type_label": pd.Categorical(["T cell", "B cell", "T cell"])})

    result = rename_obs_column(path, "cell_type_label", "author_cell_type")

    assert "error" not in result
    assert "author_cell_type" in ad.read_h5ad(result["output_path"]).obs.columns


def test_rename_records_an_edit_log_entry(tmp_path):
    path = _make(tmp_path / "t.h5ad", {"old": pd.Categorical(["a", "b", "a"])})

    result = rename_obs_column(path, "old", "new")

    log = json.loads(ad.read_h5ad(result["output_path"]).uns["provenance"][EDIT_LOG_KEY])
    assert log[-1]["operation"] == "rename_obs_column"
    assert log[-1]["details"]["column"] == "old"
    assert log[-1]["details"]["new_name"] == "new"


def test_two_renames_in_succession_both_survive(tmp_path):
    """nee2023 needs two renames back to back — the shape that used to destroy
    the first snapshot before #598. snapshot_copy waits out the boundary."""
    path = _make(
        tmp_path / "t.h5ad",
        {"cell_type_label": pd.Categorical(["T", "B", "T"]), "tissue_label": pd.Categorical(["a", "b", "a"])},
    )

    first = rename_obs_column(path, "cell_type_label", "author_cell_type")
    assert "error" not in first
    second = rename_obs_column(first["output_path"], "tissue_label", "surgical_procedure")
    assert "error" not in second

    out = ad.read_h5ad(second["output_path"])
    assert {"author_cell_type", "surgical_procedure"} <= set(out.obs.columns)
    assert not {"cell_type_label", "tissue_label"} & set(out.obs.columns)


# --- the destination rule ----------------------------------------------------


def test_rename_overwrites_a_destination_that_is_entirely_empty(tmp_path):
    """A column holding nothing carries no information to lose."""
    path = _make(
        tmp_path / "t.h5ad",
        {
            "producer": pd.Categorical(["a", "b", "a"]),
            "author_cell_type": pd.Categorical([None, None, None], categories=["unused"]),
        },
    )

    result = rename_obs_column(path, "producer", "author_cell_type")

    assert "error" not in result
    out = ad.read_h5ad(result["output_path"])
    assert list(out.obs["author_cell_type"]) == ["a", "b", "a"]
    # The replaced column's own entry must not survive as a duplicate.
    order = read_obs_column_names(result["output_path"])
    assert order.count("author_cell_type") == 1


def test_rename_refuses_a_partially_populated_destination(tmp_path):
    """One value is enough to make it not-empty — the check answers 'can this
    be overwritten without losing anything', not 'is it mostly empty'."""
    path = _make(
        tmp_path / "t.h5ad",
        {"producer": pd.Categorical(["a", "b", "a"]), "nearly": pd.Categorical([None, None, "kept"])},
    )

    result = rename_obs_column(path, "producer", "nearly")

    assert "error" in result
    assert "already exists" in result["error"]
    assert _no_snapshot(tmp_path / "t.h5ad")


def test_rename_refuses_an_int_destination_even_when_zeroed(tmp_path):
    """Integers have no null representation, so an int column is never empty —
    the conservative direction, since 0 may be a real measurement."""
    path = _make(tmp_path / "t.h5ad", {"producer": pd.Categorical(["a", "b", "a"])})
    adata = ad.read_h5ad(path)
    adata.obs["counts"] = np.zeros(3, dtype=np.int64)
    adata.write_h5ad(path)

    result = rename_obs_column(path, "producer", "counts")

    assert "error" in result
    assert "already exists" in result["error"]


# --- the remaining guards ----------------------------------------------------


def test_rename_refuses_a_missing_source(tmp_path):
    path = _make(tmp_path / "t.h5ad")

    result = rename_obs_column(path, "nonexistent", "whatever")

    assert "error" in result
    assert "not present in obs" in result["error"]
    assert _no_snapshot(tmp_path / "t.h5ad")


def test_rename_refuses_the_obs_index(tmp_path):
    """The index is a dataset in the obs group like any column, so a caller
    can name it; moving it destroys the file's cell identities."""
    path = _make(tmp_path / "t.h5ad")

    result = rename_obs_column(path, "cellID", "something")

    assert "error" in result
    assert "obs index" in result["error"]
    assert _no_snapshot(tmp_path / "t.h5ad")


def test_rename_refuses_names_containing_a_slash(tmp_path):
    """h5py resolves '/X' from the file root, so an unguarded move would
    relocate the expression matrix out of the file's reach."""
    path = _make(tmp_path / "t.h5ad", {"producer": pd.Categorical(["a", "b", "a"])})

    for column, new_name in (("/X", "safe"), ("producer", "/X"), ("producer", "  ")):
        result = rename_obs_column(path, column, new_name)
        assert "error" in result, f"{column!r} -> {new_name!r} must be refused"
        assert "cannot contain" in result["error"]
        # Reported once, not also as "not present in obs": a path-shaped name is
        # necessarily absent too, and saying both sends the caller hunting for a
        # typo instead of reading the path-name rule (drop.py makes the same
        # exclusion, and this assertion is what keeps the two agreeing).
        assert "not present in obs" not in result["error"]

    with h5py.File(path, "r") as f:
        assert "X" in f


def test_rename_updates_a_batch_condition_reference(tmp_path):
    """uns['batch_condition'] names the columns defining the experiment's
    batches. A rename knows exactly what to point it at — the same column still
    defines the batches, only its name changed. Refusing would be a dead end:
    set_uns validates entries against the obs columns present, so the new name
    cannot be written before the rename, and the rename could not happen while
    the old name was referenced."""
    path = _make(
        tmp_path / "t.h5ad",
        {"batchy": pd.Categorical(["a", "b", "a"])},
        uns={"batch_condition": np.array(["batchy", "donor_id"], dtype=object)},
    )

    result = rename_obs_column(path, "batchy", "renamed")

    assert "error" not in result
    assert result["batch_condition_updated"] is True
    out = ad.read_h5ad(result["output_path"])
    assert list(out.uns["batch_condition"]) == ["renamed", "donor_id"]  # order and siblings kept
    assert "renamed" in out.obs.columns


def test_rename_leaves_an_unrelated_batch_condition_alone(tmp_path):
    path = _make(
        tmp_path / "t.h5ad",
        {"producer": pd.Categorical(["a", "b", "a"])},
        uns={"batch_condition": np.array(["donor_id"], dtype=object)},
    )

    result = rename_obs_column(path, "producer", "renamed")

    assert result["batch_condition_updated"] is False
    assert list(ad.read_h5ad(result["output_path"]).uns["batch_condition"]) == ["donor_id"]


def test_rename_refuses_a_no_op(tmp_path):
    path = _make(tmp_path / "t.h5ad", {"same": pd.Categorical(["a", "b", "a"])})

    result = rename_obs_column(path, "same", "same")

    assert "error" in result
    assert "already the column's name" in result["error"]


def test_rename_reports_every_problem_at_once(tmp_path):
    """A caller who got two things wrong learns both in one round trip."""
    path = _make(tmp_path / "t.h5ad")

    result = rename_obs_column(path, "missing", "/X")

    assert "error" in result
    assert "cannot contain" in result["error"]
    assert "not present in obs" in result["error"]


def test_rename_missing_file():
    result = rename_obs_column("/nonexistent/path/file.h5ad", "a", "b")

    assert "error" in result


def test_rename_replaces_an_orphaned_palette_under_the_destination_name(tmp_path):
    """A palette can sit under the destination name with no matching column —
    the exact state the validator complains about. move() would raise on it."""
    path = _make(
        tmp_path / "t.h5ad",
        {"tissue_label": pd.Categorical(["a", "b", "a"])},
        uns={
            "tissue_label_colors": np.array(["#111111", "#222222"], dtype=object),
            "surgical_procedure_colors": np.array(["#999999"], dtype=object),  # orphan
        },
    )

    result = rename_obs_column(path, "tissue_label", "surgical_procedure")

    assert "error" not in result
    out = ad.read_h5ad(result["output_path"])
    assert list(out.uns["surgical_procedure_colors"]) == ["#111111", "#222222"]  # source's wins


def test_rename_over_an_empty_destination_discards_its_palette(tmp_path):
    """The overwritten column's palette must not survive to describe the
    incoming data. A length mismatch is a validator error; a length *match*
    is worse, because nothing reports silently wrong colors."""
    path = _make(
        tmp_path / "t.h5ad",
        {
            "producer": pd.Categorical(["a", "b", "c"]),
            "author_cell_type": pd.Categorical([None, None, None], categories=["unused"]),
        },
        uns={"author_cell_type_colors": np.array(["#111111", "#222222"], dtype=object)},
    )

    result = rename_obs_column(path, "producer", "author_cell_type")

    assert "error" not in result
    out = ad.read_h5ad(result["output_path"])
    assert list(out.obs["author_cell_type"]) == ["a", "b", "c"]
    assert "author_cell_type_colors" not in out.uns, "stale palette now describes different data"
