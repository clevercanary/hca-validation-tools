"""Tests for the _io helpers that narrow uns access (#617)."""

import h5py
import numpy as np
import pytest
from anndata.io import write_elem

from hca_anndata_tools._io import (
    _decode_bytes,
    compact_categories,
    read_batch_condition,
    read_edit_log_h5py,
    read_provenance,
    read_string_dataset,
    read_uns,
    remap_palette,
    require_stamped_group,
)
from hca_anndata_tools.cap import cellxgene_schema_version


def test_read_uns_absent(h5):
    assert read_uns(h5) is None


def test_read_uns_group(h5):
    group = h5.create_group("uns")
    assert read_uns(h5) == group


def test_read_uns_dataset(h5):
    """A scalar Dataset at 'uns' is the malformed shape that made membership
    tests raise TypeError and attribute access raise AttributeError."""
    h5["uns"] = "not a group"
    assert read_uns(h5) is None


def test_require_stamped_group_stamps_a_new_group(h5):
    group = require_stamped_group(h5, "uns")
    assert isinstance(group, h5py.Group)
    assert group.attrs["encoding-type"] == "dict"
    assert group.attrs["encoding-version"] == "0.1.0"


def test_require_stamped_group_preserves_existing_attrs(h5):
    """setdefault semantics: an already-stamped group keeps its attrs, so a
    re-run never rewrites what anndata wrote."""
    h5.create_group("uns").attrs["encoding-version"] = "0.2.0"

    group = require_stamped_group(h5, "uns")

    assert group.attrs["encoding-version"] == "0.2.0"
    assert group.attrs["encoding-type"] == "dict"  # missing attr still filled


def test_read_batch_condition_none():
    assert read_batch_condition(None) == []


def test_read_batch_condition_absent(h5):
    assert read_batch_condition(h5.create_group("uns")) == []


def test_read_batch_condition_array(h5):
    uns = h5.create_group("uns")
    uns.create_dataset("batch_condition", data=["donor_id", "sample_id"])
    assert read_batch_condition(uns) == ["donor_id", "sample_id"]


def test_read_batch_condition_scalar(h5):
    uns = h5.create_group("uns")
    uns["batch_condition"] = "donor_id"
    assert read_batch_condition(uns) == ["donor_id"]


def test_read_provenance_none():
    assert read_provenance(None) is None


def test_read_provenance_absent(h5):
    assert read_provenance(h5.create_group("uns")) is None


def test_read_provenance_dataset(h5):
    uns = h5.create_group("uns")
    uns["provenance"] = "not a group"
    assert read_provenance(uns) is None


def test_read_provenance_group(h5):
    prov = h5.create_group("uns/provenance")
    assert read_provenance(h5["uns"]) == prov


def test_read_edit_log_group_at_edit_history(h5):
    """A Group at uns/provenance/edit_history is narrowed to the no-log
    answer instead of raising through every caller."""
    h5.create_group("uns/provenance/edit_history")

    assert read_edit_log_h5py(h5) == "[]"


def test_read_edit_log_numeric_at_edit_history(h5):
    """A numeric scalar there is not a log either — narrowed to "[]" rather
    than handing a float to json.loads downstream."""
    h5.create_group("uns/provenance")["edit_history"] = 3.14

    assert read_edit_log_h5py(h5) == "[]"


def testcellxgene_schema_version_group_at_leaf(h5):
    """A Group at uns['schema_version'] is narrowed to None instead of
    raising TypeError from the scalar read."""
    h5.create_group("uns/schema_version")

    assert cellxgene_schema_version(h5) is None


# --- remap_palette (#624) ----------------------------------------------------
#
# Asserted as which colours survive in which order, never as a length — see
# remap_palette's docstring for why the length is what made the bug silent.

_COLORS = ["#aaa", "#bbb", "#ccc", "#ddd"]


def _palette(h5, colors=_COLORS):
    uns = h5.require_group("uns")
    write_elem(uns, "grade_colors", np.array(colors, dtype=object))
    return uns


@pytest.mark.parametrize(
    ("kept", "expected"),
    [
        ([1, 2, 3], ["#bbb", "#ccc", "#ddd"]),  # first removed
        ([0, 2, 3], ["#aaa", "#ccc", "#ddd"]),  # middle removed
        ([0, 1, 2], ["#aaa", "#bbb", "#ccc"]),  # last removed
        ([0, 3], ["#aaa", "#ddd"]),  # two non-adjacent — the case a single-index slice cannot express
        ([2], ["#ccc"]),  # all but one
        ([0, 1, 2, 3], _COLORS),  # nothing removed
    ],
)
def test_remap_palette_keeps_the_surviving_positions(h5, kept, expected):
    uns = _palette(h5)

    assert remap_palette(uns, "grade_colors", kept, len(_COLORS)) == "grade_colors"
    assert list(read_string_dataset(uns, "grade_colors")) == expected


def test_remap_palette_leaves_a_mismatched_length_alone(h5):
    """An already-broken palette is the validator's to report, not ours to
    guess at — we cannot know which position each colour was meant for."""
    uns = _palette(h5, ["#111", "#222"])  # 2 against 4 categories

    assert remap_palette(uns, "grade_colors", [0, 2], 4) is None
    assert list(read_string_dataset(uns, "grade_colors")) == ["#111", "#222"]


def test_remap_palette_no_palette_key(h5):
    assert remap_palette(h5.require_group("uns"), "grade_colors", [0], 1) is None


def test_remap_palette_no_key_named(h5):
    assert remap_palette(_palette(h5), None, [0], 4) is None


def test_remap_palette_no_uns():
    assert remap_palette(None, "grade_colors", [0], 4) is None


def test_remap_palette_does_not_resolve_link_paths(h5):
    """Membership goes through direct_members, so a '/'-prefixed key cannot
    reach a root dataset (the #623 trap)."""
    write_elem(h5, "grade_colors", np.array(["#zzz"], dtype=object))
    uns = h5.require_group("uns")

    assert remap_palette(uns, "/grade_colors", [0], 1) is None
    assert list(read_string_dataset(h5, "grade_colors")) == ["#zzz"]


def test_remap_palette_keeps_the_string_encoding(h5):
    uns = _palette(h5)
    before = dict(uns["grade_colors"].attrs)

    remap_palette(uns, "grade_colors", [0, 1], len(_COLORS))

    assert dict(uns["grade_colors"].attrs) == before


def test_compact_categories_reports_the_surviving_positions():
    """The positions remap_palette needs; compact_categories always computed
    them and used to discard them."""
    kept_cats, codes, kept = compact_categories(["a", "b", "c", "d"], np.array([0, 0, 2, -1]))

    assert kept_cats == ["a", "c"]
    assert kept == [0, 2]
    assert list(codes) == [0, 0, 1, -1]


def test_remap_palette_leaves_a_scalar_palette_alone(h5):
    """check_string_dtype passes for a shape-() dataset, but asstr()[:] raises
    on it — so the scalar case needs its own rejection, not a crash."""
    uns = h5.require_group("uns")
    write_elem(uns, "grade_colors", "#aaa")

    assert remap_palette(uns, "grade_colors", [0], 1) is None
    assert _decode_bytes(uns["grade_colors"][()]) == "#aaa"
