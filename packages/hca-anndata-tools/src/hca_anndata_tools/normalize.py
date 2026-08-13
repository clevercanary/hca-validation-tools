"""Normalize raw counts in X to standard CXG layout (normalized in X, raw in raw.X)."""

from __future__ import annotations

import h5py
import numpy as np

from ._io import open_h5ad
from .inspect import _DEFAULT_SAMPLE_SIZE, _classify_matrix_at_path, _classify_x_at_path
from .write import make_edit_entry, resolve_latest, write_h5ad

_TARGET_SUM = 1e4

# Rows compared between X and raw.X when deciding whether raw.X is a duplicate.
# Spread across the whole matrix rather than taken from the head, so a file that
# diverges only in its tail is still caught.
_DUP_SAMPLE_ROWS = 400


def _sampled_positions(n: int) -> np.ndarray:
    """Up to ``_DUP_SAMPLE_ROWS`` indices spread evenly across ``range(n)``."""
    return np.unique(np.linspace(0, n - 1, min(_DUP_SAMPLE_ROWS, n)).astype(int))


def _sparse_parts(group: h5py.Group) -> tuple[h5py.Dataset, h5py.Dataset, np.ndarray] | None:
    """``(data, indices, indptr)`` for a sparse matrix group, or None if malformed.

    A group missing any of the three is not something this can compare, so the
    caller refuses rather than guessing.
    """
    data, indices, indptr = (group.get(name) for name in ("data", "indices", "indptr"))
    if not (isinstance(data, h5py.Dataset) and isinstance(indices, h5py.Dataset) and isinstance(indptr, h5py.Dataset)):
        return None
    return data, indices, np.asarray(indptr[:])


def _rows_match(
    a: tuple[h5py.Dataset, h5py.Dataset],
    b: tuple[h5py.Dataset, h5py.Dataset],
    indptr: np.ndarray,
) -> bool:
    """Compare ``(data, indices)`` over sampled slices of two sparse matrices.

    Callers establish that the two share an ``indptr`` first, which is what
    makes slicing by one safe for both.
    """
    a_data, a_indices = a
    b_data, b_indices = b

    n_slices = len(indptr) - 1
    if n_slices <= 0:
        return True

    for i in _sampled_positions(n_slices):
        start, stop = int(indptr[i]), int(indptr[i + 1])
        if stop <= start:
            continue
        if not np.array_equal(a_data[start:stop], b_data[start:stop]):
            return False
        if not np.array_equal(a_indices[start:stop], b_indices[start:stop]):
            return False
    return True


def _raw_x_matches_x(path: str) -> bool:
    """Is raw.X the same matrix as X?

    Sampled rather than exhaustive. ``reed2024`` carries 1.65 billion nonzeros,
    so full equality means reading ~13 GB to re-confirm a fact that costs nothing
    to be wrong about: ``write_h5ad`` emits a new ``<stem>-edit-<ts>.h5ad`` and
    never modifies the original, so a false positive here cannot destroy data. The
    ``X``-is-raw-counts test in ``normalize_raw`` is already an explicit sampling
    heuristic, so this is the established shape for this decision.

    What is *not* sampled is ``indptr``: it is compared in full, and it is the
    load-bearing part. Two matrices with identical row boundaries and identical
    values across 400 rows spread over the whole file are the same matrix in every
    way that matters here; two matrices that differ anywhere in structure differ in
    ``indptr``.

    Returns False for any layout the comparison cannot speak to — mismatched
    encodings, dense against sparse — which routes the caller to its refusal.
    """
    with h5py.File(path, "r") as f:
        if "raw/X" not in f:
            return False
        x, raw_x = f["X"], f["raw/X"]

        if x.attrs.get("encoding-type") != raw_x.attrs.get("encoding-type"):
            return False

        if isinstance(x, h5py.Group) and isinstance(raw_x, h5py.Group):
            x_parts, raw_parts = _sparse_parts(x), _sparse_parts(raw_x)
            if x_parts is None or raw_parts is None:
                return False
            x_data, x_indices, x_indptr = x_parts
            raw_data, raw_indices, raw_indptr = raw_parts
            if not np.array_equal(x_indptr, raw_indptr):
                return False
            return _rows_match((x_data, x_indices), (raw_data, raw_indices), x_indptr)

        if isinstance(x, h5py.Dataset) and isinstance(raw_x, h5py.Dataset):
            if x.shape != raw_x.shape:
                return False
            n_rows = x.shape[0]
            if n_rows == 0:
                return True
            return all(np.array_equal(x[i, :], raw_x[i, :]) for i in _sampled_positions(n_rows))

        return False


def normalize_raw(path: str) -> dict:
    """Normalize raw counts in X, moving originals to raw.X.

    Produces the standard CXG layout: raw integer counts in raw.X, and
    library-size-normalized, log1p-transformed values in X. Uses the
    scanpy recipe `normalize_total(target_sum=1e4)` + `log1p`.

    Classifying each of X and raw.X as empty, counts, or normalized gives
    nine states. Three are actionable and this handles two of them (#532);
    the third — counts in raw.X with an empty X — is #572::

        raw.X \\ X   empty            counts               normalized
        empty        error            promote+normalize    error
        counts       error (#572)     duplicate? normalize error is wrong:
                                      X only, else error   already correct
        normalized   error            error                error

    **promote + normalize** is the original case: counts sit in X, raw.X is
    absent, so X is copied to raw.X before being overwritten.

    **normalize X only** is the case this exists for. When raw.X is present
    *and the same matrix as X*, both hold the raw counts and normalization
    simply never ran. raw.X is already correct, so it is left untouched and
    only X is transformed — which also skips the full `adata.copy()` the
    promote path needs, halving peak memory on the files where that matters.

    A raw.X that *differs* from X is a genuinely different file and still
    refuses. The X sample check is a fail-fast heuristic, not a full-matrix
    guarantee — a file that looks like raw counts in its first few thousand
    entries but has fractional values elsewhere will pass. This is an
    explicit wrangler action — there is no force flag.

    The output is written as an edit snapshot (`<stem>-edit-<ts>.h5ad`)
    and the operation is logged in `uns['provenance']['edit_history']`.
    A file already in the target layout is reported, not rewritten.

    Args:
        path: Path to an .h5ad file.

    Returns:
        Dict with 'output_path', 'n_obs', 'n_vars', 'target_sum', 'raw_x'
        on success; {'already_normalized': True, ...} when the file is
        already in the target layout and nothing was written; or
        {'error': ...} on failure.
    """
    try:
        import scanpy as sc

        path = resolve_latest(path)

        check = _classify_x_at_path(path, _DEFAULT_SAMPLE_SIZE)

        # Negative values disqualify X from every actionable state: they are
        # not counts, and log1p output is never negative either.
        if check["has_negative"]:
            return {"error": "X sample contains negative values — not raw counts"}

        if not check["has_raw_x"]:
            if check["verdict"] == "indeterminate":
                return {"error": "X contains no data and there is no raw.X — nothing to normalize"}
            if not check["is_integer_valued"]:
                return {"error": "X sample contains non-integer values — appears already normalized"}
            promote = True
        else:
            raw_check = _classify_matrix_at_path(path, "raw/X", _DEFAULT_SAMPLE_SIZE)
            if raw_check["verdict"] != "raw_counts":
                return {
                    "error": (
                        f"raw.X does not hold raw counts (sample looks {raw_check['verdict']}) — refusing to overwrite"
                    )
                }
            if check["verdict"] == "normalized":
                return {
                    "already_normalized": True,
                    "message": "raw.X holds counts and X is already normalized — file is in the target layout",
                }
            if check["verdict"] == "indeterminate":
                return {"error": "X contains no data while raw.X holds counts — rebuilding X is not supported"}
            if not _raw_x_matches_x(path):
                return {"error": "raw.X exists and differs from X — refusing to overwrite"}
            promote = False

        with open_h5ad(path, backed=None) as adata:
            if promote:
                # CXG schema forbids feature_is_filtered in raw.var.
                raw_source = adata.copy()
                raw_source.var = raw_source.var.drop(columns=["feature_is_filtered"], errors="ignore")
                adata.raw = raw_source
            # Otherwise raw.X already holds these counts and is left as found,
            # var included — there is nothing to move and nothing to rebuild.

            sc.pp.normalize_total(adata, target_sum=_TARGET_SUM)
            sc.pp.log1p(adata)
            # scanpy stamps uns['log1p'] = {'base': None}; None drops on h5ad
            # write, leaving {} which CXG rejects.
            adata.uns.pop("log1p", None)

            n_obs, n_vars = adata.n_obs, adata.n_vars
            raw_x_disposition = (
                "moved from X"
                if promote
                else f"left unmodified — verified duplicate of X (full indptr, {_DUP_SAMPLE_ROWS} sampled rows)"
            )
            entry = make_edit_entry(
                operation="normalize_raw",
                description=(
                    f"{'Moved raw counts to raw.X and normalized' if promote else 'Normalized'} X with "
                    f"normalize_total(target_sum={_TARGET_SUM:g}) + log1p"
                ),
                details={
                    "target_sum": _TARGET_SUM,
                    "n_obs": n_obs,
                    "n_vars": n_vars,
                    "raw_x": raw_x_disposition,
                },
            )

            result = write_h5ad(adata, path, [entry])

        if "error" in result:
            return result

        return {
            "output_path": result["output_path"],
            "n_obs": n_obs,
            "n_vars": n_vars,
            "target_sum": _TARGET_SUM,
            "raw_x": raw_x_disposition,
        }

    except Exception as e:
        return {"error": str(e)}
