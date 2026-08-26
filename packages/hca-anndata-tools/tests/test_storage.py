"""Tests for the get_storage_info function."""

import shutil
from pathlib import Path

import h5py
import numpy as np

from hca_anndata_tools._io import obs_index_name
from hca_anndata_tools.storage import _MAX_UNSUPPORTED_PATHS, get_storage_info
from hca_anndata_tools.testing import make_fixed_width_byte_array, make_nullable_string_array


def test_storage_file_size(sample_h5ad):
    result = get_storage_info(str(sample_h5ad))
    assert "error" not in result
    assert result["file_size_bytes"] > 0
    assert result["file_size_mb"] >= 0


def test_storage_x_info(sample_h5ad):
    result = get_storage_info(str(sample_h5ad))
    # Sample h5ad has a sparse X matrix, stored as a group
    x = result["X"]
    assert x is not None
    assert "format" in x or "dtype" in x


def test_storage_layers(sample_h5ad):
    result = get_storage_info(str(sample_h5ad))
    layers = result["layers"]
    assert layers is not None
    assert "raw_counts" in layers


def test_storage_raw_x_absent(sample_h5ad):
    """Sample file has no raw.X."""
    result = get_storage_info(str(sample_h5ad))
    assert result["raw_X"] is None


def test_storage_non_h5ad():
    result = get_storage_info("/some/path/file.zarr")
    assert "error" in result
    assert "h5ad" in result["error"].lower()


def test_storage_missing_file():
    result = get_storage_info("/nonexistent/file.h5ad")
    assert "error" in result


# --- encodings block (hca-validation-tools#638) -----------------------------


def _nullable_copy(src: Path, dest: Path, *, masked: int = 0, columns: tuple[str, ...] = ()) -> Path:
    """Copy ``src``, rewriting its obs index — and any named categorical
    columns' ``categories`` — as ``nullable-string-array``.

    Columns are named explicitly rather than discovered, so a test that
    asserts on a categorical says which one it broke.
    """
    shutil.copy2(src, dest)
    with h5py.File(dest, "r+") as f:
        obs = f["obs"]
        make_nullable_string_array(obs, obs_index_name(obs), masked=masked)
        for column in columns:
            make_nullable_string_array(obs[column], "categories")
    return dest


def test_encodings_reported_for_plain_file(sample_h5ad):
    """A file written by AnnData uses string-array throughout and flags nothing."""
    enc = get_storage_info(str(sample_h5ad))["encodings"]
    assert enc["obs"]["index"] == "string-array"
    assert enc["var"]["index"] == "string-array"
    assert enc["unsupported"] == []
    assert enc["unsupported_count"] == 0
    assert enc["unsupported_truncated"] is False


def test_encodings_does_not_flag_a_fixed_width_byte_index(sample_h5ad, tmp_path):
    """``array`` on a Dataset is writable — the report must agree with rename.

    This is the same predicate rename_cell_ids refuses on. When the two
    disagreed, get_storage_info called this file clean and rename refused it
    (hca-validation-tools#637 review).
    """
    path = tmp_path / "fixed.h5ad"
    shutil.copy2(sample_h5ad, path)
    with h5py.File(path, "r+") as f:
        obs = f["obs"]
        make_fixed_width_byte_array(obs, obs_index_name(obs))

    enc = get_storage_info(str(path))["encodings"]
    assert enc["obs"]["index"] == "array"
    assert enc["unsupported"] == []
    assert enc["unsupported_count"] == 0


def test_encodings_index_masked_is_none_when_not_nullable(sample_h5ad):
    """None, not 0: a plain string array cannot hold nulls at all."""
    assert get_storage_info(str(sample_h5ad))["encodings"]["obs"]["index_masked"] is None


def test_encodings_absent_dataframe_reported_as_none(sample_h5ad):
    """raw.var keeps a stable key even when the file has no raw."""
    assert get_storage_info(str(sample_h5ad))["encodings"]["raw.var"] is None


def test_encodings_flags_nullable_index(sample_h5ad, tmp_path):
    """The encoding that broke convert_cellxgene_to_hca is named and flagged."""
    path = _nullable_copy(sample_h5ad, tmp_path / "nullable.h5ad")
    enc = get_storage_info(str(path))["encodings"]
    assert enc["obs"]["index"] == "nullable-string-array"
    assert "obs/_index" in enc["unsupported"]


def test_encodings_reports_mask_count(sample_h5ad, tmp_path):
    """A masked index is a data problem, counted separately from compatibility."""
    path = _nullable_copy(sample_h5ad, tmp_path / "masked.h5ad", masked=3)
    assert get_storage_info(str(path))["encodings"]["obs"]["index_masked"] == 3


def test_encodings_flags_nested_categorical_categories(sample_h5ad, tmp_path):
    """A categorical whose categories are themselves nullable is flagged too.

    Checking only the column's own encoding-type would miss this — which is
    exactly how the liver files hid the problem.
    """
    path = _nullable_copy(sample_h5ad, tmp_path / "nested.h5ad", columns=("cell_type",))
    enc = get_storage_info(str(path))["encodings"]
    assert enc["obs"]["categoricals"].get("nullable-string-array") == 1
    assert any(p.endswith("/categories") for p in enc["unsupported"])


def test_encodings_unsupported_paths_are_capped_but_count_is_whole(sample_h5ad, tmp_path):
    """A wholly-nullable file must not flood the report with every path.

    Builds enough nullable categoricals to cross the cap — the earlier
    version of this test converted a single column, so truncation never
    fired and every assertion passed by construction.
    """
    path = tmp_path / "many.h5ad"
    shutil.copy2(sample_h5ad, path)
    extra = _MAX_UNSUPPORTED_PATHS + 2
    with h5py.File(path, "r+") as f:
        obs = f["obs"]
        n = obs[obs_index_name(obs)].shape[0]
        for i in range(extra):
            grp = obs.create_group(f"nullable_cat_{i}")
            grp.attrs["encoding-type"] = "categorical"
            grp.attrs["encoding-version"] = "0.2.0"
            grp.create_dataset("categories", data=np.array([b"a", b"b"]))
            grp.create_dataset("codes", data=np.zeros(n, dtype="i1"))
            make_nullable_string_array(grp, "categories")

    enc = get_storage_info(str(path))["encodings"]
    assert enc["unsupported_count"] == extra
    assert len(enc["unsupported"]) == _MAX_UNSUPPORTED_PATHS
    assert enc["unsupported_truncated"] is True


def test_encodings_unsupported_paths_are_on_disk_paths(sample_h5ad, tmp_path):
    """Reported paths must be usable with h5py or grep.

    ``raw.var`` is the AnnData spelling; the file stores it at ``raw/var``,
    and a sample path that no lookup resolves is not actionable.
    """
    path = _nullable_copy(sample_h5ad, tmp_path / "paths.h5ad")
    enc = get_storage_info(str(path))["encodings"]
    with h5py.File(path, "r") as f:
        for reported in enc["unsupported"]:
            assert reported in f, f"{reported} does not resolve in the file"


def test_encodings_numeric_categorical_is_not_flagged(sample_h5ad, tmp_path):
    """A numeric categorical stores its categories as a plain ``array``
    Dataset. It is directly sliceable, so it must not be reported as
    unreadable — judging by encoding name alone produced exactly that false
    positive on a clean CellxGENE file.
    """
    path = tmp_path / "numeric-cat.h5ad"
    shutil.copy2(sample_h5ad, path)
    with h5py.File(path, "r+") as f:
        grp = f["var"].create_group("length_bin")
        grp.attrs["encoding-type"] = "categorical"
        grp.attrs["encoding-version"] = "0.2.0"
        cats = grp.create_dataset("categories", data=np.array([10, 20, 30]))
        cats.attrs["encoding-type"] = "array"
        grp.create_dataset("codes", data=np.zeros(f["var"]["_index"].shape[0], dtype="i1"))
    enc = get_storage_info(str(path))["encodings"]
    assert enc["var"]["categoricals"].get("array") == 1
    assert not any("length_bin" in p for p in enc["unsupported"])


def test_encodings_covers_obsm_dataframe_indexes(sample_h5ad, tmp_path):
    """An obsm DataFrame's own index is read the same way obs's is.

    rename_cell_ids walks obsm frames and reads each index with
    read_string_dataset, so a nullable index there fails mid-rename. Missing
    it would let a file report a clean bill of health and still crash.
    """
    path = tmp_path / "obsm.h5ad"
    shutil.copy2(sample_h5ad, path)
    with h5py.File(path, "r+") as f:
        frame = f["obsm"].create_group("df_frame")
        frame.attrs["encoding-type"] = "dataframe"
        frame.attrs["encoding-version"] = "0.2.0"
        frame.attrs["_index"] = "_index"
        frame.attrs["column-order"] = np.array([], dtype=h5py.string_dtype())
        ids = f["obs"][obs_index_name(f["obs"])][:]
        ds = frame.create_dataset("_index", data=ids)
        ds.attrs["encoding-type"] = "string-array"
        make_nullable_string_array(frame, "_index")

    enc = get_storage_info(str(path))["encodings"]
    assert enc["obsm"]["df_frame"]["index"] == "nullable-string-array"
    assert "obsm/df_frame/_index" in enc["unsupported"]


def test_encodings_obsm_arrays_are_not_dataframes(sample_h5ad):
    """Plain obsm arrays (X_umap etc.) have no index and must not appear."""
    assert get_storage_info(str(sample_h5ad))["encodings"]["obsm"] == {}


def test_encodings_failure_does_not_discard_the_rest_of_the_report(sample_h5ad, tmp_path, monkeypatch):
    """A broken encodings walk must not blank size and compression.

    curate-h5ad reads the compression report to decide whether to run
    compress_h5ad, so a purely diagnostic addition must never cost the
    caller information it previously got.
    """
    path = tmp_path / "boom.h5ad"
    shutil.copy2(sample_h5ad, path)
    monkeypatch.setattr(
        "hca_anndata_tools.storage._encodings_info",
        lambda _f: (_ for _ in ()).throw(RuntimeError("structural surprise")),
    )
    result = get_storage_info(str(path))
    assert "error" not in result
    assert result["file_size_bytes"] > 0
    # The concrete fields a caller would lose if the whole result collapsed:
    # curate-h5ad reads these to decide whether to run compress_h5ad.
    assert result["X"]["format"] == "csr_matrix"
    assert "compression" in result["X"]["data"]
    assert result["X"]["data"]["shape"]
    assert result["encodings"]["error"] == "structural surprise"


def test_encodings_unstamped_index_is_labelled_not_null(sample_h5ad, tmp_path):
    """Older AnnData wrote string arrays with no encoding-type.

    That is a real encoding state and must not be reported as ``null``,
    which the skill treats as "this dataframe is absent".
    """
    path = tmp_path / "unstamped.h5ad"
    shutil.copy2(sample_h5ad, path)
    with h5py.File(path, "r+") as f:
        obs = f["obs"]
        del obs[obs_index_name(obs)].attrs["encoding-type"]
    enc = get_storage_info(str(path))["encodings"]
    assert enc["obs"]["index"] == "unstamped"
    assert enc["obs"]["index"] is not None
