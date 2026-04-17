"""Check whether X contains raw counts or already-normalized data."""

from __future__ import annotations

import os

import h5py
import numpy as np

from .write import resolve_latest

_DEFAULT_SAMPLE_SIZE = 2000


def _sample_x(f: h5py.File, sample_size: int) -> np.ndarray:
    """Return a 1-D numpy array sample of X from an open h5py File.

    Sparse: first ``sample_size`` entries of X/data. Dense: first
    ``sample_size`` entries of row 0.
    """
    x = f["X"]
    if isinstance(x, h5py.Group) and "data" in x:
        data = x["data"]
        n = min(sample_size, len(data))  # pyright: ignore[reportArgumentType]
        return np.asarray(data[:n])  # pyright: ignore[reportIndexIssue]
    return np.asarray(x[0, :sample_size])  # pyright: ignore[reportIndexIssue]


def check_x_normalization(path: str, sample_size: int = _DEFAULT_SAMPLE_SIZE) -> dict:
    """Sample X and report whether it looks like raw counts or normalized data.

    Reads a small slice via h5py without loading the full matrix. The
    heuristic is fail-fast, not a full-matrix guarantee: a file whose
    first entries are integers but whose later entries are fractional
    will be classified as ``raw_counts``.

    Args:
        path: Path to an .h5ad file.
        sample_size: Number of X entries to inspect (default 2000).

    Returns:
        Dict with ``dtype``, ``sample_size``, ``nonzero_count``,
        ``is_integer_valued``, ``has_negative``, ``has_raw_x``,
        ``verdict``, and (when nonzero values were seen) ``nonzero_min``
        and ``nonzero_max``. The min/max are ``None`` if every nonzero
        value is non-finite. On failure, ``error`` is returned instead.

        ``verdict`` is one of:
        - ``"raw_counts"`` — all sampled nonzero values are non-negative integers.
        - ``"normalized"`` — sample contains non-integer or negative values.
        - ``"indeterminate"`` — sample contained no nonzero values.
    """
    try:
        path = resolve_latest(path)
        with h5py.File(path, "r") as f:
            has_raw = "raw/X" in f
            sample = _sample_x(f, sample_size)
            dtype = str(sample.dtype)

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

        result = {
            "filename": os.path.basename(path),
            "dtype": dtype,
            "sample_size": int(sample.size),
            "nonzero_count": nonzero_count,
            "is_integer_valued": is_integer_valued,
            "has_negative": has_negative,
            "has_raw_x": has_raw,
            "verdict": verdict,
        }
        if nonzero_count > 0:
            # Filter out NaN/inf before min/max — those values aren't
            # strict-JSON-serializable and some MCP clients reject them.
            finite = nonzero[np.isfinite(nonzero)]
            result["nonzero_min"] = float(finite.min()) if finite.size else None
            result["nonzero_max"] = float(finite.max()) if finite.size else None
        return result

    except Exception as e:
        return {"error": str(e)}
