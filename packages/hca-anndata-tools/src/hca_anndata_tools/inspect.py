"""Small verdict tools for h5ad files (X normalization, schema type)."""

from __future__ import annotations

import os

import h5py
import numpy as np

from ._io import _decode_bytes
from .write import resolve_latest

_DEFAULT_SAMPLE_SIZE = 2000


def _sample_x(f: h5py.File, sample_size: int) -> np.ndarray:
    """Return a 1-D numpy array sample of X from an open h5py File.

    Sparse: first ``sample_size`` entries of X/data. Dense: first
    ``sample_size`` entries of row 0. Returns an empty array if either
    X dimension is zero (degenerate 0-cell or 0-gene file).
    """
    x = f["X"]
    if isinstance(x, h5py.Group) and "data" in x:
        data = x["data"]
        n = min(sample_size, len(data))  # pyright: ignore[reportArgumentType]
        return np.asarray(data[:n])  # pyright: ignore[reportIndexIssue]
    if x.shape[0] == 0 or x.shape[1] == 0:  # pyright: ignore[reportAttributeAccessIssue]
        return np.asarray([])
    return np.asarray(x[0, :sample_size])  # pyright: ignore[reportIndexIssue]


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
        sample = _sample_x(f, sample_size)

    nonzero = sample[sample != 0]
    nonzero_count = int(nonzero.size)
    has_negative = bool((sample < 0).any()) if sample.size else False
    is_integer_valued = (
        bool(np.all(np.mod(nonzero, 1) == 0)) if nonzero_count else False
    )

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
        "filename": os.path.basename(path),
        "dtype": dtype,
        "sample_size": int(sample.size),
        "nonzero_count": nonzero_count,
        "nonzero_min": nonzero_min,
        "nonzero_max": nonzero_max,
        "is_integer_valued": is_integer_valued,
        "has_negative": has_negative,
        "has_raw_x": has_raw,
        "verdict": verdict,
    }


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


def _read_schema_version(f: h5py.File) -> str | None:
    """Read and decode ``uns['schema_version']`` from an open h5py File.

    Returns the stripped string, or None if absent or empty.
    ``schema_version`` is stored as a scalar string dataset in AnnData's
    h5ad format.
    """
    uns = f.get("uns")
    if not isinstance(uns, h5py.Group) or "schema_version" not in uns:
        return None
    raw = uns["schema_version"][()]  # pyright: ignore[reportIndexIssue]
    value = _decode_bytes(raw)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


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
            version = _read_schema_version(f)
        if version:
            return {
                "filename": os.path.basename(path),
                "schema": "cellxgene",
                "schema_version": version,
            }
        return {
            "filename": os.path.basename(path),
            "schema": "hca",
            "schema_version": None,
        }
    except Exception as e:
        return {"error": str(e)}
