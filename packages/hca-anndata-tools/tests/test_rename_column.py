"""Tests for rename_obs_column."""

import json

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pytest

import hca_anndata_tools.rename_column as rc
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


# --- the happy path ----------------------------------------------------------


def test_rename_preserves_values_dtype_categories_and_position(tmp_path):
    """A rename is invisible to everything except the name.

    Also the motivating case: author_cell_type is itself schema-named, and
    schema names carry no refusal here — a rename loses nothing."""
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


def test_rename_refuses_a_partially_populated_destination(tmp_path, no_snapshot):
    """One value is enough to make it not-empty — the check answers 'can this
    be overwritten without losing anything', not 'is it mostly empty'."""
    path = _make(
        tmp_path / "t.h5ad",
        {"producer": pd.Categorical(["a", "b", "a"]), "nearly": pd.Categorical([None, None, "kept"])},
    )

    result = rename_obs_column(path, "producer", "nearly")

    assert "error" in result
    assert "already exists" in result["error"]
    assert no_snapshot(tmp_path / "t.h5ad")


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


def test_rename_refuses_a_missing_source(tmp_path, no_snapshot):
    path = _make(tmp_path / "t.h5ad")

    result = rename_obs_column(path, "nonexistent", "whatever")

    assert "error" in result
    assert "not present in obs" in result["error"]
    assert no_snapshot(tmp_path / "t.h5ad")


def test_rename_refuses_the_obs_index(tmp_path, no_snapshot):
    """The index is a dataset in the obs group like any column, so a caller
    can name it; moving it destroys the file's cell identities."""
    path = _make(tmp_path / "t.h5ad")

    result = rename_obs_column(path, "cellID", "something")

    assert "error" in result
    assert "obs index" in result["error"]
    assert no_snapshot(tmp_path / "t.h5ad")


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


def test_rename_works_on_a_file_with_no_uns_group(tmp_path):
    """The read phase tolerates a missing uns; the write phase must too."""
    path = tmp_path / "t.h5ad"
    obs = pd.DataFrame(
        {
            "producer": pd.Categorical(["a", "b", "a"]),
            "empty_dest": pd.Categorical([None, None, None], categories=["unused"]),
        },
        index=pd.Index(["c0", "c1", "c2"], name="cellID"),
    )
    ad.AnnData(X=np.zeros((3, 2), dtype=np.float32), obs=obs).write_h5ad(path)
    with h5py.File(path, "a") as f:
        if "uns" in f:
            del f["uns"]

    result = rename_obs_column(str(path), "producer", "empty_dest")

    assert "error" not in result
    assert list(ad.read_h5ad(result["output_path"]).obs["empty_dest"]) == ["a", "b", "a"]


def test_rename_missing_file_names_the_path(tmp_path):
    """A mistyped path gets drop.py's message, not a raw multi-line HDF5 error."""
    result = rename_obs_column(str(tmp_path / "nope.h5ad"), "a", "b")

    assert "error" in result
    assert "File not found" in result["error"]


def test_is_empty_column_short_circuits_on_the_first_populated_chunk(tmp_path, monkeypatch):
    """The scan must stop at the first row that disproves emptiness rather than
    materializing the column. Asserted by counting rows read: a helper that is
    defined but never called reads everything and still returns the right
    answer, which is how this regressed once already."""
    n = rc._SCAN_CHUNK_ROWS * 2 + 5
    path = tmp_path / "t.h5ad"
    obs = pd.DataFrame(
        {"occupied": pd.Categorical(["v"] * n)},  # non-empty from row 0
        index=pd.Index([f"c{i}" for i in range(n)], name="cellID"),
    )
    ad.AnnData(X=np.zeros((n, 1), dtype=np.float32), obs=obs).write_h5ad(path)

    read = []
    real_all_rows = rc._all_rows

    def counting(ds, predicate):
        def counted(chunk):
            read.append(len(chunk))
            return predicate(chunk)

        return real_all_rows(ds, counted)

    monkeypatch.setattr(rc, "_all_rows", counting)

    with h5py.File(path, "r") as f:
        assert rc._is_empty_column(f["obs"], "occupied") is False

    # Both halves matter. Empty `read` means the column was materialized without
    # going through the scanner at all — the exact way this regressed once, with
    # _all_rows defined but never called and every test still green.
    assert read, "_is_empty_column bypassed the chunked scanner"
    assert sum(read) <= rc._SCAN_CHUNK_ROWS, f"read {sum(read)} of {n} rows — the scan did not short-circuit"


# A bare Dataset at uns carries no encoding stamp by construction — the
# malformed shape under test, which anndata warns about before refusing it.
@pytest.mark.filterwarnings("ignore:Element '/uns' was written without encoding metadata")
def test_rename_fails_legibly_on_a_malformed_uns(tmp_path):
    """File.get("uns") can hand back a Dataset on a malformed file. Such a file
    cannot take an edit log, so the rename legitimately fails — but it must say
    something structural rather than raising AttributeError about .get, which is
    what truthiness checks on the result produced."""
    path = tmp_path / "t.h5ad"
    obs = pd.DataFrame(
        {"producer": pd.Categorical(["a", "b", "a"])},
        index=pd.Index(["c0", "c1", "c2"], name="cellID"),
    )
    ad.AnnData(X=np.zeros((3, 2), dtype=np.float32), obs=obs).write_h5ad(path)
    with h5py.File(path, "a") as f:
        if "uns" in f:
            del f["uns"]
        f.create_dataset("uns", data=np.array([1, 2, 3]))  # a Dataset, not a Group

    # A Dataset at uns also stops anndata opening the file, so the public
    # entry point now refuses it first. The structural message below is still
    # the answer for a malformed uns anndata tolerates.
    assert "error" in rename_obs_column(str(path), "producer", "renamed")

    result = rename_obs_column.__wrapped__(str(path), "producer", "renamed")

    assert "error" in result
    assert "has no attribute" not in result["error"], result["error"]
    assert "Dataset" in result["error"]  # names the structural problem
    assert not list(tmp_path.glob("*-edit-*.h5ad")), "no snapshot left behind"


def test_rename_discards_an_orphan_palette_when_the_source_owns_none(tmp_path):
    """A stale palette under the destination name must not be adopted by the
    renamed column. The danger is not a length mismatch, which the validator
    reports — it is a length *match*, which nothing reports."""
    path = _make(
        tmp_path / "t.h5ad",
        {"tissue_label": pd.Categorical(["a", "b", "c"])},  # source owns no palette
        uns={"surgical_procedure_colors": np.array(["#999999"], dtype=object)},
    )

    result = rename_obs_column(path, "tissue_label", "surgical_procedure")

    assert "error" not in result
    assert result["uns_key_renamed"] is None
    out = ad.read_h5ad(result["output_path"])
    assert "surgical_procedure_colors" not in out.uns, "orphan palette adopted by the renamed column"


def test_rename_over_an_empty_destination_replaces_it_completely(tmp_path):
    """An empty destination gives way, and everything that named it goes with
    it. Its palette must not survive to describe the incoming column, and its
    batch_condition entry must not survive as a duplicate of the new name."""
    path = _make(
        tmp_path / "t.h5ad",
        {
            "producer": pd.Categorical(["a", "b", "c"]),
            "author_cell_type": pd.Categorical([None, None, None], categories=["unused"]),
        },
        uns={
            "author_cell_type_colors": np.array(["#111111", "#222222"], dtype=object),
            "batch_condition": np.array(["producer", "author_cell_type"], dtype=object),
        },
    )

    result = rename_obs_column(path, "producer", "author_cell_type")

    assert "error" not in result
    out = ad.read_h5ad(result["output_path"])
    assert list(out.obs["author_cell_type"]) == ["a", "b", "c"]
    # The replaced column's own column-order entry must not linger as a duplicate.
    assert read_obs_column_names(result["output_path"]).count("author_cell_type") == 1
    assert "author_cell_type_colors" not in out.uns, "stale palette now describes different data"
    assert list(out.uns["batch_condition"]) == ["author_cell_type"], "duplicate entry"


def test_rename_refuses_non_string_names(tmp_path, no_snapshot):
    """MCP-exposed, so both names arrive as decoded JSON and may be anything.
    Without a shape check _validate_request leaks "'list' object has no
    attribute 'strip'", which tells a caller nothing.

    The ignores are deliberate: the annotations already reject these
    statically, and the point is the runtime guard protecting MCP callers, who
    get no type checking at all."""
    path = _make(tmp_path / "t.h5ad", {"producer": pd.Categorical(["a", "b", "a"])})

    for column, new_name in (("producer", None), ("producer", 42), (["producer"], "x")):
        result = rename_obs_column(path, column, new_name)  # pyright: ignore[reportArgumentType]

        assert "error" in result, f"{column!r} -> {new_name!r} must be refused"
        assert "must both be strings" in result["error"]
        assert no_snapshot(tmp_path / "t.h5ad")


def test_rename_drops_a_batch_condition_entry_naming_only_the_replaced_column(tmp_path):
    """batch_condition naming only the destination declared the column being
    replaced. Left in place, the name still resolves — to different data — so
    nothing reports it. Same reasoning as discarding the destination's palette."""
    path = _make(
        tmp_path / "t.h5ad",
        {
            "producer": pd.Categorical(["a", "b", "c"]),
            "dest": pd.Categorical([None, None, None], categories=["unused"]),
        },
        uns={"batch_condition": np.array(["dest", "donor_id"], dtype=object)},
    )

    result = rename_obs_column(path, "producer", "dest")

    assert "error" not in result
    assert result["batch_condition_updated"] is True
    out = ad.read_h5ad(result["output_path"])
    assert list(out.obs["dest"]) == ["a", "b", "c"]
    assert list(out.uns["batch_condition"]) == ["donor_id"], "stale entry now names different data"


def _make_cap_file(path, legacy=False):
    """A CAP-annotated file: an annotation set declared in uns, and the
    '--' columns that set names."""
    obs = pd.DataFrame(
        {
            "producer": pd.Categorical(["a", "b", "a"]),
            "myset--cell_fullname": pd.Categorical(["T cell", "B cell", "T cell"]),
        },
        index=pd.Index(["c0", "c1", "c2"], name="cellID"),
    )
    adata = ad.AnnData(X=np.zeros((3, 2), dtype=np.float32), obs=obs)
    block = {"cellannotation_schema_version": "1.0.0", "cellannotation_metadata": {"myset": {}}}
    adata.uns.update(block) if legacy else adata.uns.update({"cap_metadata": dict(block)})
    adata.write_h5ad(path, compression="gzip")
    return str(path)


def test_rename_refuses_a_cap_annotation_column(tmp_path, no_snapshot):
    """CAP material is never patched in place — CAP is the system of record and
    the workflow strips a set wholesale and re-copies it. So a rename cannot
    repair the declaration it would break, and must refuse."""
    path = _make_cap_file(tmp_path / "cap.h5ad")

    result = rename_obs_column(path, "myset--cell_fullname", "myset--renamed")

    assert "error" in result
    assert "CAP annotation-set columns" in result["error"]
    assert no_snapshot(tmp_path / "cap.h5ad")


def test_rename_refuses_a_cap_column_as_the_destination(tmp_path):
    """Renaming a producer column *into* the set's naming convention would
    make it look like a member of a set that does not declare it."""
    path = _make_cap_file(tmp_path / "cap.h5ad")

    result = rename_obs_column(path, "producer", "myset--smuggled")

    assert "error" in result
    assert "CAP annotation-set columns" in result["error"]


def test_rename_refuses_the_legacy_cap_layout(tmp_path, no_snapshot):
    """In the deprecated top-level layout the cap_metadata check sees no
    declaration, so every CAP column would look renamable — refuse the file."""
    path = _make_cap_file(tmp_path / "legacy.h5ad", legacy=True)

    result = rename_obs_column(path, "myset--cell_fullname", "myset--renamed")

    assert "error" in result
    assert "not supported" in result["error"]
    assert no_snapshot(tmp_path / "legacy.h5ad")


def test_rename_allows_a_plain_column_on_a_cap_file(tmp_path):
    """The refusal is about CAP's columns, not about CAP files."""
    path = _make_cap_file(tmp_path / "cap.h5ad")

    result = rename_obs_column(path, "producer", "author_note")

    assert "error" not in result
    assert "author_note" in ad.read_h5ad(result["output_path"]).obs.columns
