"""Encodings written by anndata itself, read back by this package.

Every other test file builds its nullable fixtures through testing.py's
hand-rolled converters. This module removes that trust step: the files here
are written by anndata's own serializer — the flag-flipped writer the liver
producers' pipelines used, and ``ad.io.write_elem`` where the convenience
layer cannot reach a shape — so what the readers and guards are tested
against is the authentic on-disk format, combination by combination.

Two facts discovered while building this, worth keeping on record:

* ``AnnData.write_h5ad`` runs ``strings_to_categoricals``, which converts
  any string column whose distinct-value count is below its length — so a
  plain ``nullable-string-array`` *column* survives only when every value
  is unique (IDs), or when the dataframe is serialized via ``write_elem``.
* pandas refuses ``pd.NA`` inside ``Categorical`` *categories*, so masked
  categories cannot be produced by pandas or anndata at all — that shape
  exists only in corrupt or hand-built files, which is why the tools treat
  it as a defect to refuse rather than an encoding to support.
"""

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp

from hca_anndata_tools._io import (
    encoding_of,
    holds_string_values,
    read_element,
    read_obs_index,
)
from hca_anndata_tools.compress import compress_h5ad
from hca_anndata_tools.merge_categories import merge_obs_categories
from hca_anndata_tools.rename import rename_cell_ids
from hca_anndata_tools.storage import get_storage_info
from hca_anndata_tools.testing import (
    make_nullable_index,
    write_h5ad_with_nullable_strings,
)
from hca_anndata_tools.write import write_h5ad


def _matrix_adata(n: int = 3) -> ad.AnnData:
    obs = pd.DataFrame(
        {
            "str_plain": ["a", "b", "a"],
            "str_nullable": pd.array(["x", pd.NA, "y"], dtype="string"),
            "int_nullable": pd.array([1, pd.NA, 3], dtype="Int64"),
            "bool_nullable": pd.array([True, pd.NA, False], dtype="boolean"),
            "cat_plain": pd.Categorical(["p", "q", "p"]),
            # The liver #638 shape: a categorical whose categories are
            # StringDtype-backed serializes its categories child as a
            # nullable-string-array group.
            "cat_nullable_cats": pd.Categorical(pd.array(["m", "n", "m"], dtype="string")),
        },
        index=pd.Index(pd.array(["c1", "c2", "c3"], dtype="string")),
    )
    return ad.AnnData(X=np.zeros((n, 2), dtype=np.float32), obs=obs)


def test_anndata_written_matrix_has_the_expected_encodings(tmp_path):
    """Pin what anndata 0.11.4 actually writes for every dtype combination —
    the ground truth all other fixtures imitate."""
    path = tmp_path / "matrix.h5ad"
    write_h5ad_with_nullable_strings(_matrix_adata(), path)

    with h5py.File(path) as f:
        assert encoding_of(f["obs/_index"]) == "nullable-string-array"
        # strings_to_categoricals converts every non-unique string column,
        # StringDtype included.
        assert encoding_of(f["obs/str_plain"]) == "categorical"
        assert encoding_of(f["obs/str_nullable"]) == "categorical"
        assert encoding_of(f["obs/int_nullable"]) == "nullable-integer"
        assert encoding_of(f["obs/bool_nullable"]) == "nullable-boolean"
        assert encoding_of(f["obs/cat_plain/categories"]) == "string-array"
        assert encoding_of(f["obs/cat_nullable_cats/categories"]) == "nullable-string-array"
        assert holds_string_values(f["obs/_index"])  # pyright: ignore[reportArgumentType]
        assert not holds_string_values(f["obs/int_nullable"])  # pyright: ignore[reportArgumentType]


def test_readers_and_report_agree_on_the_anndata_written_matrix(tmp_path):
    path = tmp_path / "matrix.h5ad"
    write_h5ad_with_nullable_strings(_matrix_adata(), path)

    assert read_obs_index(str(path)) == ["c1", "c2", "c3"]

    enc = get_storage_info(str(path))["encodings"]
    assert enc["obs"]["index"] == "nullable-string-array"
    assert enc["obs"]["index_masked"] == 0
    flagged = set(enc["unsupported"])
    assert "obs/_index" in flagged
    assert "obs/cat_nullable_cats/categories" in flagged
    # Numeric nullables are inside the profile — anndata writes them ungated
    # — so they must not be flagged.
    assert "obs/int_nullable" not in flagged
    assert "obs/bool_nullable" not in flagged


def test_masked_index_written_by_anndata_is_refused_by_name(tmp_path):
    path = tmp_path / "masked_index.h5ad"
    adata = ad.AnnData(
        X=np.zeros((3, 2), dtype=np.float32),
        obs=pd.DataFrame(index=pd.Index(pd.array(["c1", pd.NA, "c3"], dtype="string"))),
    )
    write_h5ad_with_nullable_strings(adata, path)

    assert get_storage_info(str(path))["encodings"]["obs"]["index_masked"] == 1
    with pytest.raises(ValueError, match="missing value"):
        read_obs_index(str(path))


def test_unique_valued_nullable_column_is_flagged_then_normalized(tmp_path):
    """All-unique values escape strings_to_categoricals, so the column lands
    as a genuine nullable-string-array — the report flags it, and the write
    funnel normalizes the round-trip to the plain profile (#641)."""
    path = tmp_path / "unique_col.h5ad"
    obs = pd.DataFrame({"lib_id": pd.array(["L1", "L2", "L3"], dtype="string")}, index=["c1", "c2", "c3"])
    write_h5ad_with_nullable_strings(ad.AnnData(X=np.zeros((3, 2), dtype=np.float32), obs=obs), path)

    with h5py.File(path) as f:
        assert encoding_of(f["obs/lib_id"]) == "nullable-string-array"
    assert "obs/lib_id" in get_storage_info(str(path))["encodings"]["unsupported"]

    result = write_h5ad(ad.read_h5ad(path), str(path), _entry())
    assert "error" not in result, result.get("error")
    assert "obs['lib_id']" in result["encodings_normalized"]
    with h5py.File(result["output_path"]) as f:
        assert encoding_of(f["obs/lib_id"]) == "string-array"
    assert get_storage_info(result["output_path"])["encodings"]["unsupported_count"] == 0


def test_compress_normalizes_the_anndata_written_matrix(tmp_path):
    """End to end on anndata-authored files: the full liver-shaped matrix —
    nullable index, nullable categorical categories, numeric nullables —
    goes through compress_h5ad and comes out entirely inside the profile,
    values intact. This is the #641 definition of done."""
    path = tmp_path / "matrix.h5ad"
    write_h5ad_with_nullable_strings(_matrix_adata(), path)
    assert get_storage_info(str(path))["encodings"]["unsupported_count"] > 0

    result = compress_h5ad(str(path))

    assert "error" not in result, result.get("error")
    assert "obs index" in result["encodings_normalized"]
    enc = get_storage_info(result["output_path"])["encodings"]
    assert enc["unsupported_count"] == 0
    assert enc["obs"]["index"] == "string-array"
    out = ad.read_h5ad(result["output_path"])
    assert list(out.obs_names) == ["c1", "c2", "c3"]
    assert list(out.obs["cat_nullable_cats"]) == ["m", "n", "m"]
    # Numeric nullables are inside the profile and survive untouched.
    assert str(out.obs["int_nullable"].dtype) == "Int64"


def test_masked_column_written_by_anndata_is_refused_at_the_funnel(tmp_path):
    """The masked half of #641's boundary, on an anndata-authored shape: a
    masked plain column (write_elem route) refuses at the funnel by name."""
    path = _masked_column_h5ad(tmp_path)

    result = compress_h5ad(str(path))

    assert "error" in result
    assert "obs['sample_id']" in result["error"]
    assert "masked (null) string" in result["error"]


def _masked_column_h5ad(tmp_path):
    """A file whose obs carries a masked plain nullable-string column.

    write_elem, not write_h5ad: AnnData's convenience layer would convert
    the column to a categorical (strings_to_categoricals) and swallow the
    shape entirely.
    """
    path = tmp_path / "masked_col.h5ad"
    adata = ad.AnnData(X=np.zeros((3, 2), dtype=np.float32), obs=pd.DataFrame(index=["c1", "c2", "c3"]))
    adata.write_h5ad(path)
    with h5py.File(path, "r+") as f, ad.settings.override(allow_write_nullable_strings=True):
        obs = ad.io.read_elem(f["obs"])
        obs["sample_id"] = pd.array(["s1", pd.NA, "s1"], dtype="string")
        ad.io.write_elem(f, "obs", obs)
    return path


def test_masked_column_via_write_elem_reads_and_reports(tmp_path):
    """A masked plain column cannot come out of AnnData.write_h5ad (the
    categorical conversion swallows it), but write_elem — anndata's own
    serializer, and what transplant code uses — produces it. The selector
    path must read it and report the masked rows."""
    path = _masked_column_h5ad(tmp_path)

    with h5py.File(path) as f:
        assert encoding_of(f["obs/sample_id"]) == "nullable-string-array"
        values = read_element(f["obs/sample_id"])  # pyright: ignore[reportArgumentType]
    assert values[0] == "s1" and pd.isna(values[1])

    result = rename_cell_ids(str(path), column="sample_id", value="s1", prefix_from="c", prefix_to="X_c")
    assert "error" not in result, result.get("error")
    assert result["n_selected"] == 2
    assert result["n_selector_masked"] == 1


def test_merge_normalizes_the_anndata_written_liver_shape(tmp_path):
    """The #638 categories shape straight from anndata's writer — not our
    stamp — merges and comes out as a plain string-array."""
    path = tmp_path / "liver_shape.h5ad"
    obs = pd.DataFrame(
        {"cell_type": pd.Categorical(pd.array(["T cell", "B cell", "T cell"], dtype="string"))},
        index=["c1", "c2", "c3"],
    )
    write_h5ad_with_nullable_strings(ad.AnnData(X=np.zeros((3, 2), dtype=np.float32), obs=obs), path)

    result = merge_obs_categories(str(path), "cell_type", "T cell", "B cell")

    assert "error" not in result, result.get("error")
    with h5py.File(result["output_path"]) as f:
        assert isinstance(f["obs/cell_type/categories"], h5py.Dataset)


def test_hand_rolled_fixtures_match_anndata_output(tmp_path):
    """The fidelity check behind every other test file: testing.py's
    converters must produce the same on-disk structure anndata does, or the
    whole suite quietly tests an invented format."""
    real = tmp_path / "real.h5ad"
    adata = ad.AnnData(
        X=np.zeros((3, 2), dtype=np.float32),
        obs=pd.DataFrame(index=pd.Index(pd.array(["c1", "c2", "c3"], dtype="string"))),
    )
    write_h5ad_with_nullable_strings(adata, real)

    fake = tmp_path / "fake.h5ad"
    ad.AnnData(X=np.zeros((3, 2), dtype=np.float32), obs=pd.DataFrame(index=["c1", "c2", "c3"])).write_h5ad(fake)
    make_nullable_index(fake)

    with h5py.File(real) as fr, h5py.File(fake) as ff:
        real_idx, fake_idx = fr["obs/_index"], ff["obs/_index"]
        assert isinstance(fake_idx, h5py.Group) and isinstance(real_idx, h5py.Group)
        assert sorted(real_idx) == sorted(fake_idx)
        for key in ("encoding-type", "encoding-version"):
            assert real_idx.attrs[key] == fake_idx.attrs[key], key
            for child in ("values", "mask"):
                assert real_idx[child].attrs[key] == fake_idx[child].attrs[key], (child, key)
        assert real_idx["mask"].dtype == fake_idx["mask"].dtype
        assert read_element(real_idx).tolist() == read_element(fake_idx).tolist()


def _entry() -> list[dict]:
    return [
        {
            "timestamp": "2026-08-27T00:00:00Z",
            "tool": "test",
            "tool_version": "0.0.1",
            "operation": "test_op",
            "description": "matrix test",
        }
    ]


def test_funnel_normalizes_categorical_index_and_bare_uns_shapes(tmp_path, sample_h5ad):
    """The nullable dtype can hide a level down: a CategoricalIndex whose
    categories are StringDtype, and bare uns arrays/categoricals — all the
    read-back shapes of #638-style files. The funnel normalizes every one
    (an earlier revision missed these and anndata raised after streaming X).
    """
    import shutil

    src = tmp_path / "cat_index.h5ad"
    shutil.copy2(sample_h5ad, src)
    adata = ad.read_h5ad(src)
    adata.obs.index = pd.CategoricalIndex(pd.array([f"c{i}" for i in range(adata.n_obs)], dtype="string"))
    adata.uns["grades"] = pd.Categorical(pd.array(["hi", "lo"], dtype="string"))
    adata.uns["tags"] = pd.array(["t1", "t2"], dtype="string")

    result = write_h5ad(adata, str(src), _entry())

    assert "error" not in result, result.get("error")
    assert {"obs index", "uns['grades']", "uns['tags']"} <= set(result["encodings_normalized"])
    enc = get_storage_info(result["output_path"])["encodings"]
    assert enc["unsupported_count"] == 0
    assert enc["obs"]["index"] == "string-array"  # flattened, not a categorical group
    out = ad.read_h5ad(result["output_path"])
    assert list(out.obs_names) == [f"c{i}" for i in range(adata.n_obs)]


def test_file_walk_normalizes_a_bare_uns_categorical(tmp_path):
    """convert's h5py pass covers uns categoricals too: anndata writes a
    bare uns Categorical of StringDtype with a nullable-string-array
    categories child, and the walker must normalize it — the contract's
    'only profile encodings' claim has no uns carve-out."""
    from hca_anndata_tools._io import normalize_file_string_encodings

    path = tmp_path / "uns_cat.h5ad"
    adata = ad.AnnData(X=np.zeros((2, 2), dtype=np.float32), obs=pd.DataFrame(index=["c1", "c2"]))
    adata.uns["grades"] = pd.Categorical(pd.array(["hi", "lo", "hi"], dtype="string"))
    write_h5ad_with_nullable_strings(adata, path)
    with h5py.File(path) as f:
        assert encoding_of(f["uns/grades/categories"]) == "nullable-string-array"

    with h5py.File(path, "r+") as f:
        normalized, err = normalize_file_string_encodings(f)

    assert err is None
    assert "uns/grades/categories" in normalized
    with h5py.File(path) as f:
        assert encoding_of(f["uns/grades/categories"]) == "string-array"


def test_normalize_raw_reports_encodings_normalized(tmp_path):
    """The skills claim every write_h5ad-based tool reports what it
    normalized — pin it for normalize_raw, not just compress."""
    from hca_anndata_tools.normalize import normalize_raw

    path = tmp_path / "raw_nullable.h5ad"
    n = 4
    obs = pd.DataFrame(
        {"lib": pd.array([f"L{i}" for i in range(n)], dtype="string")},
        index=[f"c{i}" for i in range(n)],
    )
    X = sp.random(n, 3, density=0.9, format="csr", dtype=np.float32)
    X.data = np.round(X.data * 10) + 1
    write_h5ad_with_nullable_strings(ad.AnnData(X=X, obs=obs), path)

    result = normalize_raw(str(path))

    assert "error" not in result, result.get("error")
    assert "obs['lib']" in result["encodings_normalized"]


def test_funnel_leaves_a_numeric_categorical_index_alone(tmp_path):
    """Flattening a numeric CategoricalIndex would hand anndata's string
    writer integers — a post-stream TypeError on files that write fine. Its
    serialization is in-profile as it stands, so the funnel must not touch
    it (caught by review on the first cut)."""
    path = tmp_path / "numeric_cat_idx.h5ad"
    adata = ad.AnnData(X=np.zeros((3, 2), dtype=np.float32), obs=pd.DataFrame(index=["c1", "c2", "c3"]))
    adata.uns["tbl"] = pd.DataFrame({"v": [1.0, 2.0]}, index=pd.CategoricalIndex([10, 20]))
    adata.write_h5ad(path)

    out = ad.read_h5ad(path)
    result = write_h5ad(out, str(path), _entry())

    assert "error" not in result, result.get("error")
    assert "encodings_normalized" not in result
