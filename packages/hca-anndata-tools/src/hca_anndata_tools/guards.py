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

:func:`detect_obs_references` finds all three at once and carries enough for
any of the three responses: the matched names a **refuse** needs to report,
the palette keys a **cascade** needs to move or delete, and — for
``batch_condition`` — the whole declaration a **repair** needs to rewrite.
What a tool does with each is that tool's policy, at its own call site.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import h5py

from ._io import direct_members, obs_index_name, read_batch_condition
from .cap import LEGACY_LAYOUT_DESCRIPTION, cap_obs_columns, is_cap_declared, is_legacy_cap_layout

__all__ = [
    "GuardRefusal",
    "ObsColumnReferences",
    "batch_condition_refusal",
    "detect_obs_references",
    "direct_members",
    "is_malformed_name",
    "legacy_layout_problems",
    "malformed_name_problems",
    "obs_index_problems",
    "obs_name_problems",
    "require_obs_group",
]


class GuardRefusal(Exception):
    """A precondition the caller must fix before the tool can run.

    Carries the message verbatim: every mutating tool ends in
    ``except Exception as e: return {"error": str(e)}``, so raising produces
    the same error dict a returned refusal would, without threading an
    optional group through the call site.
    """


# --- structural invariants ---------------------------------------------------


def is_malformed_name(name: str) -> bool:
    """True if the name cannot be an obs column: it contains ``/`` or is blank.

    h5py resolves a name containing ``/`` as an HDF5 link path, not a dict
    key: a leading slash resolves from the file root and inner slashes
    traverse subgroups, so ``del obs["/X"]`` would unlink the expression
    matrix. Every guard compares plain strings, so rejecting these up front
    is what keeps the checks agreeing with what the operation would do.

    The predicate, separate from :func:`malformed_name_problems`, because
    callers need the set as well as the message: a malformed name is excluded
    from the absent-name report so each bad name is named once.
    """
    return "/" in name or not name.strip()


# Reported names are capped; checked names never are. A malformed file can
# list hundreds of stale column-order entries, and these strings travel back
# through an MCP tool response — but truncating the *input* would let a name
# past position N reach the delete unchecked (#623).
_MAX_REPORTED = 5


def _listing(names: list[str]) -> str:
    """Format a name list for an error message, capped with a count."""
    if len(names) <= _MAX_REPORTED:
        return str(names)
    return f"{names[:_MAX_REPORTED]} (+{len(names) - _MAX_REPORTED} more)"


def malformed_name_problems(names: Iterable[str]) -> list[str]:
    """A problem entry naming every malformed name, or an empty list."""
    malformed = [n for n in names if is_malformed_name(n)]
    if malformed:
        return [f"not valid obs column names (a column name cannot contain '/' or be blank): {_listing(malformed)}"]
    return []


def obs_index_problems(obs: h5py.Group, names: Iterable[str], *, verbing: str) -> list[str]:
    """A problem entry if any name is the obs index.

    The index is a dataset in the obs group like any column, so a caller can
    name it; mutating it destroys the file's cell identities. ``verbing`` is
    the tool's gerund ("deleting", "renaming").
    """
    index_name = obs_index_name(obs)
    if index_name in names:
        return [f"'{index_name}' is the obs index, not a column — {verbing} it would destroy the file"]
    return []


def obs_name_problems(obs: h5py.Group, names: Iterable[str], *, verbing: str) -> list[str]:
    """Every structural reason these names cannot be operated on.

    The three checks any obs mutation owes, whatever the name source — a
    caller's request, or the file's own ``column-order`` attribute: the names
    are well-formed, none is the index, and each is a direct child.
    """
    names = list(names)
    problems = malformed_name_problems(names)
    problems += obs_index_problems(obs, names, verbing=verbing)
    members = direct_members(obs)
    absent = [n for n in names if n not in members and not is_malformed_name(n)]
    if absent:
        problems.append(f"not present in obs: {_listing(absent)}")
    return problems


def require_obs_group(f: h5py.File) -> h5py.Group:
    """The file's obs group, or raise :class:`GuardRefusal`.

    Two messages, deliberately: a missing obs group and a pre-modern layout
    (obs stored as a Dataset) are different repairs for the caller.
    """
    obs = f.get("obs")
    if obs is None:
        raise GuardRefusal("File has no obs group")
    if not isinstance(obs, h5py.Group):
        raise GuardRefusal("obs is not a group — the file predates the modern h5ad layout")
    return obs


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

    ``batch_condition``: the requested names the declaration lists, sorted —
    what a refusal reports. ``batch_condition_declared``: the whole
    declaration in file order — what a repair rewrites, which the
    intersection alone cannot support. ``palettes``: requested name →
    ``'<name>_colors'`` key present in uns. ``cap_columns``: requested names
    carrying the CAP ``--`` separator while an annotation set is declared.
    """

    batch_condition: list[str]
    batch_condition_declared: list[str]
    palettes: dict[str, str]
    cap_columns: list[str]


def detect_obs_references(uns: h5py.Group | None, names: Iterable[str]) -> ObsColumnReferences:
    """Find every reference to the named obs columns, across all three mechanisms."""
    names = list(names)
    declared = read_batch_condition(uns)
    palettes: dict[str, str] = {}
    cap_columns: list[str] = []
    if uns is not None:
        # direct_members, not `key in uns`: a name like '/X' would make h5py
        # resolve '/X_colors' from the file root, so a root dataset of that
        # name would be reported as this column's palette — and, in drop,
        # deleted with it. Malformed names are refused before any write, so
        # this is the belt to that brace (#623).
        uns_members = direct_members(uns)
        palettes = {n: key for n in names if (key := f"{n}_colors") in uns_members}
        # Over-refusing a '--' name in a CAP file is the safe direction, and no
        # column the mutating tools target uses that separator. Gated on the
        # declaration: without it there is no annotation set to break.
        if is_cap_declared(uns):
            cap_columns = sorted(cap_obs_columns(names))
    return ObsColumnReferences(
        batch_condition=sorted(set(names) & set(declared)),
        batch_condition_declared=declared,
        palettes=palettes,
        cap_columns=cap_columns,
    )


def batch_condition_refusal(columns: list[str], *, verbing: str) -> str:
    """The shared refusal for a by-value reference a tool cannot repair.

    Rewriting the declaration is a curation decision, not the tool's to take —
    the caller edits ``uns['batch_condition']`` first if the change is
    intended.
    """
    return (
        f"referenced by uns['batch_condition']: {columns} — that list declares "
        f"which columns define the experiment's batches, so {verbing} one changes "
        f"the declaration. Edit uns['batch_condition'] first if that is intended"
    )
