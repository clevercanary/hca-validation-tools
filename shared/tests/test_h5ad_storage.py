"""Tests for hca_validation.h5ad_storage.get_matrix_storage.

Fixtures are built with pure h5py (no anndata) so we can pin exact dtypes —
notably the int32-vs-int64 index case that drives the resident-bytes math.
"""

import h5py
import numpy as np

from hca_validation.h5ad_storage import get_matrix_storage


def _write_csr(group, *, shape, data, indices, indptr):
    group.attrs["encoding-type"] = "csr_matrix"
    group.attrs["shape"] = np.array(shape, dtype="int64")
    group.create_dataset("data", data=data)
    group.create_dataset("indices", data=indices)
    group.create_dataset("indptr", data=indptr)


# The 3x4 matrix [[5,0,0,2],[0,0,0,0],[0,7,8,0]] -> nnz=4
_DATA = np.array([5, 2, 7, 8], dtype="float32")
_INDICES = np.array([0, 3, 1, 2])
_INDPTR = np.array([0, 2, 2, 4])


def _make_file(path, *, with_raw=True, with_layer_int64=True):
    with h5py.File(path, "w") as f:
        _write_csr(
            f.create_group("X"),
            shape=(3, 4), data=_DATA,
            indices=_INDICES.astype("int32"), indptr=_INDPTR.astype("int32"),
        )
        if with_raw:
            _write_csr(
                f.create_group("raw").create_group("X"),
                shape=(3, 4), data=_DATA,
                indices=_INDICES.astype("int32"), indptr=_INDPTR.astype("int32"),
            )
        if with_layer_int64:
            _write_csr(
                f.create_group("layers").create_group("denoised"),
                shape=(3, 4), data=_DATA,
                indices=_INDICES.astype("int64"), indptr=_INDPTR.astype("int64"),
            )


def test_x_sparse_facts(tmp_path):
    path = tmp_path / "t.h5ad"
    _make_file(path)
    r = get_matrix_storage(str(path))

    x = r["X"]
    assert x["format"] == "csr_matrix"
    assert (x["n_obs"], x["n_vars"]) == (3, 4)
    assert x["nnz"] == 4
    assert x["data_dtype"] == "float32"
    assert x["index_dtype"] == "int32"
    # resident = nnz*(data_itemsize + index_itemsize) + indptr_len*indptr_itemsize
    assert x["resident_bytes"] == 4 * (4 + 4) + 4 * 4


def test_int64_layer_doubles_index_cost(tmp_path):
    path = tmp_path / "t.h5ad"
    _make_file(path)
    r = get_matrix_storage(str(path))

    layer = r["layers"]["denoised"]
    assert layer["index_dtype"] == "int64"
    # int64 indices (8B) + int64 indptr (8B): 4*(4+8) + 4*8
    assert layer["resident_bytes"] == 4 * (4 + 8) + 4 * 8
    # ... which is larger than the int32-indexed X holding identical data
    assert layer["resident_bytes"] > r["X"]["resident_bytes"]


def test_raw_present_and_absent(tmp_path):
    with_raw = tmp_path / "with_raw.h5ad"
    _make_file(with_raw, with_raw=True)
    assert get_matrix_storage(str(with_raw))["raw_X"] is not None

    no_raw = tmp_path / "no_raw.h5ad"
    _make_file(no_raw, with_raw=False)
    assert get_matrix_storage(str(no_raw))["raw_X"] is None


def test_no_layers_returns_none(tmp_path):
    path = tmp_path / "t.h5ad"
    _make_file(path, with_layer_int64=False)
    assert get_matrix_storage(str(path))["layers"] is None


def test_unrecognized_layer_node_is_filtered(tmp_path):
    """Layers that aren't sparse/dense matrices must not leak None into the
    documented {name: {...}} shape."""
    path = tmp_path / "t.h5ad"
    _make_file(path, with_layer_int64=True)
    with h5py.File(path, "a") as f:
        # A plain group with no encoding-type is not a recognizable matrix.
        f["layers"].create_group("not_a_matrix")

    layers = get_matrix_storage(str(path))["layers"]
    assert "not_a_matrix" not in layers          # filtered out, no None value
    assert "denoised" in layers                  # the real matrix survives
    assert all(v is not None for v in layers.values())


def test_incomplete_sparse_node_is_unrecognized(tmp_path):
    """A node advertising a sparse encoding but missing data/indices/indptr is
    treated as unrecognized (None), not a KeyError that fails the whole call."""
    path = tmp_path / "t.h5ad"
    _make_file(path, with_raw=True, with_layer_int64=True)
    with h5py.File(path, "a") as f:
        # X advertises csr_matrix but is missing 'indptr'.
        del f["X"]["indptr"]

    result = get_matrix_storage(str(path))
    assert result["X"] is None                  # degraded, not raised
    assert result["raw_X"] is not None          # other matrices still reported
    assert result["layers"]["denoised"] is not None


def test_only_unrecognized_layers_returns_none(tmp_path):
    """If no layer is a matrix, layers collapses to None, not an empty dict."""
    path = tmp_path / "t.h5ad"
    _make_file(path, with_layer_int64=False)
    with h5py.File(path, "a") as f:
        f.create_group("layers").create_group("not_a_matrix")
    assert get_matrix_storage(str(path))["layers"] is None
