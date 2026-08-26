"""Tests for the get_storage_info function."""

import shutil
from pathlib import Path

import h5py
import numpy as np

from hca_anndata_tools._io import obs_index_name
from hca_anndata_tools.storage import get_storage_info
from hca_anndata_tools.testing import make_nullable_string_array


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


def _nullable_copy(src: Path, dest: Path, *, masked: int = 0, categorical: bool = False) -> Path:
    """Copy ``src`` and rewrite its obs index (and optionally a categorical)
    as ``nullable-string-array``."""
    shutil.copy2(src, dest)
    with h5py.File(dest, "r+") as f:
        obs = f["obs"]
        make_nullable_string_array(obs, obs_index_name(obs), masked=masked)
        if categorical:
            for name in obs:
                item = obs[name]
                if isinstance(item, h5py.Group) and "categories" in item:
                    make_nullable_string_array(item, "categories")
                    break
    return dest


def test_encodings_reported_for_plain_file(sample_h5ad):
    """A file written by AnnData uses string-array throughout and flags nothing."""
    enc = get_storage_info(str(sample_h5ad))["encodings"]
    assert enc["obs"]["index"] == "string-array"
    assert enc["var"]["index"] == "string-array"
    assert enc["unsupported"] == []


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
    path = _nullable_copy(sample_h5ad, tmp_path / "nested.h5ad", categorical=True)
    enc = get_storage_info(str(path))["encodings"]
    assert enc["obs"]["categoricals"].get("nullable-string-array") == 1
    assert any(p.endswith("/categories") for p in enc["unsupported"])


def test_encodings_unsupported_paths_are_capped_but_count_is_whole(sample_h5ad, tmp_path):
    """A wholly-nullable file must not flood the report with every path.

    The count stays exact — it is the actionable number — while the paths
    are a bounded sample.
    """
    path = _nullable_copy(sample_h5ad, tmp_path / "many.h5ad", categorical=True)
    enc = get_storage_info(str(path))["encodings"]
    assert enc["unsupported_count"] >= len(enc["unsupported"])
    assert len(enc["unsupported"]) <= 10
    assert enc["unsupported_truncated"] is (enc["unsupported_count"] > 10)


def test_encodings_clean_file_reports_zero_and_no_truncation(sample_h5ad):
    enc = get_storage_info(str(sample_h5ad))["encodings"]
    assert enc["unsupported_count"] == 0
    assert enc["unsupported_truncated"] is False


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
