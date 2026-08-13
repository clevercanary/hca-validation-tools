"""Tests for normalize_raw."""

import json

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp

from hca_anndata_tools.normalize import normalize_raw


def _counts(rng, n_obs=40, n_vars=15, density=0.3):
    """A sparse integer count matrix with at least one nonzero per row."""
    dense = rng.integers(1, 10, size=(n_obs, n_vars)).astype(np.float32)
    masked = dense * (rng.random((n_obs, n_vars)) < density)
    # Guarantee at least one nonzero per row so normalize_total doesn't warn.
    rows = np.arange(n_obs)
    picks = rng.integers(0, n_vars, size=n_obs)
    masked[rows, picks] = dense[rows, picks]
    return sp.csr_matrix(masked)


def _frame(n_obs, n_vars):
    obs = pd.DataFrame(index=[f"c{i}" for i in range(n_obs)])  # pyright: ignore[reportArgumentType]
    var = pd.DataFrame(index=[f"g{i}" for i in range(n_vars)])  # pyright: ignore[reportArgumentType]
    return obs, var


def _write(path, x, raw_x=None, obs=None):
    """Write an h5ad with X, and optionally a raw whose X is ``raw_x``."""
    n_obs, n_vars = x.shape
    default_obs, var = _frame(n_obs, n_vars)
    obs = default_obs if obs is None else obs
    adata = ad.AnnData(X=x, obs=obs, var=var)
    if raw_x is not None:
        adata.raw = ad.AnnData(X=raw_x, obs=obs, var=var)
    adata.write_h5ad(path)
    return path


def _write_raw_counts(path, *, density=0.3, n_obs=40, n_vars=15) -> None:
    """Write an h5ad with raw integer counts in X and no raw.X."""
    rng = np.random.default_rng(7)
    x = _counts(rng, n_obs, n_vars, density)
    obs = pd.DataFrame(
        {"cell_type": pd.Categorical(rng.choice(["A", "B"], n_obs))},
        index=[f"c{i}" for i in range(n_obs)],  # pyright: ignore[reportArgumentType]
    )
    _write(path, x, obs=obs)


@pytest.fixture
def raw_counts_h5ad(tmp_path):
    path = tmp_path / "raw_counts.h5ad"
    _write_raw_counts(path)
    return path


def test_normalize_raw_moves_counts_and_normalizes(raw_counts_h5ad):
    original = ad.read_h5ad(raw_counts_h5ad)

    result = normalize_raw(str(raw_counts_h5ad))
    assert "error" not in result
    assert result["target_sum"] == 1e4
    assert result["n_obs"] == original.n_obs
    assert result["n_vars"] == original.n_vars

    out = ad.read_h5ad(result["output_path"])
    assert out.raw is not None
    np.testing.assert_array_equal(out.raw.X.toarray(), original.X.toarray())  # pyright: ignore[reportAttributeAccessIssue]

    # X should now be normalized + log1p: non-negative floats, mostly non-integer
    x_dense = out.X.toarray()  # pyright: ignore[reportAttributeAccessIssue]
    assert (x_dense >= 0).all()
    assert not np.all(np.mod(x_dense[x_dense > 0], 1) == 0)


@pytest.fixture
def duplicate_raw_h5ad(tmp_path):
    """The breast-v1 shape: raw.X present and byte-identical to X, both counts."""
    x = _counts(np.random.default_rng(21))
    return _write(tmp_path / "duplicate.h5ad", x, raw_x=x.copy())


def test_normalize_raw_proceeds_when_raw_x_duplicates_x(duplicate_raw_h5ad):
    """The state this exists for: normalization never ran, so both matrices hold counts.

    All seven breast-v1 source datasets are in it. raw.X is already correct, so
    the operation is a normalization of X alone.
    """
    original = ad.read_h5ad(duplicate_raw_h5ad)

    result = normalize_raw(str(duplicate_raw_h5ad))
    assert "error" not in result
    assert "verified duplicate" in result["raw_x"]

    out = ad.read_h5ad(result["output_path"])

    # raw.X untouched — still the counts it always held.
    np.testing.assert_array_equal(out.raw.X.toarray(), original.X.toarray())  # pyright: ignore[reportOptionalMemberAccess,reportAttributeAccessIssue]

    # X is now normalized: non-negative, and no longer whole numbers.
    x_dense = out.X.toarray()  # pyright: ignore[reportAttributeAccessIssue]
    assert (x_dense >= 0).all()
    assert not np.all(np.mod(x_dense[x_dense > 0], 1) == 0)


def test_normalize_raw_refuses_when_raw_x_differs_from_x(tmp_path):
    """A raw.X that is not X is a different matrix, and overwriting it loses data."""
    rng = np.random.default_rng(22)
    path = _write(tmp_path / "differs.h5ad", _counts(rng), raw_x=_counts(rng))

    result = normalize_raw(str(path))
    assert "error" in result
    assert "differs" in result["error"].lower()


def test_normalize_raw_refuses_when_raw_x_is_not_counts(tmp_path):
    """raw.X must hold counts before it can be trusted as the authoritative copy."""
    rng = np.random.default_rng(23)
    fractional = sp.csr_matrix(rng.random((40, 15)).astype(np.float32) + 0.5)
    path = _write(tmp_path / "raw_not_counts.h5ad", _counts(rng), raw_x=fractional)

    result = normalize_raw(str(path))
    assert "error" in result
    assert "raw.x does not hold raw counts" in result["error"].lower()


def test_normalize_raw_is_a_noop_when_already_in_target_layout(raw_counts_h5ad):
    """Counts in raw.X and a normalized X is the goal, not a failure.

    Running the tool twice used to error on the second pass, back when any raw.X
    was refused outright. It now reports that there is nothing to do and writes
    no file — the distinction matters, because an error here would read as a
    defect in a file that is correct.
    """
    result = normalize_raw(str(raw_counts_h5ad))
    assert "error" not in result

    result2 = normalize_raw(result["output_path"])
    assert "error" not in result2
    assert result2["already_normalized"] is True
    assert "output_path" not in result2


def test_normalize_raw_refuses_an_empty_x_with_no_raw(tmp_path):
    """No counts anywhere. Normalizing an empty matrix would produce an empty one."""
    path = _write(tmp_path / "empty.h5ad", sp.csr_matrix((20, 10), dtype=np.float32))

    result = normalize_raw(str(path))
    assert "error" in result
    assert "no data" in result["error"].lower()


def test_normalize_raw_duplicate_dense_x(tmp_path):
    """Dense matrices reach the same verdict by a different comparison path."""
    rng = np.random.default_rng(24)
    x = rng.integers(1, 10, size=(20, 8)).astype(np.float32)
    path = _write(tmp_path / "dense_duplicate.h5ad", x, raw_x=x.copy())

    result = normalize_raw(str(path))
    assert "error" not in result

    out = ad.read_h5ad(result["output_path"])
    np.testing.assert_array_equal(np.asarray(out.raw.X), x)  # pyright: ignore[reportOptionalMemberAccess]


# The all-zero cell this test is built around is exactly what scanpy warns on,
# so the warning is the fixture working, not a defect to chase.
@pytest.mark.filterwarnings("ignore:Some cells have zero counts")
def test_normalize_raw_dense_x_with_an_empty_first_cell(tmp_path):
    """A dense matrix must be judged on more than its first row.

    Sampling row 0 alone made an all-zero leading cell — ordinary in an
    unfiltered matrix — read as an empty matrix, which refused the file on the
    plain path and, on the duplicate path, reported the counts in raw.X as "not
    raw counts".
    """
    rng = np.random.default_rng(25)
    x = rng.integers(1, 10, size=(20, 8)).astype(np.float32)
    x[0, :] = 0

    plain = _write(tmp_path / "dense_zero_first_row.h5ad", x)
    assert "error" not in normalize_raw(str(plain))

    duplicate = _write(tmp_path / "dense_zero_first_row_dup.h5ad", x, raw_x=x.copy())
    assert "error" not in normalize_raw(str(duplicate))


@pytest.mark.filterwarnings("ignore:Some cells have zero counts")
def test_normalize_raw_dense_x_with_empty_leading_columns(tmp_path):
    """The column mirror of the row case above.

    Sampling the first few columns of each row is the same blind spot rotated
    ninety degrees: a matrix whose leading genes are all zero, which unfiltered
    data routinely is, would read as empty.
    """
    rng = np.random.default_rng(27)
    x = rng.integers(1, 10, size=(20, 40)).astype(np.float32)
    x[:, :30] = 0

    plain = _write(tmp_path / "dense_zero_lead_cols.h5ad", x)
    assert "error" not in normalize_raw(str(plain))

    duplicate = _write(tmp_path / "dense_zero_lead_cols_dup.h5ad", x, raw_x=x.copy())
    assert "error" not in normalize_raw(str(duplicate))


def test_normalize_raw_refuses_when_shapes_differ(tmp_path):
    """Matrices of different width can still share indptr, indices and data.

    Trailing all-zero columns contribute nothing to a CSR body, so shape is the
    only thing that separates them — and calling them a verified duplicate would
    put that claim in the provenance record.
    """
    rng = np.random.default_rng(26)
    n_obs = 30
    x = _counts(rng, n_obs=n_obs, n_vars=10)
    wider = sp.csr_matrix((x.data, x.indices, x.indptr), shape=(n_obs, 13))

    # Built directly rather than through _write: raw legitimately carries more
    # genes than X (that is what gene filtering produces), so the two need
    # different var frames.
    obs = pd.DataFrame(index=[f"c{i}" for i in range(n_obs)])  # pyright: ignore[reportArgumentType]
    adata = ad.AnnData(X=x, obs=obs, var=pd.DataFrame(index=[f"g{i}" for i in range(10)]))  # pyright: ignore[reportArgumentType]
    adata.raw = ad.AnnData(X=wider, obs=obs, var=pd.DataFrame(index=[f"g{i}" for i in range(13)]))  # pyright: ignore[reportArgumentType]
    path = tmp_path / "shape_mismatch.h5ad"
    adata.write_h5ad(path)

    result = normalize_raw(str(path))
    assert "error" in result
    assert "differs" in result["error"].lower()


def test_normalize_raw_edit_log_records_the_duplicate_verification(duplicate_raw_h5ad):
    """Provenance has to show why the usual refusal did not apply."""
    result = normalize_raw(str(duplicate_raw_h5ad))
    assert "error" not in result

    with h5py.File(result["output_path"], "r") as f:
        log_raw = f["uns/provenance/edit_history"][()]
    entry = json.loads(log_raw.decode("utf-8") if isinstance(log_raw, bytes) else log_raw)[0]

    assert "verified duplicate" in entry["details"]["raw_x"]
    assert "Normalized X" in entry["description"]
    assert "Moved raw counts" not in entry["description"]


def test_normalize_raw_fails_when_x_has_non_integer(tmp_path):
    rng = np.random.default_rng(3)
    X = rng.random((20, 10)).astype(np.float32)  # floats in [0, 1)
    adata = ad.AnnData(
        X=sp.csr_matrix(X),
        obs=pd.DataFrame(index=[f"c{i}" for i in range(20)]),  # pyright: ignore[reportArgumentType]
        var=pd.DataFrame(index=[f"g{i}" for i in range(10)]),  # pyright: ignore[reportArgumentType]
    )
    path = tmp_path / "normalized.h5ad"
    adata.write_h5ad(path)

    result = normalize_raw(str(path))
    assert "error" in result
    assert "non-integer" in result["error"].lower()


def test_normalize_raw_fails_on_negative_values(tmp_path):
    X = np.array([[1.0, -2.0], [3.0, 4.0]], dtype=np.float32)
    adata = ad.AnnData(
        X=sp.csr_matrix(X),
        obs=pd.DataFrame(index=["c0", "c1"]),  # pyright: ignore[reportArgumentType]
        var=pd.DataFrame(index=["g0", "g1"]),  # pyright: ignore[reportArgumentType]
    )
    path = tmp_path / "negatives.h5ad"
    adata.write_h5ad(path)

    result = normalize_raw(str(path))
    assert "error" in result
    assert "negative" in result["error"].lower()


def test_normalize_raw_edit_log_written(raw_counts_h5ad):
    result = normalize_raw(str(raw_counts_h5ad))
    assert "error" not in result

    with h5py.File(result["output_path"], "r") as f:
        log_raw = f["uns/provenance/edit_history"][()]
    log = json.loads(log_raw.decode("utf-8") if isinstance(log_raw, bytes) else log_raw)
    assert len(log) == 1
    entry = log[0]
    assert entry["operation"] == "normalize_raw"
    assert entry["details"]["target_sum"] == 1e4
    assert entry["details"]["n_obs"] == result["n_obs"]
    assert entry["details"]["n_vars"] == result["n_vars"]
    assert "source_sha256" in entry


def test_normalize_raw_missing_file(tmp_path):
    result = normalize_raw(str(tmp_path / "does-not-exist.h5ad"))
    assert "error" in result


def test_normalize_raw_strips_log1p_uns_stamp(raw_counts_h5ad):
    """scanpy's uns['log1p'] stamp roundtrips to an empty dict that CXG rejects (#327)."""
    result = normalize_raw(str(raw_counts_h5ad))
    assert "error" not in result

    out = ad.read_h5ad(result["output_path"])
    assert "log1p" not in out.uns


def test_normalize_raw_strips_feature_is_filtered_from_raw_var(tmp_path):
    """raw.var must not contain feature_is_filtered per CXG schema (#326)."""
    rng = np.random.default_rng(13)
    n_obs, n_vars = 30, 10
    X = rng.integers(0, 10, size=(n_obs, n_vars)).astype(np.float32)
    var = pd.DataFrame(
        {
            "feature_is_filtered": [False] * n_vars,
            "gene_symbol": [f"G{i}" for i in range(n_vars)],
        },
        index=[f"ENSG{i:011d}" for i in range(n_vars)],  # pyright: ignore[reportArgumentType]
    )
    adata = ad.AnnData(
        X=sp.csr_matrix(X),
        obs=pd.DataFrame(index=[f"c{i}" for i in range(n_obs)]),  # pyright: ignore[reportArgumentType]
        var=var,
    )
    path = tmp_path / "with_feature_is_filtered.h5ad"
    adata.write_h5ad(path)

    result = normalize_raw(str(path))
    assert "error" not in result

    out = ad.read_h5ad(result["output_path"])
    assert "feature_is_filtered" not in out.raw.var.columns  # pyright: ignore[reportOptionalMemberAccess]
    # Other var columns preserved in raw.var
    assert "gene_symbol" in out.raw.var.columns  # pyright: ignore[reportOptionalMemberAccess]
    # Normalized var still has feature_is_filtered
    assert "feature_is_filtered" in out.var.columns


def test_normalize_raw_dense_x(tmp_path):
    """Dense X with integer values should also work."""
    rng = np.random.default_rng(11)
    X = rng.integers(0, 10, size=(20, 8)).astype(np.float32)
    adata = ad.AnnData(
        X=X,
        obs=pd.DataFrame(index=[f"c{i}" for i in range(20)]),  # pyright: ignore[reportArgumentType]
        var=pd.DataFrame(index=[f"g{i}" for i in range(8)]),  # pyright: ignore[reportArgumentType]
    )
    path = tmp_path / "dense.h5ad"
    adata.write_h5ad(path)

    result = normalize_raw(str(path))
    assert "error" not in result

    out = ad.read_h5ad(result["output_path"])
    assert out.raw is not None
    np.testing.assert_array_equal(np.asarray(out.raw.X), X)
