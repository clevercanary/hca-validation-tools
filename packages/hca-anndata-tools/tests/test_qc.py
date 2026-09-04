"""Tests for the count gate (#686).

Fixtures are built with anndata's own writer from dense numpy, then converted
to the format under test — never through ``iter_matrix_chunks`` or anything
in ``qc``, so the reader's bugs cannot hide in the fixture (contract,
principle 17). Each finding-code fixture is the clean base plus exactly one
defect, so "that code and nothing else" is what every parametrised case
asserts.
"""

from __future__ import annotations

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pytest

from hca_anndata_tools._errors import Refusal
from hca_anndata_tools.qc import SAMPLE_ID_LIMIT, check_raw_counts, iter_matrix_chunks
from hca_anndata_tools.testing import make_nullable_index, write_matrix_h5ad

FORMATS = ["csr", "csc", "dense"]

# 6 cells x 5 genes, every row and column non-zero, integer-valued floats.
BASE = np.array(
    [
        [3, 0, 1, 0, 2],
        [0, 4, 0, 1, 0],
        [1, 0, 0, 2, 0],
        [0, 1, 5, 0, 1],
        [2, 0, 0, 3, 0],
        [0, 2, 1, 0, 4],
    ],
    dtype=np.float32,
)


_write = write_matrix_h5ad


def _codes(result: dict) -> dict[str, dict]:
    assert "error" not in result, result
    return {f["code"]: f for f in result["findings"]}


# --- one fixture per finding code, gated matrix is raw/X ---------------------

# code -> (index into BASE, value written there, IDs the finding must name)
DEFECTS = {
    "negative_values": ((1, 1), -3.0, ["c1"]),
    "non_finite_values": ((2, 3), np.nan, ["c2"]),
    "non_integer_values": ((3, 2), 2.5, ["c3"]),
    "zero_count_cells": ((4, slice(None)), 0.0, ["c4"]),
    "undetected_genes": ((slice(None), 2), 0.0, ["g2"]),
}


@pytest.mark.parametrize("fmt", FORMATS)
@pytest.mark.parametrize("code", list(DEFECTS))
def test_each_code_fires_alone_on_raw_x(tmp_path, fmt, code):
    index, value, ids = DEFECTS[code]
    raw = BASE.copy()
    raw[index] = value
    path = _write(tmp_path / f"{code}.h5ad", BASE, fmt, raw=raw)

    result = check_raw_counts(str(path))

    assert result["matrix"] == "raw/X"
    assert result["format"] == fmt
    assert result["integer_check"]["status"] == "applied"
    found = _codes(result)
    assert list(found) == [code]
    assert found[code]["count"] == 1
    assert found[code]["sample_ids"] == ids
    assert found[code]["element"] == "raw/X"


@pytest.mark.parametrize("fmt", FORMATS)
def test_clean_matrix_yields_no_findings(tmp_path, fmt):
    path = _write(tmp_path / "clean.h5ad", BASE, fmt, raw=BASE)

    result = check_raw_counts(str(path))

    assert _codes(result) == {}
    assert result["n_obs"] == 6
    assert result["n_var"] == 5
    assert result["dtype"] == "float32"  # float storage of integer values passes the integer criterion
    assert result["nnz"] == (None if fmt == "dense" else int(np.count_nonzero(BASE)))


def test_integer_dtype_skips_float_only_criteria(tmp_path):
    m = BASE.astype(np.int32)
    m[1, 1] = -3
    path = _write(tmp_path / "i.h5ad", m, "csr", raw=m)

    result = check_raw_counts(str(path))

    assert result["dtype"] == "int32"
    assert list(_codes(result)) == ["negative_values"]


def test_count_is_values_and_ids_are_cells(tmp_path):
    """Two negative values in one cell, one in another: count 3, two cell IDs."""
    m = BASE.copy()
    m[0, 0] = -1
    m[0, 2] = -1
    m[5, 4] = -1
    path = _write(tmp_path / "n.h5ad", BASE, "csr", raw=m)

    found = _codes(check_raw_counts(str(path)))

    assert found["negative_values"]["count"] == 3
    assert found["negative_values"]["sample_ids"] == ["c0", "c5"]


def test_sample_ids_are_capped(tmp_path):
    n = SAMPLE_ID_LIMIT + 5
    m = np.ones((n, 3), dtype=np.float32)
    m[:, 0] = -1
    path = _write(tmp_path / "cap.h5ad", m, "csr", raw=m)

    found = _codes(check_raw_counts(str(path)))

    assert found["negative_values"]["count"] == n
    assert len(found["negative_values"]["sample_ids"]) == SAMPLE_ID_LIMIT
    assert found["negative_values"]["sample_ids"][0] == "c0"


# --- lone X: integer applicability and the skipped gene check ---------------


def test_lone_normalized_x_reports_integer_check_not_applicable(tmp_path):
    rng = np.random.default_rng(1)
    X = rng.random((6, 5)).astype(np.float32) + 0.1  # fractional everywhere
    X[2, 3] = -0.5
    path = _write(tmp_path / "norm.h5ad", X, "csr")

    result = check_raw_counts(str(path))

    assert result["matrix"] == "X"
    assert result["integer_check"]["status"] == "not_applicable"
    assert "check_x_normalization" in result["integer_check"]["reason"]
    assert list(_codes(result)) == ["negative_values"]


def test_lone_raw_count_x_applies_integer_check(tmp_path):
    path = _write(tmp_path / "rawx.h5ad", BASE, "csr")

    result = check_raw_counts(str(path))

    assert result["matrix"] == "X"
    assert result["integer_check"]["status"] == "applied"
    assert _codes(result) == {}


def test_lone_x_fractional_past_the_classifier_sample_is_a_finding(tmp_path):
    """check_x_normalization samples the head of X; a fractional value past
    that sample leaves the verdict at raw_counts, and the gate — which reads
    every value — is what reports it. A fractional value *inside* the sample
    flips the verdict to normalized instead, and then the criterion is not
    applied: on a lone X the classifier, not the gate, decides."""
    rng = np.random.default_rng(3)
    m = rng.integers(1, 6, size=(100, 30)).astype(np.float32)  # 3000 stored entries
    m[99, 29] = 2.5  # last entry in CSR data order, past the 2000-entry sample
    path = _write(tmp_path / "tail.h5ad", m, "csr")

    result = check_raw_counts(str(path))

    assert result["integer_check"]["status"] == "applied"
    found = _codes(result)
    assert list(found) == ["non_integer_values"]
    assert found["non_integer_values"]["sample_ids"] == ["c99"]


@pytest.mark.parametrize("fmt", FORMATS)
def test_undetected_genes_is_reported_on_a_lone_x(tmp_path, fmt):
    """The vendored validator scans X for all-zero genes only when raw exists
    (its feature_is_filtered consistency check); on a lone X nobody else
    reports one, so the gate does, naming the gene from var."""
    m = BASE.copy()
    m[:, 2] = 0
    path = _write(tmp_path / "x-only.h5ad", m, fmt)

    result = check_raw_counts(str(path))

    assert result["matrix"] == "X"
    found = _codes(result)
    assert list(found) == ["undetected_genes"]
    assert found["undetected_genes"]["sample_ids"] == ["g2"]
    assert found["undetected_genes"]["element"] == "X"


# --- edges -------------------------------------------------------------------


@pytest.mark.parametrize("shape", [(0, 5), (6, 0)])
def test_empty_matrix_is_the_only_finding(tmp_path, shape):
    path = _write(tmp_path / "empty.h5ad", np.zeros(shape, dtype=np.float32), "csr")

    result = check_raw_counts(str(path))

    assert [f["code"] for f in result["findings"]] == ["empty_matrix"]


def test_nullable_string_index_runs_to_completion(tmp_path):
    path = _write(tmp_path / "nullable.h5ad", BASE, "csr", raw=BASE)
    make_nullable_index(path, "obs")
    make_nullable_index(path, "var")

    result = check_raw_counts(str(path))

    assert _codes(result) == {}


def test_unknown_sparse_encoding_is_refused_by_name(tmp_path):
    """Behind the gate this is unreachable today (anndata reads nothing else
    into X); the undecorated entry point pins the refusal for the day it does."""
    path = _write(tmp_path / "coo.h5ad", BASE, "csr", raw=BASE)
    with h5py.File(path, "r+") as f:
        f["raw/X"].attrs["encoding-type"] = "coo_matrix"

    # __wrapped__ skips the anndata gate, which would otherwise refuse first
    # in anndata's words and never reach ours.
    result = check_raw_counts.__wrapped__(str(path))  # pyright: ignore[reportFunctionMemberAccess]

    assert "coo_matrix" in result["error"]
    assert "csr_matrix, csc_matrix, and dense" in result["error"]
    assert "traceback" not in result


@pytest.mark.parametrize("chunk_nnz", [0, -1, 2.0, "8", True])
def test_bad_chunk_nnz_is_refused(tmp_path, chunk_nnz):
    # The handler's own domain check, shared by every chunked read-only tool.
    path = _write(tmp_path / "c.h5ad", BASE, "csr")
    assert "chunk_nnz must be a positive int" in check_raw_counts(str(path), chunk_nnz=chunk_nnz)["error"]


def test_iterator_refuses_bad_chunk_nnz(tmp_path):
    path = _write(tmp_path / "c.h5ad", BASE, "csr")
    with h5py.File(path, "r") as f, pytest.raises(ValueError, match="chunk_nnz"):
        list(iter_matrix_chunks(f, "X", 0))


def test_missing_file_names_the_path(tmp_path):
    result = check_raw_counts(str(tmp_path / "nope.h5ad"))
    assert result["error"].startswith("File not found")


# --- the chunk iterator: bounded memory, same answer, the axis contract ------


@pytest.mark.parametrize("fmt", FORMATS)
def test_chunks_respect_the_budget_and_agree_with_one_pass(tmp_path, fmt):
    rng = np.random.default_rng(7)
    m = rng.integers(0, 6, size=(120, 40)).astype(np.float32)
    m[10, 3] = -2
    m[50, :] = 0
    m[:, 17] = 0
    m[77, 9] = np.nan
    m[99, 21] = 1.5
    budget = 300  # nnz ~ 120*40*5/6 = 4000 -> a dozen or so chunks
    path = _write(tmp_path / "big.h5ad", m, fmt, raw=m)

    with h5py.File(path, "r") as f:
        chunks = list(iter_matrix_chunks(f, "raw/X", budget, axis="any"))
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.matrix.nnz <= budget or (chunk.matrix.shape[0 if chunk.axis == "row" else 1] == 1)
    # The chunks tile the compressed axis exactly once, in order.
    axis = chunks[0].axis
    covered = sum(c.matrix.shape[0 if axis == "row" else 1] for c in chunks)
    assert covered == (120 if axis == "row" else 40)
    assert [c.start for c in chunks] == sorted(c.start for c in chunks)

    chunked = check_raw_counts(str(path), chunk_nnz=budget)
    assert chunked == check_raw_counts(str(path))
    assert set(_codes(chunked)) == {
        "negative_values",
        "zero_count_cells",
        "undetected_genes",
        "non_finite_values",
        "non_integer_values",
    }


def test_csc_is_walked_by_column_only_on_request(tmp_path):
    """The seam #677 is written against: a row consumer must not silently
    receive column slabs."""
    path = _write(tmp_path / "csc.h5ad", BASE, "csc", raw=BASE)
    with h5py.File(path, "r") as f:
        with pytest.raises(Refusal, match="csc_matrix.*axis='any'"):
            list(iter_matrix_chunks(f, "raw/X", 4))
        chunks = list(iter_matrix_chunks(f, "raw/X", 4, axis="any"))
    assert {c.axis for c in chunks} == {"col"}
    assert sum(c.matrix.shape[1] for c in chunks) == 5


@pytest.mark.parametrize("fmt", ["csr", "dense"])
def test_row_walk_is_the_default_for_row_formats(tmp_path, fmt):
    path = _write(tmp_path / "rows.h5ad", BASE, fmt, raw=BASE)
    with h5py.File(path, "r") as f:
        chunks = list(iter_matrix_chunks(f, "raw/X", 4))
    assert {c.axis for c in chunks} == {"row"}
    assert sum(c.matrix.shape[0] for c in chunks) == 6


# --- refusals for files the gate opens but the walk cannot trust ------------


def test_file_with_no_matrix_is_refused_by_name(tmp_path):
    path = tmp_path / "nox.h5ad"
    ad.AnnData(
        obs=pd.DataFrame(index=["c0", "c1"]),  # pyright: ignore[reportArgumentType]
        var=pd.DataFrame(index=["g0"]),  # pyright: ignore[reportArgumentType]
    ).write_h5ad(path)

    result = check_raw_counts(str(path))

    assert "neither raw/X nor X" in result["error"]
    assert "traceback" not in result


def test_obs_shorter_than_matrix_is_refused_by_name(tmp_path):
    m = BASE.copy()
    m[1, 1] = -3.0
    path = _write(tmp_path / "short-obs.h5ad", BASE, "csr", raw=m)
    with h5py.File(path, "r+") as f:
        obs = f["obs"]
        del obs["_index"]
        obs.create_dataset("_index", data=np.array([f"c{i}" for i in range(4)], dtype="S"))
        obs["_index"].attrs["encoding-type"] = "string-array"
        obs["_index"].attrs["encoding-version"] = "0.2.0"

    result = check_raw_counts.__wrapped__(str(path))  # pyright: ignore[reportFunctionMemberAccess]

    assert "obs has 4 IDs but raw/X has 6 rows" in result["error"]
    assert "traceback" not in result


def test_raw_x_without_raw_var_is_refused_before_the_walk(tmp_path):
    """Refused whether or not a gene happens to be all-zero: the refusal must
    not depend on the data."""
    path = _write(tmp_path / "no-raw-var.h5ad", BASE, "csr", raw=BASE)
    with h5py.File(path, "r+") as f:
        del f["raw/var"]

    result = check_raw_counts.__wrapped__(str(path))  # pyright: ignore[reportFunctionMemberAccess]

    assert "raw/var is not" in result["error"]
    assert "traceback" not in result


def test_chunk_bounds_do_not_wrap_on_int32_indptr():
    """scipy stores indptr as int32 while nnz fits; adding the budget in that
    dtype wraps negative near 2^31 and would force one-row chunks."""
    from hca_anndata_tools.qc import chunk_bounds

    indptr = np.array([0, 2_140_000_000, 2_140_000_005, 2_140_000_010], dtype=np.int32)
    bounds = list(chunk_bounds(indptr, 20_000_000))
    assert bounds == [(0, 1), (1, 3)]


def test_legacy_h5sparse_group_is_walked(tmp_path):
    """Pre-0.8 anndata stamped sparse groups with h5sparse_format instead of
    encoding-type. anndata still opens them, so the gate must too (principle 2)."""
    m = BASE.copy()
    m[1, 1] = -3.0
    path = _write(tmp_path / "legacy.h5ad", BASE, "csr", raw=m)
    with h5py.File(path, "r+") as f:
        g = f["raw/X"]
        del g.attrs["encoding-type"]
        del g.attrs["encoding-version"]
        g.attrs["h5sparse_format"] = "csr"
        g.attrs["h5sparse_shape"] = g.attrs["shape"]

    result = check_raw_counts(str(path))

    assert result["format"] == "csr"
    assert list(_codes(result)) == ["negative_values"]


def test_dense_float16_is_walked(tmp_path):
    """anndata writes and reads a float16 dense X; scipy.sparse refuses the
    dtype, so the block is upcast before it becomes a chunk."""
    m = BASE.astype(np.float16)
    m[4, :] = 0  # a defect the sampled classifier does not react to
    path = _write(tmp_path / "f16.h5ad", m, "dense")

    result = check_raw_counts(str(path))

    assert result["dtype"] == "float16"
    assert result["integer_check"]["status"] == "applied"
    assert list(_codes(result)) == ["zero_count_cells"]
