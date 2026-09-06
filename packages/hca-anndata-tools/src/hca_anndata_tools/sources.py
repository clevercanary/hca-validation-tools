"""Which tracker source datasets an integrated object is built from (#705).

Every time the question has come up it was answered by hand: the breast-v1
audit intersected each of seven source obs indexes against the atlas (#534,
#636), the gut-v1 provenance report did the same for the lineage files. This
is that intersection as a tool, over the tracker's directory layout.

The layout is the whole declaration of a collection (#530's open question).
An integrated object lives somewhere under ``<project>/integrated-objects/``
— directly, or in ``tracker-source/``, ``cap-source/``, ``archive/`` — and
its sources are every ``.h5ad`` at the top of the sibling
``<project>/source-datasets/tracker-source/``. Nothing overrides that: a
target outside the layout is refused by name rather than guessed at, because
a wrong candidate directory would report a confident, wrong provenance.

Matching is by cell ID only. Beyond the anndata open that gates each file,
it reads the obs index and no matrix, so a two-million-cell atlas against
seven sources is a set intersection per source. A content tier — hashing each cell's raw count row
on the pair's shared var axis, which is what recovers provenance for the
positional or synthetic IDs of liver-v1 and MSK — is a follow-up; the result
shape leaves room for it beside ``matched_by_id``.
"""

from __future__ import annotations

import os
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from ._errors import Refusal
from ._io import check_duplicate_ids, gate_h5ad_paths, obs_index_name, open_h5ad, read_index
from .qc import SAMPLE_ID_LIMIT, finding, run_read
from .write import resolve_latest, strip_timestamp

# The tracker layout, as two names: the ancestor that marks an integrated
# object, and the path from that ancestor's parent to its source datasets.
INTEGRATED_DIR = "integrated-objects"
SOURCE_SUBDIR = Path("source-datasets") / "tracker-source"

# The partition verdict: a code, as every sibling check reports, so a reader
# switches on it and composes any prose from ``target``'s counts.
PARTITIONS = ("exact", "incomplete")


@gate_h5ad_paths
def find_source_datasets(path: str) -> dict:
    """Report which tracker source datasets an integrated object's cells come from.

    Read-only. Locates the candidates from the tracker layout — the sibling
    ``source-datasets/tracker-source/`` of the nearest ``integrated-objects``
    ancestor of ``path`` — and intersects each candidate's obs index with the
    target's. No matrix in any file is touched: beyond the anndata open
    that gates each file (which materialises its obs, var, and uns), only
    the obs index is read.

    Refuses by name when ``path`` is not under an ``integrated-objects``
    directory, when the source directory does not exist or holds no
    ``.h5ad``, when a candidate resolves to the target itself, or when the
    target's obs index has duplicate IDs (an intersection over duplicates has
    no single meaning), or when any file's obs index is not stored as
    strings (an integer index is bad input, not something to convert). A
    candidate anndata cannot open is refused in anndata's own words, as the
    gate refuses the target. ``-edit-`` snapshots in the source directory
    collapse to the latest per stem, as every tool resolves a path.

    Args:
        path: Path to an integrated-object .h5ad under the tracker layout.

    Returns:
        Dict with ``filename``, ``source_dir``, ``sources`` (one row per
        candidate — ``filename``, ``n_obs``, ``matched_by_id``,
        ``fraction_of_target``; ordered by ``fraction_of_target`` descending,
        zero-match rows kept so the reader sees what was tried), ``target``
        (``n_obs``, ``accounted`` = cells matched by at least one candidate,
        ``unaccounted`` = cells no candidate accounts for, ``claimed_twice`` =
        cells matched by more than one), ``partition`` — one of
        :data:`PARTITIONS`: ``"exact"`` when every cell is accounted for
        exactly once, otherwise ``"incomplete"``, with ``target`` and
        ``findings`` carrying the why — and
        ``findings`` — ``unaccounted_cells`` and ``cells_claimed_twice`` in
        the shared finding shape, IDs capped at 20. On failure, ``error`` is
        returned instead.
    """
    return run_read(path, _find_source_datasets_at_path)


def source_directory(target: Path) -> Path:
    """The tracker-layout source directory for an integrated object, refused by name when the layout is absent."""
    for parent in target.parents:
        if parent.name == INTEGRATED_DIR:
            return parent.parent / SOURCE_SUBDIR
    raise Refusal(
        f"{target} is not under an '{INTEGRATED_DIR}' directory, so its source datasets cannot be located; "
        f"the tracker layout is <project>/{INTEGRATED_DIR}/... beside <project>/{SOURCE_SUBDIR}/"
    )


def list_candidates(source_dir: Path, target: Path) -> list[Path]:
    """Every source dataset in ``source_dir``: the top-level ``.h5ad`` files, edit variants collapsed to the latest.

    One listing, then one :func:`resolve_latest` per distinct stem — the same
    resolution every tool applies to a path, so a source beside its own
    ``-edit-`` snapshots is one candidate, named by its newest file.
    """
    if not source_dir.is_dir():
        raise Refusal(f"source directory {source_dir} does not exist")
    stems = {strip_timestamp(p.name) for p in source_dir.glob("*.h5ad") if p.is_file()}
    if not stems:
        raise Refusal(f"source directory {source_dir} holds no .h5ad file")
    candidates = sorted(Path(resolve_latest(str(source_dir / stem))) for stem in stems)
    for candidate in candidates:
        if candidate.samefile(target):  # symlink or hard link alike; both paths exist here
            raise Refusal(
                f"{candidate.name} in {source_dir} is the target itself; an integrated object is not its own source"
            )
    return candidates


def _require_string_ids(ids: np.ndarray, label: str) -> None:
    """Cell IDs are strings; an index stored as numbers is bad input, refused rather than converted."""
    if ids.dtype.kind != "O":
        raise Refusal(f"{label} obs index is stored as {ids.dtype}, not strings; cell IDs must be strings to match")


def _read_ids(path: Path) -> tuple[np.ndarray, str]:
    """A file's obs index in its stored dtype (so a numeric index is seen as one), with the index dataset's name."""
    with h5py.File(path, "r") as f:
        obs = f["obs"]
        name = obs_index_name(obs)
        ids = read_index(obs, name, "obs")
    _require_string_ids(ids, path.name)
    return ids, name


def _read_candidate_ids(path: Path) -> np.ndarray:
    """A candidate's obs index, behind the Scope rule the decorator applies to the target only.

    A file anndata rejects is refused in anndata's own words, as the gate
    refuses the target, rather than read around.
    """
    try:
        with open_h5ad(str(path), backed="r"):
            pass
    except Exception as e:
        raise Refusal(f"{path.name}: {e}") from e
    return _read_ids(path)[0]


def _find_source_datasets_at_path(path: str) -> dict:
    # Lexically normalised, not resolved: a ``..`` hop must not slip a file
    # from outside the layout past the ancestor walk, while a symlinked tree
    # (a scratch copy of the layout) keeps the layout it was built with —
    # which is why ``Path.resolve()``, ruff's suggestion, is the wrong call.
    target = Path(os.path.abspath(path))  # noqa: PTH100
    source_dir = source_directory(target)
    candidates = list_candidates(source_dir, target)

    target_ids, index_name = _read_ids(target)  # the gate has opened the target through anndata already
    index = pd.Index(target_ids)
    if (dup := check_duplicate_ids(index, "obs")) is not None:
        raise Refusal(f"{dup}; an intersection over duplicate IDs has no single meaning")
    n_obs = len(index)
    claims = np.zeros(n_obs, dtype=np.int64)

    rows = []
    for candidate in candidates:
        ids = _read_candidate_ids(candidate)
        # Probe the candidate's IDs against the target's hash engine, built
        # once above; unique positions so a duplicated source ID counts once.
        hit = np.unique(index.get_indexer(ids))
        hit = hit[hit >= 0]
        claims[hit] += 1
        rows.append(
            {
                "filename": candidate.name,
                "n_obs": len(ids),
                "matched_by_id": int(hit.size),
                "fraction_of_target": hit.size / n_obs if n_obs else 0.0,
            }
        )
    rows.sort(key=lambda r: (-r["fraction_of_target"], r["filename"]))

    unaccounted, twice = np.flatnonzero(claims == 0), np.flatnonzero(claims > 1)
    element = f"obs/{index_name}"
    findings = [
        finding(code, where.size, target_ids[where[:SAMPLE_ID_LIMIT]], element)
        for code, where in (("unaccounted_cells", unaccounted), ("cells_claimed_twice", twice))
        if where.size
    ]
    return {
        "filename": target.name,
        "source_dir": str(source_dir),
        "sources": rows,
        "target": {
            "n_obs": n_obs,
            "accounted": n_obs - unaccounted.size,
            "unaccounted": int(unaccounted.size),
            "claimed_twice": int(twice.size),
        },
        "partition": "exact" if not findings else "incomplete",
        "findings": findings,
    }
