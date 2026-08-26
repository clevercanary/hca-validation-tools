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
from hca_anndata_tools.testing import create_sample_h5ad, make_nullable_string_array

# The real split this tool exists for, from nee2023's tissue_label (#527):
# 11,635 cells under a misspelling of the category above them.
_VALUES = ["Prophylactic Mastectomy"] * 5 + ["Prophylatctic Mastectomy"] * 3 + ["Contralateral"] * 2
_TYPO = "Prophylatctic Mastectomy"
_CORRECT = "Prophylactic Mastectomy"


def _make(path, column="tissue_label", values=None, uns=None, compression="gzip", **extra_obs):
    values = _VALUES if values is None else values
    obs = pd.DataFrame(
        {column: pd.Categorical(values), **extra_obs},
        index=pd.Index([f"c{i}" for i in range(len(values))], name="cellID"),
    )
    n = len(obs)
    adata = ad.AnnData(X=np.zeros((n, 2), dtype=np.float32), obs=obs)
    adata.uns.update(uns or {})
    adata.write_h5ad(path, compression=compression)
    return str(path)


_CAP_BLOCK = {"cellannotation_schema_version": "1.0.0", "cellannotation_metadata": {"myset": {}}}


def _make_cap_file(path):
    """A CAP-annotated file: an annotation set declared in uns, and the '--'
    column that set names. Compose with the ``downgrade_cap_to_legacy``
    fixture for the deprecated top-level layout."""
    return _make(
        path,
        column="myset--cell_fullname",
        values=["T cell", "B cel", "T cell"],
        uns={"cap_metadata": _CAP_BLOCK},
    )


# --- the happy path ----------------------------------------------------------


def test_merge_folds_the_typo_into_its_correct_sibling(tmp_path):
    path = _make(tmp_path / "nee.h5ad")

    result = merge_obs_categories(path, "tissue_label", _TYPO, _CORRECT)

    assert "error" not in result
    out = ad.read_h5ad(result["output_path"])
    assert _TYPO not in out.obs["tissue_label"].cat.categories
    assert (out.obs["tissue_label"] == _CORRECT).sum() == 8  # 5 + the 3 recoded
    assert len(out.obs) == 10, "cell count is preserved — a merge recodes, it never drops rows"


def test_merge_reports_the_recoded_count(tmp_path):
    """The caller confirms the split was the size they expected — for nee2023,
    11,635 cells."""
    path = _make(tmp_path / "nee.h5ad")

    result = merge_obs_categories(path, "tissue_label", _TYPO, _CORRECT)

    assert result["cells_recoded"] == 3
    assert result["categories_remaining"] == 2
    assert result["from_value"] == _TYPO and result["to_value"] == _CORRECT


def test_merge_preserves_compression(tmp_path):
    """replace_categorical_column carries the codes dataset's storage settings
    across the delete-and-recreate."""
    path = _make(tmp_path / "nee.h5ad", compression="gzip")

    result = merge_obs_categories(path, "tissue_label", _TYPO, _CORRECT)

    with h5py.File(result["output_path"], "r") as f:
        assert f["obs/tissue_label/codes"].compression == "gzip"


def test_merge_writes_an_edit_log_entry(tmp_path):
    path = _make(tmp_path / "nee.h5ad")

    result = merge_obs_categories(path, "tissue_label", _TYPO, _CORRECT)

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

    merge_obs_categories(path, "tissue_label", _TYPO, _CORRECT)

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
def test_merge_refuses_an_absent_value(tmp_path, no_snapshot, from_value, to_value, expected):
    """Both must already exist: creating a category is a different operation,
    and a missing value is a caller mistake, not a silent no-op."""
    path = _make(tmp_path / "nee.h5ad")

    result = merge_obs_categories(path, "tissue_label", from_value, to_value)

    assert "error" in result
    assert expected in result["error"]
    assert no_snapshot(path)


def test_merge_refuses_a_non_categorical_column(tmp_path, no_snapshot):
    """This edits the categories array, not values row by row."""
    path = _make(tmp_path / "nee.h5ad", n_counts=np.arange(10, dtype=float))

    result = merge_obs_categories(path, "n_counts", "1.0", "2.0")

    assert "error" in result
    assert "not a categorical column" in result["error"]
    assert no_snapshot(path)


def test_merge_refuses_a_derived_label_with_its_term_id_present(tmp_path, no_snapshot):
    """The coherence guard: merging a label alone desyncs it from the term ID
    it is derived from, and populate_labels regenerates *from* the term ID."""
    path = _make(
        tmp_path / "nee.h5ad",
        column="cell_type",
        values=["T cell"] * 5 + ["T cel"] * 3 + ["B cell"] * 2,
        cell_type_ontology_term_id=pd.Categorical(["CL:0000084"] * 10),
    )

    result = merge_obs_categories(path, "cell_type", "T cel", "T cell")

    assert "error" in result
    assert "cell_type_ontology_term_id" in result["error"]
    assert "populate_labels" in result["error"]
    assert no_snapshot(path)


def test_merge_trims_the_palette_entry_the_category_owned(tmp_path):
    """uns['<col>_colors'] is positionally aligned to the categories, so the
    entry to drop is exactly the merged-away category's index. Left alone it
    would recolour every category after it, and the validator only checks the
    palette's length — so the mis-colouring would pass silently."""
    # categories sort as: Contralateral, Prophylactic, Prophylatctic
    path = _make(
        tmp_path / "nee.h5ad",
        uns={"tissue_label_colors": np.array(["#c0c0c0", "#good00", "#typo00"], dtype=object)},
    )

    result = merge_obs_categories(path, "tissue_label", _TYPO, _CORRECT)

    assert "error" not in result
    assert result["palette_trimmed"] == "tissue_label_colors"
    out = ad.read_h5ad(result["output_path"])
    colors = list(out.uns["tissue_label_colors"])
    assert colors == ["#c0c0c0", "#good00"], "the typo's colour goes; the others keep theirs"
    assert len(colors) == len(out.obs["tissue_label"].cat.categories)
    assert dict(zip(out.obs["tissue_label"].cat.categories, colors, strict=True)) == {
        "Contralateral": "#c0c0c0",
        _CORRECT: "#good00",
    }, "each surviving category keeps the colour it had"


def test_merge_leaves_a_mismatched_palette_alone(tmp_path):
    """A palette whose length already disagrees with the categories is not
    ours to interpret — the validator reports it."""
    path = _make(  # palette of 2 against 3 categories
        tmp_path / "nee.h5ad", uns={"tissue_label_colors": np.array(["#111", "#222"], dtype=object)}
    )

    result = merge_obs_categories(path, "tissue_label", _TYPO, _CORRECT)

    assert "error" not in result
    assert result["palette_trimmed"] is None
    assert list(ad.read_h5ad(result["output_path"]).uns["tissue_label_colors"]) == ["#111", "#222"]


def test_merge_allows_a_column_named_by_batch_condition(tmp_path):
    """Unlike a drop or a rename, a merge leaves the column's name and identity
    intact, so the declaration still names a real column — nothing dangles."""
    path = _make(tmp_path / "nee.h5ad", uns={"batch_condition": np.array(["tissue_label"], dtype=object)})

    result = merge_obs_categories(path, "tissue_label", _TYPO, _CORRECT)

    assert "error" not in result
    out = ad.read_h5ad(result["output_path"])
    assert list(out.uns["batch_condition"]) == ["tissue_label"], "declaration untouched"


def test_merge_refuses_the_obs_index(tmp_path, no_snapshot):
    path = _make(tmp_path / "nee.h5ad")

    result = merge_obs_categories(path, "cellID", "c1", "c2")

    assert "error" in result
    assert "obs index" in result["error"]
    assert no_snapshot(path)


def test_merge_refuses_a_slash_name(tmp_path, no_snapshot):
    """h5py resolves a '/' name as a link path — the check every obs mutation
    owes (guards.malformed_name_problems)."""
    path = _make(tmp_path / "nee.h5ad")

    result = merge_obs_categories(path, "/X", "a", "b")

    assert "error" in result
    assert "/X" in result["error"]
    assert no_snapshot(path)


def test_merge_refuses_identical_values(tmp_path, no_snapshot):
    path = _make(tmp_path / "nee.h5ad")

    result = merge_obs_categories(path, "tissue_label", _CORRECT, _CORRECT)

    assert "error" in result
    assert "nothing to merge" in result["error"]
    assert no_snapshot(path)


def test_merge_refuses_an_absent_column(tmp_path, no_snapshot):
    path = _make(tmp_path / "nee.h5ad")

    result = merge_obs_categories(path, "no_such_column", "a", "b")

    assert "error" in result
    assert "not present in obs" in result["error"]
    assert no_snapshot(path)


def test_merge_refuses_non_string_arguments(tmp_path):
    """MCP-exposed, so arguments arrive as decoded JSON and may hold numbers."""
    path = _make(tmp_path / "nee.h5ad")

    result = merge_obs_categories(path, "tissue_label", 1, _CORRECT)  # pyright: ignore[reportArgumentType]

    assert "error" in result
    assert "must be strings" in result["error"]


def test_merge_missing_file():
    result = merge_obs_categories("/nonexistent/file.h5ad", "col", "a", "b")
    assert "error" in result
    assert "File not found" in result["error"]


def test_merge_refuses_a_cap_annotation_column(tmp_path, no_snapshot):
    """CAP is the system of record for its exports: a set is stripped and
    re-copied wholesale, never edited value by value here."""
    path = _make_cap_file(tmp_path / "cap.h5ad")

    result = merge_obs_categories(path, "myset--cell_fullname", "B cel", "T cell")

    assert "error" in result
    assert "CAP annotation-set column" in result["error"]
    assert no_snapshot(path)


def test_merge_refuses_the_legacy_cap_layout(tmp_path, no_snapshot, downgrade_cap_to_legacy):
    """The layout precondition every mutating tool carries (#552): in the
    legacy layout uns['cap_metadata'] is absent, so CAP columns would look
    editable — the whole file is refused instead."""
    path = str(downgrade_cap_to_legacy(Path(_make_cap_file(tmp_path / "legacy.h5ad"))))

    result = merge_obs_categories(path, "myset--cell_fullname", "B cel", "T cell")

    assert "error" in result
    assert "deprecated" in result["error"] or "not supported" in result["error"]
    assert no_snapshot(path)


def test_merge_keeps_categories_that_are_empty_for_their_own_reasons(tmp_path):
    """Exactly one category disappears: the merged-away one. A category left
    empty by an earlier subset is the file's business, not this tool's."""
    path = _make(tmp_path / "nee.h5ad")
    adata = ad.read_h5ad(path)
    adata.obs["tissue_label"] = adata.obs["tissue_label"].cat.add_categories(["Never Used"])
    adata.write_h5ad(path)

    result = merge_obs_categories(path, "tissue_label", _TYPO, _CORRECT)

    assert "error" not in result
    cats = list(ad.read_h5ad(result["output_path"]).obs["tissue_label"].cat.categories)
    assert "Never Used" in cats, "an unrelated empty category must survive the merge"
    assert _TYPO not in cats
    assert result["categories_remaining"] == len(cats)


def test_merge_reports_the_count_it_actually_wrote(tmp_path):
    """categories_remaining comes from what was written, not from arithmetic
    on the pre-merge list."""
    path = _make(tmp_path / "nee.h5ad")

    result = merge_obs_categories(path, "tissue_label", _TYPO, _CORRECT)

    out = ad.read_h5ad(result["output_path"])
    assert result["categories_remaining"] == len(out.obs["tissue_label"].cat.categories)


def test_merge_flags_that_paired_labels_are_now_stale(tmp_path):
    """Merging term IDs is the remedy the label-side guard recommends, so it is
    allowed — but it leaves the paired label stale, and the caller has no other
    way to know that."""
    path = _make(
        tmp_path / "nee.h5ad",
        column="cell_type_ontology_term_id",
        values=["CL:0000084"] * 5 + ["CL:0000236"] * 3 + ["CL:0000000"] * 2,
        cell_type=pd.Categorical(["T cell"] * 5 + ["B cell"] * 3 + ["other"] * 2),
    )

    result = merge_obs_categories(path, "cell_type_ontology_term_id", "CL:0000236", "CL:0000084")

    assert "error" not in result
    assert result["stale_label_column"] == "cell_type"
    with h5py.File(result["output_path"], "r") as f:
        assert "cell_type" in json.loads(read_edit_log_h5py(f))[-1]["description"]


def test_merge_does_not_flag_regeneration_for_a_plain_column(tmp_path):
    path = _make(tmp_path / "nee.h5ad")

    result = merge_obs_categories(path, "tissue_label", _TYPO, _CORRECT)

    assert result["stale_label_column"] is None
    assert result["palette_trimmed"] is None


def test_merge_refuses_a_non_string_categorical(tmp_path):
    """anndata writes int-backed categoricals (batch, cluster ids); the caller
    is forced to pass strings, so those values can never match."""
    path = _make(tmp_path / "nee.h5ad", column="batch", values=pd.Categorical([1, 2, 1, 2, 1] * 2))

    result = merge_obs_categories(path, "batch", "2", "1")

    assert "error" in result
    assert "non-string categories" in result["error"]
    assert "int" in result["error"], "the dtype is named, so the caller sees why"


# --- palette repair: the slice arithmetic, at every position ------------------
#
# The happy-path test above merges the category that sorts *last*, so it only
# exercises the empty upper half of the slice. These cover all four positions —
# both empty halves, and the two where both halves are populated, which is
# where an off-by-one shows — and assert the surviving category -> colour
# *mapping*, not just the length, because the validator checks only length.

_ABCD = ["a", "a", "b", "b", "c", "c", "d", "d"]
_ABCD_COLORS = ["#aaa", "#bbb", "#ccc", "#ddd"]


def _make_palette_file(path, column="grp"):
    return _make(path, column=column, values=_ABCD, uns={f"{column}_colors": np.array(_ABCD_COLORS, dtype=object)})


@pytest.mark.parametrize(
    ("from_value", "to_value", "expected"),
    [
        # first position — colors[:0] is empty
        ("a", "b", {"b": "#bbb", "c": "#ccc", "d": "#ddd"}),
        # middle, merging upward (to_index > from_index)
        ("b", "d", {"a": "#aaa", "c": "#ccc", "d": "#ddd"}),
        # middle, merging downward (to_index < from_index)
        ("c", "a", {"a": "#aaa", "b": "#bbb", "d": "#ddd"}),
        # last position — colors[from_index + 1:] is empty
        ("d", "a", {"a": "#aaa", "b": "#bbb", "c": "#ccc"}),
    ],
)
def test_palette_survivors_keep_their_own_colour(tmp_path, from_value, to_value, expected):
    path = _make_palette_file(tmp_path / "pal.h5ad")

    result = merge_obs_categories(path, "grp", from_value, to_value)

    assert "error" not in result
    assert result["palette_trimmed"] == "grp_colors"
    out = ad.read_h5ad(result["output_path"])
    cats = list(out.obs["grp"].cat.categories)
    colors = list(out.uns["grp_colors"])
    assert dict(zip(cats, colors, strict=True)) == expected
    # the merged-away category's colour is the one that went
    assert _ABCD_COLORS["abcd".index(from_value)] not in colors


def test_palette_repair_leaves_other_columns_palettes_alone(tmp_path):
    """Only the merged column's palette is positionally invalidated; a
    neighbour's is unrelated data."""
    path = _make(
        tmp_path / "pal.h5ad",
        column="grp",
        values=_ABCD,
        uns={
            "grp_colors": np.array(_ABCD_COLORS, dtype=object),
            "other_colors": np.array(["#111", "#222"], dtype=object),
        },
        other=pd.Categorical(["x", "y"] * 4),
    )

    result = merge_obs_categories(path, "grp", "a", "b")

    assert "error" not in result
    out = ad.read_h5ad(result["output_path"])
    assert list(out.uns["other_colors"]) == ["#111", "#222"]
    assert list(out.obs["other"].cat.categories) == ["x", "y"]


def test_palette_keeps_its_on_disk_encoding(tmp_path):
    """Written through anndata's write_elem, so the string-array encoding
    attrs survive — a hand-rolled rewrite is what drops them."""
    path = _make_palette_file(tmp_path / "pal.h5ad")
    with h5py.File(path, "r") as f:
        before = dict(f["uns"]["grp_colors"].attrs)

    result = merge_obs_categories(path, "grp", "a", "b")

    with h5py.File(result["output_path"], "r") as f:
        assert dict(f["uns"]["grp_colors"].attrs) == before


def test_palette_untouched_when_the_merge_is_refused(tmp_path, no_snapshot):
    """All-or-nothing covers the palette too: a refused request writes nothing,
    so the palette cannot be trimmed against a merge that did not happen."""
    path = _make_palette_file(tmp_path / "pal.h5ad")

    result = merge_obs_categories(path, "grp", "a", "not-a-category")

    assert "error" in result
    assert no_snapshot(path)
    assert list(ad.read_h5ad(path).uns["grp_colors"]) == _ABCD_COLORS


def test_merge_refuses_nullable_categories_by_name(tmp_path):
    """The liver file shape must not leak an h5py internal.

    A nullable-string-array categories group has no .dtype, so the string-dtype
    guard raised AttributeError and the tool returned "'Group' object has no
    attribute 'dtype'" — an h5py internal from a tool that should say which
    encoding it cannot write (hca-validation-tools#637). Note mask 0: this is
    the plain shape of all seven liver integrated objects, not an edge case.
    """
    path = create_sample_h5ad(tmp_path / "nullable.h5ad")
    with h5py.File(path, "r+") as f:
        make_nullable_string_array(f["obs"]["cell_type"], "categories")

    before = set(tmp_path.iterdir())
    result = merge_obs_categories(str(path), "cell_type", "T cell", "B cell")

    assert "error" in result
    assert "nullable-string-array" in result["error"]
    assert "#641" in result["error"]
    assert "dtype" not in result["error"]
    # Refused before the snapshot, like every other write guard here.
    assert set(tmp_path.iterdir()) == before
