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

Each source is also named as the tracker names it (#776). A download is
``<tracker name>-r<revision>-wip-<n>.h5ad``, so the name is read back off the
file; :func:`hca_anndata_tools.source_dataset.set_source_dataset` writes those
names into ``obs['source_dataset']``, and both tools match through
:func:`match_sources` so the preview and the write cannot disagree.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
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

# The tracker's download names end in -r<revision>-wip-<n>, or -r<revision> once
# published; the part before is the file's name on the tracker. The same rule as
# hca_tracker_client.verify.file_stem, copied rather than imported: this package
# is published and cannot depend on the private client.
_TRACKER_DOWNLOAD = re.compile(r"^(?P<stem>.+)-r\d+(?:-wip-\d+)?\.h5ad$")


def tracker_name(filename: str) -> str | None:
    """The tracker's name for a downloaded file: our ``-edit-`` suffix, then the tracker's, removed; None if not one."""
    match = _TRACKER_DOWNLOAD.match(strip_timestamp(filename))
    return match.group("stem") if match else None


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

    Each candidate is named as the tracker names it (:func:`tracker_name`):
    a candidate whose file name is not a tracker download name is refused, as
    are two candidates naming the same tracker source dataset (two revisions
    side by side), since both would claim the same cells.

    Args:
        path: Path to an integrated-object .h5ad under the tracker layout.

    Returns:
        Dict with ``filename``, ``tracker_name`` (the target's, or None when
        its file name is not a tracker download name — a CAP export's, say),
        ``source_dir``, ``sources`` (one row per
        candidate — ``filename``, ``tracker_name``, ``n_obs``, ``matched_by_id``,
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
    if not source_dir.exists():
        raise Refusal(f"source directory {source_dir} does not exist")
    if not source_dir.is_dir():
        raise Refusal(f"source directory {source_dir} is not a directory")
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


@dataclass
class SourceMatch:
    """Which source each of an integrated object's cells comes from, by cell ID.

    ``sources`` is one row per candidate in candidate order, and ``owner`` holds,
    per target cell, the position in it of a source claiming that cell (-1 for
    none); only where ``claims`` is 1 is that the one source.
    """

    target: Path
    source_dir: Path
    target_ids: np.ndarray
    index_name: str
    sources: list[dict]
    owner: np.ndarray
    claims: np.ndarray

    def findings(self) -> list[dict]:
        """The cells that keep the match from being a partition, in the shared finding shape."""
        unaccounted, twice = np.flatnonzero(self.claims == 0), np.flatnonzero(self.claims > 1)
        element = f"obs/{self.index_name}"
        return [
            finding(code, where.size, self.target_ids[where[:SAMPLE_ID_LIMIT]], element)
            for code, where in (("unaccounted_cells", unaccounted), ("cells_claimed_twice", twice))
            if where.size
        ]


def _candidate_names(candidates: list[Path]) -> list[str]:
    """Each candidate's tracker name, refusing a file that is not a tracker download and two files that are one."""
    read = [(c.name, tracker_name(c.name)) for c in candidates]
    unfit = [filename for filename, name in read if name is None]
    if unfit:
        raise Refusal(
            f"not tracker download names (<name>-r<revision>-wip-<n>.h5ad or <name>-r<revision>.h5ad), so "
            f"their tracker names cannot be read: {unfit}"
        )
    names = [name for _, name in read if name is not None]
    by_name: dict[str, list[str]] = {}
    for (filename, _), name in zip(read, names, strict=True):
        by_name.setdefault(name, []).append(filename)
    # Two revisions of one source downloaded side by side: both would claim the
    # same cells, and the double claim would not say why.
    repeated = {name: files for name, files in by_name.items() if len(files) > 1}
    if repeated:
        raise Refusal(f"more than one copy of the same tracker source dataset; keep one of each: {repeated}")
    return names


def match_sources(path: str) -> SourceMatch:
    """Match an integrated object's cells against its tracker source datasets by ID; refuses as the tools document."""
    # Lexically normalised, not resolved: a ``..`` hop must not slip a file
    # from outside the layout past the ancestor walk, while a symlinked tree
    # (a scratch copy of the layout) keeps the layout it was built with —
    # which is why ``Path.resolve()``, ruff's suggestion, is the wrong call.
    target = Path(os.path.abspath(path))  # noqa: PTH100
    source_dir = source_directory(target)
    candidates = list_candidates(source_dir, target)
    names = _candidate_names(candidates)

    target_ids, index_name = _read_ids(target)  # the gate has opened the target through anndata already
    index = pd.Index(target_ids)
    if (dup := check_duplicate_ids(index, "obs")) is not None:
        raise Refusal(f"{dup}; an intersection over duplicate IDs has no single meaning")
    n_obs = len(index)
    claims = np.zeros(n_obs, dtype=np.int64)
    owner = np.full(n_obs, -1, dtype=np.int64)

    rows = []
    for position, (candidate, name) in enumerate(zip(candidates, names, strict=True)):
        ids = _read_candidate_ids(candidate)
        # Probe the candidate's IDs against the target's hash engine, built
        # once above; unique positions so a duplicated source ID counts once.
        hit = np.unique(index.get_indexer(ids))
        hit = hit[hit >= 0]
        claims[hit] += 1
        owner[hit] = position
        rows.append(
            {
                "filename": candidate.name,
                "tracker_name": name,
                "n_obs": len(ids),
                "matched_by_id": int(hit.size),
                "fraction_of_target": hit.size / n_obs if n_obs else 0.0,
            }
        )
    return SourceMatch(target, source_dir, target_ids, index_name, rows, owner, claims)


def _find_source_datasets_at_path(path: str) -> dict:
    match = match_sources(path)
    rows = sorted(match.sources, key=lambda r: (-r["fraction_of_target"], r["filename"]))
    findings = match.findings()
    n_obs = len(match.target_ids)
    unaccounted, twice = int((match.claims == 0).sum()), int((match.claims > 1).sum())
    return {
        "filename": match.target.name,
        "tracker_name": tracker_name(match.target.name),
        "source_dir": str(match.source_dir),
        "sources": rows,
        "target": {
            "n_obs": n_obs,
            "accounted": n_obs - unaccounted,
            "unaccounted": unaccounted,
            "claimed_twice": twice,
        },
        "partition": "exact" if not findings else "incomplete",
        "findings": findings,
    }
