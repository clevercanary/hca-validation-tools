"""Tests for extracted helper functions in _io.py and write.py."""

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp

from hca_anndata_tools._io import (
    read_categorical_data,
    read_obs_index,
    transplant_obs_columns,
    update_column_order,
    verify_categorical_integrity,
    verify_obs_transplant,
)
from hca_anndata_tools.write import build_edit_log, cleanup_previous_version


# -- read_obs_index -----------------------------------------------------------


def test_read_obs_index(tmp_path):
    ids = ["cell_A", "cell_B", "cell_C"]
    adata = ad.AnnData(
        X=sp.csr_matrix((3, 2), dtype=np.float32),
        obs=pd.DataFrame(index=ids),
    )
    path = tmp_path / "test.h5ad"
    adata.write_h5ad(path)
    assert read_obs_index(str(path)) == ids


def test_read_obs_index_preserves_order(tmp_path):
    ids = ["z_last", "a_first", "m_middle"]
    adata = ad.AnnData(
        X=sp.csr_matrix((3, 2), dtype=np.float32),
        obs=pd.DataFrame(index=ids),
    )
    path = tmp_path / "order.h5ad"
    adata.write_h5ad(path)
    assert read_obs_index(str(path)) == ids


# -- read_categorical_data -----------------------------------------------------


def test_read_categorical_data(tmp_path):
    path = tmp_path / "cat.h5ad"
    obs = pd.DataFrame(
        {"col": pd.Categorical(["a", "b", "a"])},
        index=["c0", "c1", "c2"],
    )
    adata = ad.AnnData(X=sp.csr_matrix((3, 2), dtype=np.float32), obs=obs)
    adata.write_h5ad(path)

    with h5py.File(path, "r") as f:
        cats, codes = read_categorical_data(f["obs"]["col"])
        assert cats == ["a", "b"]
        assert len(codes) == 3
        # Verify codes map correctly: a=0, b=1, a=0
        assert cats[codes[0]] == "a"
        assert cats[codes[1]] == "b"
        assert cats[codes[2]] == "a"


# -- update_column_order ------------------------------------------------------


def test_update_column_order_append(tmp_path):
    path = tmp_path / "order.h5ad"
    obs = pd.DataFrame({"a": [1], "b": [2]}, index=["c0"])
    adata = ad.AnnData(X=sp.csr_matrix((1, 1), dtype=np.float32), obs=obs)
    adata.write_h5ad(path)

    with h5py.File(path, "a") as f:
        update_column_order(f, ["c", "d"])
        order = [v.decode() if isinstance(v, bytes) else v for v in f["obs"].attrs["column-order"]]
        assert order == ["a", "b", "c", "d"]


def test_update_column_order_with_deleted(tmp_path):
    path = tmp_path / "order2.h5ad"
    obs = pd.DataFrame({"a": [1], "b": [2], "c": [3]}, index=["c0"])
    adata = ad.AnnData(X=sp.csr_matrix((1, 1), dtype=np.float32), obs=obs)
    adata.write_h5ad(path)

    with h5py.File(path, "a") as f:
        update_column_order(f, ["d"], deleted={"b"})
        order = [v.decode() if isinstance(v, bytes) else v for v in f["obs"].attrs["column-order"]]
        assert "b" not in order
        assert order == ["a", "c", "d"]


# -- transplant_obs_columns ---------------------------------------------------


def test_transplant_obs_columns_basic(tmp_path):
    # Create source with extra column
    src_path = tmp_path / "src.h5ad"
    obs_src = pd.DataFrame({"new_col": pd.Categorical(["x", "y"])}, index=["c0", "c1"])
    ad.AnnData(X=np.empty((2, 0), dtype=np.float32), obs=obs_src).write_h5ad(src_path)

    # Create target without that column
    tgt_path = tmp_path / "tgt.h5ad"
    obs_tgt = pd.DataFrame({"existing": [1, 2]}, index=["c0", "c1"])
    ad.AnnData(X=sp.csr_matrix((2, 2), dtype=np.float32), obs=obs_tgt).write_h5ad(tgt_path)

    with h5py.File(src_path, "r") as f_src, h5py.File(tgt_path, "a") as f_tgt:
        transplant_obs_columns(f_src, f_tgt, ["new_col"])

    written = ad.read_h5ad(tgt_path)
    assert "new_col" in written.obs.columns
    assert "existing" in written.obs.columns
    assert list(written.obs["new_col"]) == ["x", "y"]
    # Verify column-order includes new column
    with h5py.File(tgt_path, "r") as f:
        order = [v.decode() if isinstance(v, bytes) else v for v in f["obs"].attrs["column-order"]]
        assert "new_col" in order
        assert "existing" in order


# -- verify_obs_transplant ----------------------------------------------------


@pytest.fixture
def _make_pair(tmp_path):
    """Create a matching temp/output pair with obs columns."""
    def _factory(obs_data: dict, index: list[str], mismatch_col: str | None = None):
        n = len(index)
        obs = pd.DataFrame(obs_data, index=index)
        adata = ad.AnnData(
            X=np.empty((n, 0), dtype=np.float32),
            obs=obs,
        )
        temp_path = tmp_path / "temp.h5ad"
        adata.write_h5ad(temp_path)

        output_path = tmp_path / "output.h5ad"
        adata.write_h5ad(output_path)

        # Optionally corrupt a column in the output
        if mismatch_col:
            with h5py.File(output_path, "a") as f:
                item = f["obs"][mismatch_col]
                if isinstance(item, h5py.Group) and "codes" in item:
                    codes = item["codes"][:]
                    codes[0] = (codes[0] + 1) % max(codes.max() + 1, 2)
                    item["codes"][...] = codes

        return str(temp_path), str(output_path)
    return _factory


def test_verify_matching_categorical(_make_pair):
    temp, output = _make_pair(
        {"label": pd.Categorical(["typeA", "typeB", "typeA"])},
        ["c0", "c1", "c2"],
    )
    assert verify_obs_transplant(temp, output, ["label"]) is None


def test_verify_matching_string(_make_pair):
    temp, output = _make_pair(
        {"name": ["alice", "bob", "carol"]},
        ["c0", "c1", "c2"],
    )
    assert verify_obs_transplant(temp, output, ["name"]) is None


def test_verify_mismatch_detected(_make_pair):
    temp, output = _make_pair(
        {"label": pd.Categorical(["typeA", "typeB", "typeA"])},
        ["c0", "c1", "c2"],
        mismatch_col="label",
    )
    result = verify_obs_transplant(temp, output, ["label"])
    assert result is not None
    assert "codes mismatch" in result


def test_verify_categories_mismatch(tmp_path):
    """Different category names should be detected."""
    n = 3
    index = ["c0", "c1", "c2"]

    temp_adata = ad.AnnData(
        X=np.empty((n, 0), dtype=np.float32),
        obs=pd.DataFrame({"label": pd.Categorical(["typeA", "typeB", "typeA"])}, index=index),
    )
    temp_path = tmp_path / "temp.h5ad"
    temp_adata.write_h5ad(temp_path)

    out_adata = ad.AnnData(
        X=np.empty((n, 0), dtype=np.float32),
        obs=pd.DataFrame({"label": pd.Categorical(["typeX", "typeY", "typeX"])}, index=index),
    )
    out_path = tmp_path / "output.h5ad"
    out_adata.write_h5ad(out_path)

    result = verify_obs_transplant(str(temp_path), str(out_path), ["label"])
    assert result is not None
    assert "categories mismatch" in result


def test_verify_empty_columns(_make_pair):
    temp, output = _make_pair({}, ["c0", "c1"])
    assert verify_obs_transplant(temp, output, []) is None


# -- verify_categorical_integrity ----------------------------------------------


def _make_categorical_h5ad(tmp_path, categories, codes, name="test_col"):
    n = len(codes)
    obs = pd.DataFrame(
        {name: pd.Categorical.from_codes(codes, categories=categories)},
        index=[f"c{i}" for i in range(n)],
    )
    adata = ad.AnnData(X=sp.csr_matrix((n, 2), dtype=np.float32), obs=obs)
    path = tmp_path / "cat_test.h5ad"
    adata.write_h5ad(path)
    return str(path)


def test_verify_categorical_valid(tmp_path):
    path = _make_categorical_h5ad(tmp_path, ["a", "b"], [0, 1, 0, -1])
    with h5py.File(path, "r") as f:
        assert verify_categorical_integrity(f, ["test_col"]) is None


def test_verify_categorical_code_out_of_range(tmp_path):
    path = _make_categorical_h5ad(tmp_path, ["a", "b"], [0, 1, 0])
    with h5py.File(path, "a") as f:
        f["obs"]["test_col"]["codes"][1] = 5
    with h5py.File(path, "r") as f:
        result = verify_categorical_integrity(f, ["test_col"])
        assert result is not None
        assert "max code" in result


def test_verify_categorical_expected_valid_counts(tmp_path):
    path = _make_categorical_h5ad(tmp_path, ["a", "b"], [0, 1, -1])
    with h5py.File(path, "r") as f:
        assert verify_categorical_integrity(f, ["test_col"], {"test_col": 2}) is None
        result = verify_categorical_integrity(f, ["test_col"], {"test_col": 3})
        assert result is not None
        assert "expected 3 valid" in result


def test_verify_catches_nan_to_valid_corruption(tmp_path):
    """Simulate the bug where NaN codes (-1) get remapped to a valid category."""
    # Start with: a=0, b=1, NaN=-1  → 2 valid values
    path = _make_categorical_h5ad(tmp_path, ["a", "b"], [0, 1, -1])

    # Corrupt: change the NaN (-1) to a valid code (0), simulating the bug
    with h5py.File(path, "a") as f:
        codes = f["obs"]["test_col"]["codes"][:]
        codes[2] = 0  # NaN cell now points to "a"
        f["obs"]["test_col"]["codes"][...] = codes

    # The structural check passes (codes are in range)
    with h5py.File(path, "r") as f:
        assert verify_categorical_integrity(f, ["test_col"]) is None

    # But the valid count check catches it (expected 2, got 3)
    with h5py.File(path, "r") as f:
        result = verify_categorical_integrity(f, ["test_col"], {"test_col": 2})
        assert result is not None
        assert "expected 2 valid values, got 3" in result


# -- build_edit_log ------------------------------------------------------------


def test_build_edit_log_basic(tmp_path):
    path = tmp_path / "test.h5ad"
    path.write_bytes(b"fake content for sha256")

    result = build_edit_log(
        "[]",
        [{"timestamp": "t", "tool": "test", "tool_version": "1", "operation": "op", "description": "d"}],
        str(path),
    )
    assert "json" in result
    assert "error" not in result

    import json
    log = json.loads(result["json"])
    assert len(log) == 1
    assert log[0]["tool"] == "test"
    assert "source_file" in log[0]
    assert "source_sha256" in log[0]


def test_build_edit_log_appends(tmp_path):
    import json
    path = tmp_path / "test.h5ad"
    path.write_bytes(b"content")

    existing = json.dumps([{"old": "entry"}])
    entry = {"timestamp": "t", "tool": "test", "tool_version": "1", "operation": "op", "description": "d"}
    result = build_edit_log(existing, [entry], str(path))
    log = json.loads(result["json"])
    assert len(log) == 2
    assert log[0]["old"] == "entry"
    assert log[1]["tool"] == "test"


def test_build_edit_log_precomputed_sha(tmp_path):
    path = tmp_path / "test.h5ad"
    path.write_bytes(b"content")

    entry = {"timestamp": "t", "tool": "test", "tool_version": "1", "operation": "op", "description": "d"}
    result = build_edit_log("[]", [entry], str(path), source_sha256="abc123")

    import json
    log = json.loads(result["json"])
    assert log[0]["source_sha256"] == "abc123"


def test_build_edit_log_missing_keys(tmp_path):
    path = tmp_path / "test.h5ad"
    path.write_bytes(b"content")
    result = build_edit_log("[]", [{"timestamp": "t"}], str(path))
    assert "error" in result
    assert "missing required keys" in result["error"]


def test_build_edit_log_empty_entries(tmp_path):
    path = tmp_path / "test.h5ad"
    path.write_bytes(b"content")
    result = build_edit_log("[]", [], str(path))
    assert "error" in result


def test_build_edit_log_corrupt_json(tmp_path):
    path = tmp_path / "test.h5ad"
    path.write_bytes(b"content")
    entry = {"timestamp": "t", "tool": "test", "tool_version": "1", "operation": "op", "description": "d"}
    result = build_edit_log("{not json", [entry], str(path))
    assert "error" in result
    assert "invalid JSON" in result["error"]


# -- cleanup_previous_version --------------------------------------------------


def test_cleanup_deletes_timestamped(tmp_path):
    old = tmp_path / "file-edit-2026-01-01-00-00-00.h5ad"
    new = tmp_path / "file-edit-2026-01-02-00-00-00.h5ad"
    old.write_bytes(b"old")
    new.write_bytes(b"new")
    cleanup_previous_version(str(old), str(new))
    assert not old.exists()
    assert new.exists()


def test_cleanup_preserves_original(tmp_path):
    original = tmp_path / "file.h5ad"
    new = tmp_path / "file-edit-2026-01-01-00-00-00.h5ad"
    original.write_bytes(b"original")
    new.write_bytes(b"new")
    cleanup_previous_version(str(original), str(new))
    assert original.exists()
    assert new.exists()


def test_cleanup_same_path_noop(tmp_path):
    path = tmp_path / "file-edit-2026-01-01-00-00-00.h5ad"
    path.write_bytes(b"content")
    cleanup_previous_version(str(path), str(path))
    assert path.exists()
