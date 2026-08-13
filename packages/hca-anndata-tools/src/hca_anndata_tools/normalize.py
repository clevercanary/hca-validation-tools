"""Normalize raw counts in X to standard CXG layout (normalized in X, raw in raw.X)."""

from __future__ import annotations

from ._io import open_h5ad
from .inspect import (
    _DEFAULT_SAMPLE_SIZE,
    _DUP_SAMPLE_ROWS,
    _classify_matrix_at_path,
    _classify_x_at_path,
    _matrices_equal,
)
from .write import make_edit_entry, resolve_latest, write_h5ad

_TARGET_SUM = 1e4

_PROMOTE = "promote"
_NORMALIZE_ONLY = "normalize_only"

# What each actionable state does to raw.X, and how it says so. Decided once and
# looked up once, so the state a future case adds (#572 rebuilds X from raw.X)
# is one entry here plus one arm below, rather than another condition threaded
# through the copy, the log detail, and the description independently.
_MODES = {
    _PROMOTE: {
        "verb": "Moved raw counts to raw.X and normalized",
        "raw_x": "moved from X",
    },
    _NORMALIZE_ONLY: {
        "verb": "Normalized",
        # "structure" rather than "indptr": both layouts compare sampled rows,
        # but the structure they compare in full differs — shape and indptr for
        # sparse, shape alone for dense. The edit log is the durable record of
        # what was checked, so it must not name evidence that does not exist for
        # the layout it is describing.
        "raw_x": f"left unmodified — verified duplicate of X (structure in full, {_DUP_SAMPLE_ROWS} sampled rows)",
    },
}


def normalize_raw(path: str) -> dict:
    """Normalize raw counts in X, moving originals to raw.X.

    Produces the standard CXG layout: raw integer counts in raw.X, and
    library-size-normalized, log1p-transformed values in X. Uses the
    scanpy recipe `normalize_total(target_sum=1e4)` + `log1p`.

    Classifying each of X and raw.X as empty, counts, or normalized gives
    nine states. Three are actionable and this handles two of them (#532);
    the third — counts in raw.X with an empty X — is #572::

        raw.X     X            outcome
        --------  -----------  --------------------------------------------
        absent    counts       promote + normalize
        counts    counts       normalize X only when the two are the same
                               matrix, refuse when they differ
        counts    normalized   already the target layout — no-op
        counts    empty        rebuild X from raw.X — not supported (#572)
        every other combination refuses

    "absent" in that first row, not "empty": a raw.X that is present but holds
    no counts is refused rather than promoted over. Overwriting it would lose
    nothing, but it is still an existing raw.X, and this has no force flag.

    **promote + normalize** is the original case: counts sit in X, raw.X is
    absent, so X is copied to raw.X before being overwritten.

    **normalize X only** is the case this exists for. When raw.X is present
    *and the same matrix as X*, both hold the raw counts and normalization
    simply never ran. raw.X is already correct, so it is left untouched and
    only X is transformed — which also skips the `adata.copy()`. Reading a file
    that already carries raw.X makes two matrices resident; copying it to build
    raw would make four, which is the difference between feasible and not on a
    file of tens of GB.

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
        on success; {'skipped': True, 'reason': ...} when the file is
        already in the target layout and nothing was written, matching
        `strip_forbidden_obs_columns` and `compress_h5ad`; or
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
            mode = _PROMOTE
        else:
            raw_check = _classify_matrix_at_path(path, "raw/X", _DEFAULT_SAMPLE_SIZE)
            if raw_check["verdict"] != "raw_counts":
                # "normalize", not "overwrite": what this path would rewrite is
                # X, not raw.X. raw.X is only ever read here.
                return {
                    "error": (
                        "raw.X does not hold raw counts — refusing to normalize. When raw.X is "
                        "present it must hold the counts X is derived from."
                    )
                }
            if check["verdict"] == "normalized":
                return {
                    "skipped": True,
                    "reason": (
                        "raw.X holds counts and X is already normalized — the file is already in the target layout."
                    ),
                }
            if check["verdict"] == "indeterminate":
                return {"error": "X contains no data while raw.X holds counts — rebuilding X is not supported"}
            # Safe to sample rather than compare exhaustively: write_h5ad emits a
            # new <stem>-edit-<ts>.h5ad and never modifies the original, so being
            # wrong here cannot destroy data.
            if not _matrices_equal(path, "X", "raw/X"):
                # Not "differs": _matrices_equal also returns False when the two
                # cannot be compared at all — mismatched encodings, dense against
                # sparse — and naming a difference there would describe a
                # comparison that never happened.
                return {
                    "error": (
                        "raw.X could not be confirmed to hold the same counts as X — refusing to "
                        "normalize. X is only safe to overwrite when raw.X already holds those counts."
                    )
                }
            mode = _NORMALIZE_ONLY

        plan = _MODES[mode]

        with open_h5ad(path, backed=None) as adata:
            if mode == _PROMOTE:
                # CXG schema forbids feature_is_filtered in raw.var.
                raw_source = adata.copy()
                raw_source.var = raw_source.var.drop(columns=["feature_is_filtered"], errors="ignore")
                adata.raw = raw_source
            # _NORMALIZE_ONLY leaves raw as found, var included — it already
            # holds these counts, so there is nothing to move or rebuild.

            sc.pp.normalize_total(adata, target_sum=_TARGET_SUM)
            sc.pp.log1p(adata)
            # scanpy stamps uns['log1p'] = {'base': None}; None drops on h5ad
            # write, leaving {} which CXG rejects.
            adata.uns.pop("log1p", None)

            n_obs, n_vars = adata.n_obs, adata.n_vars
            entry = make_edit_entry(
                operation="normalize_raw",
                description=(f"{plan['verb']} X with normalize_total(target_sum={_TARGET_SUM:g}) + log1p"),
                details={
                    "target_sum": _TARGET_SUM,
                    "n_obs": n_obs,
                    "n_vars": n_vars,
                    "raw_x": plan["raw_x"],
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
            "raw_x": plan["raw_x"],
        }

    except Exception as e:
        return {"error": str(e)}
