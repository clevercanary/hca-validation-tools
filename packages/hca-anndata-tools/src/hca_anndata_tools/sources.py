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

Matching is by cell ID only. It reads the obs index of every file and no
matrix, so a two-million-cell atlas against seven sources is a set
intersection per source. A content tier — hashing each cell's raw count row
on the pair's shared var axis, which is what recovers provenance for the
positional or synthetic IDs of liver-v1 and MSK — is a follow-up; the result
shape leaves room for it beside ``matched``.
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from ._errors import Refusal, describe_exception
from ._io import check_duplicate_ids, gate_h5ad_paths, obs_index_name, open_h5ad, read_index
from .qc import finding, run_read
from .write import resolve_latest

# The tracker layout, as two names: the ancestor that marks an integrated
# object, and the path from that ancestor's parent to its source datasets.
INTEGRATED_DIR = "integrated-objects"
SOURCE_SUBDIR = Path("source-datasets") / "tracker-source"


@gate_h5ad_paths
def find_source_datasets(path: str) -> dict:
    """Report which tracker source datasets an integrated object's cells come from.

    Read-only. Locates the candidates from the tracker layout — the sibling
    ``source-datasets/tracker-source/`` of the nearest ``integrated-objects``
    ancestor of ``path`` — and intersects each candidate's obs index with the
    target's. Reads obs indexes only; no matrix in any file is touched.

    Refuses by name when ``path`` is not under an ``integrated-objects``
    directory, when the source directory does not exist or holds no
    ``.h5ad``, when a candidate resolves to the target itself, or when the
    target's obs index has duplicate IDs (an intersection over duplicates has
    no single meaning). ``-edit-`` snapshots in the source directory collapse
    to the latest per stem, as every tool resolves a path. A candidate that
    cannot be read gets its row with ``error`` and zero counts, and the run
    continues.

    Args:
        path: Path to an integrated-object .h5ad under the tracker layout.

    Returns:
        Dict with ``filename``, ``n_obs``, ``source_dir``, ``sources`` (one
        row per candidate — ``filename``, ``n_obs``, ``matched``,
        ``fraction_of_target``, plus ``error`` when it could not be read —
        ordered by ``fraction_of_target`` descending, zero-match rows kept so
        the reader sees what was tried), ``target`` (``n_obs``, ``accounted``
        = cells matched by at least one candidate, ``unaccounted`` = cells no
        candidate accounts for, ``claimed_twice`` = cells matched by more than
        one), ``partition`` (``"exact"`` when every cell is accounted for
        exactly once and every candidate was read, otherwise the reason), and
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
    """Every source dataset in ``source_dir``: the top-level ``.h5ad`` files, edit variants collapsed to the latest."""
    if not source_dir.is_dir():
        raise Refusal(f"source directory {source_dir} does not exist")
    files = sorted(source_dir.glob("*.h5ad"))
    if not files:
        raise Refusal(f"source directory {source_dir} holds no .h5ad file")
    candidates = sorted({Path(resolve_latest(str(p))) for p in files})
    target_resolved = target.resolve()
    for candidate in candidates:
        if candidate.resolve() == target_resolved:
            raise Refusal(
                f"{candidate.name} in {source_dir} is the target itself; an integrated object is not its own source"
            )
    return candidates


def _read_obs_ids(path: str) -> tuple[np.ndarray, str]:
    """The obs index of a file anndata can open, with the index dataset's name."""
    with open_h5ad(path, backed="r"):
        pass  # the Scope rule: a file anndata rejects is refused, not read around
    with h5py.File(path, "r") as f:
        obs = f["obs"]
        name = obs_index_name(obs)
        return read_index(obs, name, "obs"), name


def _find_source_datasets_at_path(path: str) -> dict:
    target = Path(path)
    source_dir = source_directory(target)
    candidates = list_candidates(source_dir, target)

    target_ids, index_name = _read_obs_ids(path)
    if (dup := check_duplicate_ids(target_ids, "obs")) is not None:
        raise Refusal(f"{dup}; an intersection over duplicate IDs has no single meaning")
    n_obs = len(target_ids)
    index = pd.Index(target_ids)
    claims = np.zeros(n_obs, dtype=np.int64)

    rows = []
    for candidate in candidates:
        row: dict = {"filename": candidate.name, "n_obs": None, "matched": 0, "fraction_of_target": 0.0}
        try:
            ids, _ = _read_obs_ids(str(candidate))
            hits = index.isin(ids)
            claims += hits
            row["n_obs"] = len(ids)
            row["matched"] = int(hits.sum())
            row["fraction_of_target"] = row["matched"] / n_obs if n_obs else 0.0
        except Exception as e:
            row["error"] = describe_exception(e)[0]
        rows.append(row)
    rows.sort(key=lambda r: (-r["fraction_of_target"], r["filename"]))

    unaccounted = claims == 0
    twice = claims > 1
    n_unaccounted, n_twice = int(unaccounted.sum()), int(twice.sum())
    n_errors = sum("error" in r for r in rows)

    reasons = []
    if n_unaccounted:
        reasons.append(f"{n_unaccounted} of {n_obs} target cells unaccounted for")
    if n_twice:
        reasons.append(f"{n_twice} target cells claimed by more than one source")
    if n_errors:
        reasons.append(f"{n_errors} candidate(s) could not be read")

    element = f"obs/{index_name}"
    findings = []
    if n_unaccounted:
        findings.append(finding("unaccounted_cells", n_unaccounted, target_ids[unaccounted], element))
    if n_twice:
        findings.append(finding("cells_claimed_twice", n_twice, target_ids[twice], element))

    return {
        "filename": target.name,
        "n_obs": n_obs,
        "source_dir": str(source_dir),
        "sources": rows,
        "target": {
            "n_obs": n_obs,
            "accounted": n_obs - n_unaccounted,
            "unaccounted": n_unaccounted,
            "claimed_twice": n_twice,
        },
        "partition": "exact" if not reasons else "; ".join(reasons),
        "findings": findings,
    }
