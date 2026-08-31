"""Tests for the _io helpers that narrow uns access (#617)."""

import warnings

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pytest
from anndata.io import write_elem

from hca_anndata_tools import _io
from hca_anndata_tools._io import (
    _decode_bytes,
    compact_categories,
    encoding_of,
    index_length,
    is_writable_element,
    obs_index_name,
    read_batch_condition,
    read_categorical_data,
    read_edit_log_h5py,
    read_element,
    read_obs_index,
    read_provenance,
    read_uns,
    remap_palette,
    require_stamped_group,
    verify_categorical_integrity,
)
from hca_anndata_tools.cap import cellxgene_schema_version
from hca_anndata_tools.testing import (
    create_sample_h5ad,
    make_fixed_width_byte_array,
    make_nullable_index,
    make_nullable_string_array,
)


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


def test_cellxgene_schema_version_group_at_leaf(h5):
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
    assert list(read_element(uns["grade_colors"])) == expected


def test_remap_palette_leaves_a_mismatched_length_alone(h5):
    """An already-broken palette is the validator's to report, not ours to
    guess at — we cannot know which position each colour was meant for."""
    uns = _palette(h5, ["#111", "#222"])  # 2 against 4 categories

    assert remap_palette(uns, "grade_colors", [0, 2], 4) is None
    assert list(read_element(uns["grade_colors"])) == ["#111", "#222"]


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
    assert list(read_element(h5["grade_colors"])) == ["#zzz"]


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


# --- nullable-string-array reads (hca-validation-tools#637) -----------------


def _nullable(tmp_path, *, masked=0):
    """A sample file whose obs index is a nullable-string-array group."""
    path = create_sample_h5ad(tmp_path / "test.h5ad")
    make_nullable_index(path, masked=masked)
    return path


def test_read_element_reads_a_nullable_group(tmp_path):
    """The encoding that broke every hand-rolled [:] slice."""
    path = _nullable(tmp_path)
    with h5py.File(path) as f:
        values = read_element(f["obs"][obs_index_name(f["obs"])])
    assert values.dtype == object
    assert all(isinstance(v, str) for v in values)


def test_read_element_reads_a_plain_dataset_unchanged(tmp_path):
    """The common encoding must keep working — same contract, same dtype."""
    path = create_sample_h5ad(tmp_path / "plain.h5ad")
    with h5py.File(path) as f:
        values = read_element(f["obs"][obs_index_name(f["obs"])])
    assert values.dtype == object
    assert all(isinstance(v, str) for v in values)


def test_read_element_reads_nullable_categories(tmp_path):
    """A categorical whose categories are themselves a nullable group.

    An index-only fix would miss this; it is how the liver files are written.
    """
    path = create_sample_h5ad(tmp_path / "cats.h5ad")
    with h5py.File(path, "r+") as f:
        make_nullable_string_array(f["obs"]["cell_type"], "categories")
    with h5py.File(path) as f:
        cats, codes = read_categorical_data(f["obs"]["cell_type"])
    assert len(cats) > 0
    assert len(codes) > 0


def test_read_obs_index_reads_a_nullable_index(tmp_path):
    assert len(read_obs_index(str(_nullable(tmp_path)))) > 0


def test_read_obs_index_refuses_a_masked_index(tmp_path):
    """A cell with no ID cannot be joined on, and str(pd.NA) is "<NA>" — so
    every masked row would collapse to one identifier and later joins would
    match the wrong cells while reporting success.

    The message must be actionable: it names the index column and the count.
    """
    path = _nullable(tmp_path, masked=3)
    with pytest.raises(ValueError) as exc:
        read_obs_index(str(path))
    assert "3 missing value" in str(exc.value)
    assert "_index" in str(exc.value)


def test_read_element_decodes_fixed_width_byte_arrays(tmp_path):
    """A byte array stamped ``array`` must come back as str.

    anndata's own write_elem stamps a numpy S-kind array as ``array``, which
    read_elem routes through read_array — raw bytes, no warning. Skipping the
    decode makes cell IDs compare unequal to their str counterparts, so a join
    silently matches nothing instead of failing (hca-validation-tools#637).
    """
    path = tmp_path / "fixed.h5ad"
    with h5py.File(path, "w") as f:
        write_elem(f, "ids", np.array([b"cell_0", b"cell_1"], dtype="S64"))
        assert f["ids"].attrs["encoding-type"] == "array"  # the shape of the trap
    with h5py.File(path) as f:
        values = read_element(f["ids"])
    assert list(values) == ["cell_0", "cell_1"]
    assert all(isinstance(v, str) for v in values)


def test_read_element_keeps_a_single_row_iterable(tmp_path):
    """anndata unwraps a length-1 unstamped byte array to a scalar.

    Without atleast_1d that reaches callers as a 0-d array, and
    ``list(read_element(...))`` raises "iteration over a 0-d array" —
    on a one-category legacy categorical, or a one-cell file.
    """
    path = tmp_path / "one.h5ad"
    with h5py.File(path, "w") as f:
        f.create_dataset("solo", data=np.array([b"only"], dtype="S8"))
    with h5py.File(path) as f:
        values = read_element(f["solo"])
    assert values.ndim == 1
    assert list(values) == ["only"]


def test_read_element_does_not_warn_on_a_legacy_unstamped_element(tmp_path):
    """An unstamped element is old, not invalid — reading it must be silent.

    anndata warns once per read that it took the legacy path. Routing every
    read through read_elem would otherwise make the MCP server emit that
    warning on every tool call against such a file, for a file class
    encoding_of explicitly supports.
    """
    path = tmp_path / "legacy.h5ad"
    with h5py.File(path, "w") as f:
        f.create_dataset("ids", data=np.array([b"cell_0", b"cell_1"], dtype="S16"))
    with h5py.File(path) as f, warnings.catch_warnings():
        warnings.simplefilter("error")
        assert list(read_element(f["ids"])) == ["cell_0", "cell_1"]


def test_is_writable_element_judges_the_container_not_the_encoding(tmp_path):
    """A fixed-width byte index is stamped ``array`` and writes perfectly well.

    replace_string_dataset needs a Dataset to copy storage properties from —
    that is the whole constraint. An encoding-name check refuses this file
    (hca-validation-tools#637 review) while get_storage_info calls it clean,
    so the two guards must share one predicate.
    """
    path = create_sample_h5ad(tmp_path / "fixed.h5ad")
    with h5py.File(path, "r+") as f:
        obs = f["obs"]
        make_fixed_width_byte_array(obs, obs_index_name(obs))
    with h5py.File(path) as f:
        obs = f["obs"]
        assert encoding_of(obs[obs_index_name(obs)]) == "array"
        assert is_writable_element(obs[obs_index_name(obs)])
        assert not is_writable_element(f["obs"]["cell_type"])


def test_verify_categorical_integrity_counts_rows_not_group_members(tmp_path):
    """n_obs must be the cell count even when the index is a nullable group.

    len(obs[idx_key]) on that group returns 2 — the ``values`` and ``mask``
    members — so every categorical column would be reported corrupt with a
    codes-length mismatch, after the caller had already paid for a full copy.
    """
    with h5py.File(_nullable(tmp_path)) as f:
        assert verify_categorical_integrity(f, ["cell_type", "sex"]) is None


def test_index_length_returns_rows_for_both_encodings(tmp_path):
    """50 cells either way — never the group's member count of 2."""
    plain = create_sample_h5ad(tmp_path / "plain.h5ad")
    with h5py.File(plain) as f:
        obs = f["obs"]
        assert index_length(obs[obs_index_name(obs)]) == 50

    with h5py.File(_nullable(tmp_path)) as f:
        obs = f["obs"]
        item = obs[obs_index_name(obs)]
        assert isinstance(item, h5py.Group)  # the shape that used to return 2
        assert index_length(item) == 50


def test_index_length_does_not_read_the_values(tmp_path, monkeypatch):
    """Metadata only — proven by making a values read fail.

    The point of this helper is the 174 MB and 1.15s that read_element spends
    on a 944k-cell index to produce a number the HDF5 header already holds.
    Asserting the count alone would pass either way, so the read is removed.
    """

    def boom(item):
        raise AssertionError("index_length read the values")

    monkeypatch.setattr(_io, "read_element", boom)
    with h5py.File(_nullable(tmp_path)) as f:
        obs = f["obs"]
        assert index_length(obs[obs_index_name(obs)]) == 50


def test_index_length_falls_back_for_an_unknown_group(tmp_path):
    """An encoding with no ``values`` child is slow, not wrong."""
    path = tmp_path / "cats.h5ad"
    with h5py.File(path, "w") as f:
        write_elem(f, "col", pd.Categorical(["a", "b", "a"]))
        assert index_length(f["col"]) == 3


def test_read_element_names_a_truncated_nullable_group(tmp_path):
    """A stamped values+mask group missing a child is a corrupt file; anndata
    would leak a raw HDF5 KeyError. read_element names the element and the
    missing child for every caller at once."""
    path = tmp_path / "truncated.h5ad"
    with h5py.File(path, "w") as f:
        no_values = f.create_group("no_values")
        no_values.attrs["encoding-type"] = "nullable-string-array"
        no_values.attrs["encoding-version"] = "0.1.0"
        no_mask = f.create_group("no_mask")
        no_mask.attrs["encoding-type"] = "nullable-string-array"
        no_mask.attrs["encoding-version"] = "0.1.0"
        no_mask.create_dataset("values", data=np.array(["a"], dtype=object), dtype=h5py.string_dtype())

        with pytest.raises(ValueError, match="no 'values'"):
            _io.read_element(no_values)
        with pytest.raises(ValueError, match="no 'mask'"):
            _io.read_element(no_mask)
        # The normalizing writer shares the same guard — a corrupt group
        # must not surface as a raw KeyError after the snapshot.
        with pytest.raises(ValueError, match="no 'mask'"):
            _io.replace_string_dataset(f, "no_mask", np.array(["b"], dtype=object))


def test_is_missing_value_judges_na_itself():
    """NA is judged inside the shared predicate, not by call-site guards —
    per-site guards are how 'NAType has no attribute strip' comes back."""
    assert _io.is_missing_value(pd.NA, set()) is True  # pyright: ignore[reportArgumentType]
    assert _io.is_missing_value("unknown", {"unknown"}) is True
    assert _io.is_missing_value("real value", {"unknown"}) is False


def test_open_h5ad_names_the_masked_categorical_column(tmp_path):
    """anndata cannot read a categorical whose categories are masked; the
    open funnel replaces pandas' unnamed 'Categorical categories cannot be
    null' with a refusal naming the column — in var as well as obs, for
    every tool that opens files through it."""
    path = tmp_path / "masked_var_cat.h5ad"
    var = pd.DataFrame({"family": pd.Categorical(["a", "b"])}, index=["ENSG1", "ENSG2"])
    adata = ad.AnnData(X=np.zeros((2, 2), dtype=np.float32), var=var, obs=pd.DataFrame(index=["c0", "c1"]))
    adata.write_h5ad(path)
    with h5py.File(path, "r+") as f:
        make_nullable_string_array(f["var/family"], "categories", masked=1)

    with pytest.raises(ValueError, match="masked \\(null\\) categories") as excinfo, _io.open_h5ad(str(path)):
        pass
    assert "var column 'family'" in str(excinfo.value)


def test_open_h5ad_names_a_masked_categorical_in_obsm(tmp_path):
    """The named refusal covers obsm frames too — anndata reads their
    categoricals the same way, and the raw pandas message names no column."""
    path = tmp_path / "masked_obsm_cat.h5ad"
    adata = ad.AnnData(X=np.zeros((2, 2), dtype=np.float32), obs=pd.DataFrame(index=["c0", "c1"]))
    adata.obsm["annot"] = pd.DataFrame({"grade": pd.Categorical(["hi", "lo"])}, index=adata.obs_names)
    adata.write_h5ad(path)
    with h5py.File(path, "r+") as f:
        make_nullable_string_array(f["obsm/annot/grade"], "categories", masked=1)

    with pytest.raises(ValueError, match="masked \\(null\\) categories") as excinfo, _io.open_h5ad(str(path)):
        pass
    assert "obsm['annot'] column 'grade'" in str(excinfo.value)


def test_normalizing_a_nullable_group_preserves_producer_attrs(tmp_path):
    """Only the encoding attrs change when a nullable group is normalized —
    whatever else a producer stamped on the element survives, per
    replace_string_dataset's own contract ("preserving its attrs")."""
    path = tmp_path / "attrs.h5ad"
    with h5py.File(path, "w") as f:
        obs = f.create_group("obs")
        ds = obs.create_dataset("col", data=np.array(["a", "b"], dtype=object), dtype=h5py.string_dtype())
        ds.attrs["encoding-type"] = "string-array"
        ds.attrs["encoding-version"] = "0.2.0"
        ds.attrs["producer-note"] = "keep me"
        make_nullable_string_array(obs, "col")  # copies attrs onto the group
        _io.replace_string_dataset(obs, "col", np.array(["a", "b"], dtype=object))
        out = obs["col"]
        assert isinstance(out, h5py.Dataset)
        assert out.attrs["producer-note"] == "keep me"
        assert out.attrs["encoding-type"] == "string-array"


# --- readers report the dtype that is on disk (hca-validation-tools#668) ----


@pytest.mark.parametrize(
    ("values", "expected_kind"),
    [
        (np.array([True, False]), "b"),
        (np.array([1, 2], dtype=np.int64), "i"),
        (np.array([1.5, 2.5]), "f"),
    ],
    ids=["bool", "int", "float"],
)
def test_read_element_preserves_non_string_dtypes(tmp_path, values, expected_kind):
    """No coercion: what anndata reads passes through untouched.

    Flattening these to object erases the distinction between "strings" and
    "values someone widened", and anndata's write registry resolves object as
    strings — which is how a boolean CAP category reached a vlen-string writer.
    """
    path = tmp_path / "dtypes.h5"
    with h5py.File(path, "w") as f:
        write_elem(f, "col", values)
    with h5py.File(path) as f:
        out = read_element(f["col"])
    assert out.dtype.kind == expected_kind
    assert list(out) == list(values)
