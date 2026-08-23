"""Shared coherence guards for the obs-mutating tools.

The organizing principle (#614): a tool owes its caller a *coherent* file —
no dangling references, no destroyed cell identities, nothing reachable
outside the group being edited — and the validator, not the tool, owns
*validity*. These helpers are the single implementation of the checks that
principle keeps, extracted (#622) after per-tool copies drifted twice
(#552, and within #616's review).

Three things reference an obs column, each pointing a different way, which
is why per-site reasoning kept missing one:

- **by value** — ``uns['batch_condition']`` lists obs column names (the only
  obs reference the HCA schema itself declares);
- **by key name** — ``uns['<column>_colors']`` palettes;
- **by naming convention** — CAP annotation-set columns named
  ``<set>--<suffix>``, declared by ``uns['cap_metadata']``.

:func:`detect_obs_references` finds all three at once. What a tool *does*
about each — repair, refuse, or cascade — is that tool's policy, stated as a
labeled block at its call site; only detection and the shared refusal wording
live here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import h5py

from ._io import _decode_bytes, read_batch_condition
from .cap import CAP_METADATA_KEY, LEGACY_LAYOUT_DESCRIPTION, is_legacy_cap_layout

# --- structural invariants ---------------------------------------------------


def malformed_name_problems(names: Iterable[str]) -> list[str]:
    """Names that cannot be obs columns: containing ``/`` or blank.

    h5py resolves a name containing ``/`` as an HDF5 link path, not a dict
    key: a leading slash resolves from the file root and inner slashes
    traverse subgroups, so ``del obs["/X"]`` would unlink the expression
    matrix. Every guard compares plain strings, so rejecting these up front
    is what keeps the checks agreeing with what the operation would do.
    """
    malformed = [n for n in names if "/" in n or not n.strip()]
    if malformed:
        return [f"not valid obs column names (a column name cannot contain '/' or be blank): {malformed}"]
    return []


def obs_index_name(obs: h5py.Group) -> str:
    """The name of the obs index dataset, from ``obs.attrs['_index']``."""
    return _decode_bytes(obs.attrs.get("_index", "_index"))


def obs_index_problems(obs: h5py.Group, names: Iterable[str], *, consequence: str) -> list[str]:
    """A problem entry if any name is the obs index.

    The index is a dataset in the obs group like any column, so a caller can
    name it; mutating it destroys the file's cell identities. ``consequence``
    finishes the sentence with the tool's own verb ("deleting it would
    destroy the file", "renaming it would destroy the file").
    """
    index_name = obs_index_name(obs)
    if index_name in names:
        return [f"'{index_name}' is the obs index, not a column — {consequence}"]
    return []


def direct_members(obs: h5py.Group) -> set[str]:
    """The obs group's direct children, for membership tests.

    Membership against this set, not ``name in obs`` — the latter resolves
    link paths and so accepts names that point outside obs entirely (the
    ``/`` trap :func:`malformed_name_problems` rejects).
    """
    return set(obs.keys())


def require_obs_group(f: h5py.File) -> tuple[h5py.Group | None, dict | None]:
    """The file's obs group, or the error dict refusing its absence.

    Two messages, deliberately: a missing obs group and a pre-modern layout
    (obs stored as a Dataset) are different repairs for the caller.
    """
    obs = f.get("obs")  # not read_group: the two failure shapes get different messages
    if obs is None:
        return None, {"error": "File has no obs group"}
    if not isinstance(obs, h5py.Group):
        return None, {"error": "obs is not a group — the file predates the modern h5ad layout"}
    return obs, None


def legacy_layout_problems(uns: h5py.Group | None) -> list[str]:
    """A problem entry if the file uses the deprecated top-level CAP layout.

    A layout precondition, not a validity verdict: in this layout
    ``uns['cap_metadata']`` is absent, so the CAP reference detection sees no
    declaration and every CAP column looks mutable — the shape of #552.
    Refusing the whole file is the point.
    """
    if is_legacy_cap_layout(uns):
        return [f"the file uses {LEGACY_LAYOUT_DESCRIPTION}, which is not supported"]
    return []


# --- the reference detector --------------------------------------------------


@dataclass(frozen=True)
class ObsColumnReferences:
    """What in the file references the named obs columns, by mechanism.

    ``batch_condition``: the requested names listed in
    ``uns['batch_condition']``, sorted. ``palettes``: requested name →
    ``'<name>_colors'`` key present in uns, in request order. ``cap_columns``:
    requested names carrying the CAP ``--`` separator while
    ``uns['cap_metadata']`` declares annotation sets, sorted.
    """

    batch_condition: list[str]
    palettes: dict[str, str]
    cap_columns: list[str]


def detect_obs_references(uns: h5py.Group | None, names: Iterable[str]) -> ObsColumnReferences:
    """Find every reference to the named obs columns, across all three mechanisms."""
    names = list(names)
    batched = sorted(set(names) & set(read_batch_condition(uns)))
    palettes: dict[str, str] = {}
    cap_columns: list[str] = []
    if uns is not None:
        palettes = {n: key for n in names if (key := f"{n}_colors") in uns}
        # Keyed on the '--' convention rather than on parsing cap_metadata,
        # which may be stored as either a group or a JSON string: over-refusing
        # a '--' name in a CAP file is the safe direction, and no column the
        # mutating tools target uses that separator. Keyed on CAP_METADATA_KEY
        # rather than the literal so a canonical-key rename moves cap.py and
        # this check together (#552, in the other direction).
        if CAP_METADATA_KEY in uns:
            cap_columns = sorted(n for n in names if "--" in n)
    return ObsColumnReferences(batch_condition=batched, palettes=palettes, cap_columns=cap_columns)


def batch_condition_refusal(columns: list[str], *, verbing: str) -> str:
    """The shared refusal for a by-value reference a tool cannot repair.

    ``verbing`` is the tool's gerund ("dropping", "removing"). Rewriting the
    declaration is a curation decision, not the tool's to take — the caller
    edits ``uns['batch_condition']`` first if the change is intended.
    """
    return (
        f"referenced by uns['batch_condition']: {columns} — that list declares "
        f"which columns define the experiment's batches, so {verbing} one changes "
        f"the declaration. Edit uns['batch_condition'] first if that is intended"
    )


def cap_palette_keys(keys: Iterable[str]) -> list[str]:
    """CAP-shaped palette keys: ``<name>_colors`` where the base name is a CAP
    ``--`` column. Both those paired with a present column and those already
    orphaned by an earlier era's overwrite, which deleted columns but left
    palettes."""
    return [k for k in keys if k.endswith("_colors") and "--" in k.removesuffix("_colors")]
