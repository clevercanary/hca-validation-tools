"""Small verdict tools for h5ad files (X normalization, schema type)."""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np

from ._errors import Refusal
from ._io import gate_h5ad_paths
from .cap import cellxgene_schema_version
from .write import resolve_latest

_DEFAULT_SAMPLE_SIZE = 2000

# Rows compared when deciding whether two matrices are the same. Spread across
# the whole matrix rather than taken from the head, so a file that diverges only
# in its tail is still caught.
_DUP_SAMPLE_ROWS = 400

# Rows a dense matrix is classified from. Sparse matrices sample `data`, which is
# nonzero by construction, but a dense sample has to pick rows — and picking only
# the first made an all-zero leading cell, which is ordinary in an unfiltered
# matrix, look like an empty matrix.
_DENSE_SAMPLE_ROWS = 20


def _sampled_positions(n: int, limit: int = _DUP_SAMPLE_ROWS) -> np.ndarray:
    """Up to ``limit`` indices spread evenly across ``range(n)``."""
    if n <= 0:
        return np.asarray([], dtype=int)
    return np.unique(np.linspace(0, n - 1, min(limit, n)).astype(int))


def _sample_matrix(f: h5py.File, key: str, sample_size: int) -> np.ndarray:
    """Return a 1-D numpy array sample of the matrix at ``key``.

    ``key`` is an h5ad matrix path — "X" or "raw/X". Sparse: first
    ``sample_size`` entries of ``<key>/data``. Dense: an even share of
    ``sample_size`` taken from each of up to ``_DENSE_SAMPLE_ROWS`` rows spread
    across the matrix, and spread across its columns too. Returns an empty array
    if the matrix is absent or either dimension is zero (degenerate 0-cell or
    0-gene file).

    Both axes are spread deliberately. A dense sample taken from one corner of
    the matrix is judging the whole of it by whatever happens to sit there, and
    all-zero leading rows *and* leading columns are both ordinary in an
    unfiltered matrix — either one read as an empty matrix.
    """
    if key not in f:
        return np.asarray([])

    x = f[key]
    if isinstance(x, h5py.Group) and "data" in x:
        data = x["data"]
        n = min(sample_size, len(data))  # pyright: ignore[reportArgumentType]
        return np.asarray(data[:n])  # pyright: ignore[reportIndexIssue]

    n_rows, n_cols = x.shape[0], x.shape[1]  # pyright: ignore[reportAttributeAccessIssue]
    if n_rows == 0 or n_cols == 0:
        return np.asarray([])

    # Row count is capped by the budget as well as by _DENSE_SAMPLE_ROWS: asking
    # for fewer values than there are rows would otherwise build the sample and
    # then truncate it, which throws away the later rows and leaves a sample
    # drawn from the top of the matrix — the bias this spreads rows to avoid.
    rows = _sampled_positions(n_rows, max(1, min(_DENSE_SAMPLE_ROWS, sample_size)))
    # Ceiling division, so the budget is met rather than floored away: 50 across
    # 20 rows is 3 each, not 2. _sampled_positions returns sorted unique indices,
    # which is what h5py requires of a fancy-index selection.
    cols = _sampled_positions(n_cols, -(-sample_size // len(rows)))
    # Not truncated to sample_size: every sampled row contributes equally, and a
    # sample slightly over budget costs nothing. The dict reports the size drawn.
    return np.concatenate([np.asarray(x[i, cols]) for i in rows])  # pyright: ignore[reportIndexIssue]


def _sparse_parts(group: h5py.Group) -> tuple[h5py.Dataset, h5py.Dataset, np.ndarray] | None:
    """``(data, indices, indptr)`` for a sparse matrix group, or None if malformed.

    ``data`` and ``indices`` stay unread dataset handles — only ``indptr`` is
    materialized, which is one int per row rather than one per nonzero.
    """
    data, indices, indptr = (group.get(name) for name in ("data", "indices", "indptr"))
    if not (isinstance(data, h5py.Dataset) and isinstance(indices, h5py.Dataset) and isinstance(indptr, h5py.Dataset)):
        return None
    return data, indices, np.asarray(indptr[:])


def _matrices_equal(path: str, a_key: str, b_key: str) -> bool:
    """Are the two matrices at these keys the same matrix?

    Sampled, not exhaustive, and the two layouts differ in what they compare in
    full. Sparse: ``shape`` and ``indptr``, then ``data`` and ``indices`` over
    ``_DUP_SAMPLE_ROWS`` rows spread across the matrix. Dense: ``shape`` alone,
    then those same sampled rows in their entirety.

    Whatever is compared in full pins the dimensions — and for sparse, each row's
    nonzero count — which is what makes the sampled rows meaningful. It does not
    pin content: two sparse matrices can share shape and ``indptr`` and still
    hold different ``indices`` or ``data`` within a row, and only the sampled
    rows would catch that. So this answers "the same, as far as several hundred
    rows can show" rather than "provably identical".

    Exhaustive comparison is deliberately not offered. A source dataset can carry
    well over a billion nonzeros, where full equality means reading tens of GB;
    callers that need that guarantee should say so at their own layer.

    Returns False for any layout this cannot speak to — mismatched encodings,
    dense against sparse, a malformed sparse group — so callers refuse rather
    than act on a comparison that never happened.
    """
    with h5py.File(path, "r") as f:
        if a_key not in f or b_key not in f:
            return False
        a, b = f[a_key], f[b_key]

        if a.attrs.get("encoding-type") != b.attrs.get("encoding-type"):
            return False

        if isinstance(a, h5py.Group) and isinstance(b, h5py.Group):
            # indptr pins the row count but says nothing about the column count,
            # so two matrices differing only in trailing all-zero columns carry
            # byte-identical indptr, indices and data. Shape is what separates
            # them, and h5ad records it on the group.
            a_shape, b_shape = a.attrs.get("shape"), b.attrs.get("shape")
            if a_shape is None or b_shape is None or not np.array_equal(a_shape, b_shape):
                return False

            a_parts, b_parts = _sparse_parts(a), _sparse_parts(b)
            if a_parts is None or b_parts is None:
                return False
            a_data, a_indices, indptr = a_parts
            b_data, b_indices, b_indptr = b_parts
            if not np.array_equal(indptr, b_indptr):
                return False

            for i in _sampled_positions(len(indptr) - 1):
                start, stop = int(indptr[i]), int(indptr[i + 1])
                if stop <= start:
                    continue
                if not np.array_equal(a_data[start:stop], b_data[start:stop]):
                    return False
                if not np.array_equal(a_indices[start:stop], b_indices[start:stop]):
                    return False
            return True

        if isinstance(a, h5py.Dataset) and isinstance(b, h5py.Dataset):
            if a.shape != b.shape:
                return False
            # One fancy-indexed read per matrix rather than one per row: h5py
            # accepts a sorted unique index array, which is what
            # _sampled_positions returns, and 400 round trips through h5py cost
            # far more than the single read does.
            rows = _sampled_positions(a.shape[0])
            if rows.size == 0:
                return True
            return np.array_equal(a[rows, :], b[rows, :])

        return False


def _verdict_from_sample(sample: np.ndarray) -> dict:
    """Classify a matrix sample as raw counts, normalized, or indeterminate.

    The shared core of every matrix verdict in this package: X's, and —
    since #532 — raw.X's, which has to answer the same question before the
    counts in it can be trusted.
    """
    nonzero = sample[sample != 0]
    nonzero_count = int(nonzero.size)
    has_negative = bool((sample < 0).any()) if sample.size else False
    is_integer_valued = bool(np.all(np.mod(nonzero, 1) == 0)) if nonzero_count else False

    if nonzero_count == 0:
        verdict = "indeterminate"
    elif has_negative or not is_integer_valued:
        verdict = "normalized"
    else:
        verdict = "raw_counts"

    nonzero_min: float | None = None
    nonzero_max: float | None = None
    if nonzero_count > 0:
        # Filter NaN/inf before min/max — those values aren't strict
        # JSON-serializable and some MCP clients reject them.
        finite = nonzero[np.isfinite(nonzero)]
        if finite.size:
            nonzero_min = float(finite.min())
            nonzero_max = float(finite.max())

    return {
        "sample_size": int(sample.size),
        "nonzero_count": nonzero_count,
        "nonzero_min": nonzero_min,
        "nonzero_max": nonzero_max,
        "is_integer_valued": is_integer_valued,
        "has_negative": has_negative,
        "verdict": verdict,
    }


def resolve_count_matrix(f: h5py.File) -> tuple[str, dict]:
    """Which matrix holds the counts, and whether it can be trusted as counts.

    ``raw/X`` when present, asserted to be counts rather than sampled: the
    schema gives it no other meaning, so a normalized ``raw/X`` is a defect
    for the caller to report, not a state to accommodate. Otherwise ``X`` —
    and then the sampled verdict
    decides: a lone ``X`` the sample calls normalized is not counts, and any
    criterion that only makes sense on counts (integer-valued, per-cell
    totals) has no meaning on it. Returned as ``status`` ``applied`` /
    ``not_applicable`` with the verdict as its ``reason``, verbatim, so the
    tools that share this decision (#686, #677, #687, #688) never spell it
    differently and never hedge.
    """
    if "raw/X" in f:
        return "raw/X", {"status": "applied", "reason": "raw/X is gated as the raw count matrix"}
    if "X" not in f:
        raise Refusal("neither raw/X nor X is present; there is no count matrix to gate")
    verdict = _verdict_from_sample(_sample_matrix(f, "X", _DEFAULT_SAMPLE_SIZE))["verdict"]
    if verdict == "normalized":
        return "X", {
            "status": "not_applicable",
            "reason": "no raw.X, and check_x_normalization classifies X as normalized",
        }
    return "X", {"status": "applied", "reason": f"no raw.X; check_x_normalization classifies X as {verdict}"}


def _classify_matrix_at_path(path: str, key: str, sample_size: int) -> dict:
    """Sample the matrix at ``key`` and return its verdict dict.

    Package-internal. Used for "raw/X" by ``normalize_raw``, which must
    establish that raw.X holds counts before it will treat it as the
    authoritative copy.
    """
    with h5py.File(path, "r") as f:
        return _verdict_from_sample(_sample_matrix(f, key, sample_size))


def _classify_x_at_path(path: str, sample_size: int) -> dict:
    """Sample X at an already-resolved path and return the verdict dict.

    Package-internal: skips ``resolve_latest`` and input validation so
    callers that have already resolved the latest path (e.g.
    ``normalize_raw``) don't pay a second directory glob. External
    callers should use :func:`check_x_normalization`.
    """
    with h5py.File(path, "r") as f:
        has_raw = "raw/X" in f
        # Read dtype from HDF5 directly — an empty sample array defaults
        # to float64 regardless of the on-disk type.
        x = f["X"]
        stored_dtype = (
            x["data"].dtype  # pyright: ignore[reportAttributeAccessIssue,reportIndexIssue]
            if isinstance(x, h5py.Group) and "data" in x
            else x.dtype  # pyright: ignore[reportAttributeAccessIssue]
        )
        dtype = str(stored_dtype)
        sample = _sample_matrix(f, "X", sample_size)

    return {
        "filename": Path(path).name,
        "dtype": dtype,
        **_verdict_from_sample(sample),
        "has_raw_x": has_raw,
    }


@gate_h5ad_paths
def check_x_normalization(path: str, sample_size: int = _DEFAULT_SAMPLE_SIZE) -> dict:
    """Sample X and report whether it looks like raw counts or normalized data.

    Reads a small slice via h5py without loading the full matrix. The
    heuristic is fail-fast, not a full-matrix guarantee: a file whose
    first entries are integers but whose later entries are fractional
    will be classified as ``raw_counts``.

    Args:
        path: Path to an .h5ad file.
        sample_size: Requested maximum number of X entries to inspect
            (default 2000). Must be >= 1. The returned ``sample_size``
            is the actual number sampled, which may be less when fewer
            entries are available (e.g. sparse X with small nnz).

    Returns:
        Dict with a fixed shape: ``filename``, ``dtype``, ``sample_size``,
        ``nonzero_count``, ``nonzero_min``, ``nonzero_max``,
        ``is_integer_valued``, ``has_negative``, ``has_raw_x``, ``verdict``.
        ``nonzero_min`` and ``nonzero_max`` are ``None`` when no nonzero
        values were seen, or when every nonzero value is non-finite. On
        failure, ``error`` is returned instead.

        ``verdict`` is one of:
        - ``"raw_counts"`` — all sampled nonzero values are non-negative integers.
        - ``"normalized"`` — sample contains non-integer or negative values.
        - ``"indeterminate"`` — sample contained no nonzero values.
    """
    try:
        if not isinstance(sample_size, int) or sample_size < 1:
            return {"error": f"sample_size must be a positive int, got {sample_size!r}"}
        return _classify_x_at_path(resolve_latest(path), sample_size)
    except Exception as e:
        return {"error": str(e)}


@gate_h5ad_paths
def check_schema_type(path: str) -> dict:
    """Report whether an h5ad file declares the CellxGENE or HCA schema.

    Detection is conservative: the presence of a non-empty
    ``uns['schema_version']`` is the CellxGENE signal. HCA-authored files
    (or anything else) fall through to ``"hca"``.

    Reads via h5py without loading the matrix.

    Args:
        path: Path to an .h5ad file.

    Returns:
        Dict with ``filename``, ``schema`` (``"cellxgene"`` or ``"hca"``),
        and ``schema_version`` (string when CellxGENE, ``None`` otherwise).
        On failure, ``error`` is returned instead.
    """
    try:
        path = resolve_latest(path)
        with h5py.File(path, "r") as f:
            version = cellxgene_schema_version(f)
        if version:
            return {
                "filename": Path(path).name,
                "schema": "cellxgene",
                "schema_version": version,
            }
        return {
            "filename": Path(path).name,
            "schema": "hca",
            "schema_version": None,
        }
    except Exception as e:
        return {"error": str(e)}
