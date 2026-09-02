"""Tests for the duplicate-cell check (#677), a port of Lattice's evaluate_dup_counts.

Fixtures are dense numpy written through anndata, then converted to the
format under test — never through the code under test (contract, principle
17). The one that matters most is "same values at different columns": it is
the case Lattice's second pass exists for, so it is the test that proves the
port kept it.
"""

from __future__ import annotations

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp

from hca_anndata_tools.dup_counts import SAMPLE_GROUP_LIMIT, check_duplicate_cells
from hca_anndata_tools.qc import SAMPLE_ID_LIMIT
from hca_anndata_tools.testing import make_nullable_index

ROW_FORMATS = ["csr", "dense"]
_AS_FORMAT = {"csr": sp.csr_matrix, "csc": sp.csc_matrix, "dense": np.asarray}

# 8 cells x 5 genes, all rows distinct, every row non-empty.
BASE = np.array(
    [
        [3, 0, 1, 0, 2],
        [0, 4, 0, 1, 0],
        [1, 0, 0, 2, 0],
        [0, 1, 5, 0, 1],
        [2, 0, 0, 3, 0],
        [0, 2, 1, 0, 4],
        [1, 1, 0, 0, 0],
        [0, 0, 0, 7, 1],
    ],
    dtype=np.float32,
)


def _write(path, X: np.ndarray, fmt: str, *, raw: np.ndarray | None = None):
    n_obs, n_var = X.shape
    adata = ad.AnnData(
        X=_AS_FORMAT[fmt](X),
        obs=pd.DataFrame(index=[f"c{i}" for i in range(n_obs)]),  # pyright: ignore[reportArgumentType]
        var=pd.DataFrame(index=[f"g{j}" for j in range(n_var)]),  # pyright: ignore[reportArgumentType]
    )
    if raw is not None:
        adata.raw = ad.AnnData(
            X=_AS_FORMAT[fmt](raw),
            var=pd.DataFrame(index=[f"g{j}" for j in range(raw.shape[1])]),  # pyright: ignore[reportArgumentType]
        )
    adata.write_h5ad(path)
    return path


def _groups(result: dict) -> list[list[str]]:
    assert "error" not in result, result
    if not result["findings"]:
        return []
    (finding,) = result["findings"]
    assert finding["code"] == "duplicate_cells"
    return finding["sample_groups"]


@pytest.mark.parametrize("fmt", ROW_FORMATS)
def test_clean_matrix_has_no_groups(tmp_path, fmt):
    path = _write(tmp_path / "clean.h5ad", BASE, fmt, raw=BASE)

    result = check_duplicate_cells(str(path))

    assert result["matrix"] == "raw/X"
    assert result["format"] == fmt
    assert result["non_canonical_rows"] == 0
    assert result["findings"] == []


@pytest.mark.parametrize("fmt", ROW_FORMATS)
def test_one_duplicated_cell_is_one_group_of_two(tmp_path, fmt):
    m = BASE.copy()
    m[6] = m[2]
    path = _write(tmp_path / "pair.h5ad", m, fmt, raw=m)

    result = check_duplicate_cells(str(path))

    assert _groups(result) == [["c2", "c6"]]
    (finding,) = result["findings"]
    assert finding["count"] == 1
    assert finding["groups"] == 1
    assert finding["matrix"] == "raw/X"


def test_two_independent_pairs_are_two_groups(tmp_path):
    m = BASE.copy()
    m[6] = m[2]
    m[7] = m[0]
    path = _write(tmp_path / "pairs.h5ad", m, "csr", raw=m)

    result = check_duplicate_cells(str(path))

    assert _groups(result) == [["c0", "c7"], ["c2", "c6"]]
    assert result["findings"][0]["count"] == 2
    assert result["findings"][0]["groups"] == 2


def test_triplet_is_one_group_with_two_surplus(tmp_path):
    m = BASE.copy()
    m[6] = m[2]
    m[7] = m[2]
    path = _write(tmp_path / "triplet.h5ad", m, "csr", raw=m)

    result = check_duplicate_cells(str(path))

    assert _groups(result) == [["c2", "c6", "c7"]]
    assert result["findings"][0]["count"] == 2


def test_cells_differing_in_one_value_are_not_duplicates(tmp_path):
    m = BASE.copy()
    m[6] = m[2]
    m[6, 3] += 1
    path = _write(tmp_path / "near.h5ad", m, "csr", raw=m)

    assert _groups(check_duplicate_cells(str(path))) == []


@pytest.mark.parametrize("fmt", ROW_FORMATS)
def test_same_values_at_different_columns_are_not_duplicates(tmp_path, fmt):
    """The case the second pass exists for: identical data slices, different
    indices. Pass one collides; pass two must separate them."""
    m = BASE.copy()
    m[6] = [1, 0, 0, 2, 0]  # same values as c2 ...
    m[7] = [0, 1, 0, 0, 2]  # ... at different columns
    m[2] = [1, 0, 0, 2, 0]
    path = _write(tmp_path / "shifted.h5ad", m, fmt, raw=m)

    result = check_duplicate_cells(str(path))

    assert _groups(result) == [["c2", "c6"]]  # c7 shares the multiset, not the row


def test_unsorted_indices_canonicalize_to_a_duplicate(tmp_path):
    """A row stored with its indices out of order is still the same cell."""
    m = BASE.copy()
    m[6] = m[2]
    path = _write(tmp_path / "unsorted.h5ad", m, "csr", raw=m)
    with h5py.File(path, "r+") as f:
        g = f["raw/X"]
        indptr = g["indptr"][:]
        a, b = int(indptr[6]), int(indptr[7])
        assert b - a == 2
        g["indices"][a:b] = g["indices"][a:b][::-1]
        g["data"][a:b] = g["data"][a:b][::-1]

    result = check_duplicate_cells(str(path))

    assert result["non_canonical_rows"] == 1
    assert _groups(result) == [["c2", "c6"]]


def test_repeated_index_is_non_canonical_and_sums(tmp_path):
    """c6 stores gene 0 twice as 1 + 1; canonical it is c2's row shifted — not a
    duplicate of anything, but counted as non-canonical."""
    m = BASE.copy()
    path = _write(tmp_path / "repeat.h5ad", m, "csr", raw=m)
    with h5py.File(path, "r+") as f:
        g = f["raw/X"]
        indptr = g["indptr"][:]
        a, b = int(indptr[6]), int(indptr[7])  # c6 = [1, 1, 0, 0, 0] -> indices [0, 1]
        g["indices"][a:b] = [0, 0]  # now gene 0 twice, summing to 2

    result = check_duplicate_cells(str(path))

    assert result["non_canonical_rows"] == 1
    assert _groups(result) == []


def test_zero_count_cells_do_not_group(tmp_path):
    m = BASE.copy()
    m[6] = 0
    m[7] = 0
    path = _write(tmp_path / "empty-rows.h5ad", m, "csr", raw=m)

    result = check_duplicate_cells(str(path))

    assert _groups(result) == []


def test_lone_x_is_hashed_as_is(tmp_path):
    rng = np.random.default_rng(2)
    X = rng.random((8, 5)).astype(np.float32) + 0.1
    X[6] = X[2]
    path = _write(tmp_path / "lonex.h5ad", X, "csr")

    result = check_duplicate_cells(str(path))

    assert result["matrix"] == "X"
    assert "integer_check" not in result
    assert _groups(result) == [["c2", "c6"]]


def test_csc_is_refused_by_name(tmp_path):
    path = _write(tmp_path / "csc.h5ad", BASE, "csc", raw=BASE)

    result = check_duplicate_cells(str(path))

    assert "csc_matrix" in result["error"]
    assert "traceback" not in result


def test_nullable_string_index_runs_to_completion(tmp_path):
    m = BASE.copy()
    m[6] = m[2]
    path = _write(tmp_path / "nullable.h5ad", m, "csr", raw=m)
    make_nullable_index(path, "obs")

    assert _groups(check_duplicate_cells(str(path))) == [["c2", "c6"]]


def test_empty_matrix_has_no_findings(tmp_path):
    path = _write(tmp_path / "empty.h5ad", np.zeros((0, 5), dtype=np.float32), "csr")
    result = check_duplicate_cells(str(path))
    assert result["findings"] == []
    assert result["non_canonical_rows"] == 0


def test_bad_chunk_nnz_and_missing_file(tmp_path):
    path = _write(tmp_path / "c.h5ad", BASE, "csr")
    assert "chunk_nnz" in check_duplicate_cells(str(path), chunk_nnz=0)["error"]
    assert check_duplicate_cells(str(tmp_path / "nope.h5ad"))["error"].startswith("File not found")


def test_group_and_id_caps(tmp_path):
    n_groups = SAMPLE_GROUP_LIMIT + 3
    big = SAMPLE_ID_LIMIT + 4
    rows = []
    for g in range(n_groups):
        row = np.zeros(6, dtype=np.float32)
        row[g % 6] = g + 1
        row[(g + 1) % 6] = 1
        rows.extend([row] * (big if g == 0 else 2))
    m = np.stack(rows)
    path = _write(tmp_path / "caps.h5ad", m, "csr", raw=m)

    (finding,) = check_duplicate_cells(str(path))["findings"]

    assert finding["groups"] == n_groups
    assert finding["count"] == (big - 1) + (n_groups - 1)  # surplus: one big group plus a pair per other group
    assert len(finding["sample_groups"]) == SAMPLE_GROUP_LIMIT
    assert len(finding["sample_groups"][0]) == SAMPLE_ID_LIMIT


@pytest.mark.parametrize("fmt", ROW_FORMATS)
def test_chunked_walk_agrees_with_one_pass(tmp_path, fmt):
    rng = np.random.default_rng(7)
    m = rng.integers(0, 4, size=(120, 40)).astype(np.float32)
    m[50] = m[10]
    m[99] = m[10]
    m[77] = m[3]
    m[20] = 0
    path = _write(tmp_path / "big.h5ad", m, fmt, raw=m)

    chunked = check_duplicate_cells(str(path), chunk_nnz=300)
    whole = check_duplicate_cells(str(path))

    assert chunked == whole
    assert _groups(chunked) == [["c3", "c77"], ["c10", "c50", "c99"]]
    assert chunked["findings"][0]["count"] == 3
