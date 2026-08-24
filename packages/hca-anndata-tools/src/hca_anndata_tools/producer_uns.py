"""Write scalar values into producer-owned, nested ``uns`` namespaces.

The remedy for a correction a producer asks us to apply to their own metadata:
``clevercanary/hca-ingest-coordination#23`` corrects three fields inside
``uns['ihbca_provenance']`` on seven breast-v1 source datasets, and nothing in
the toolkit could reach them. The alternative was a hand-written h5py snippet
run once against files up to 27 GB — untested, and outside the HCA schema, so
``validate_schema`` has no opinion on whether it wrote the right thing.

Deliberately not an extension of :func:`~hca_anndata_tools.edit.set_uns`.
That tool addresses a flat top-level key, so a nested path is inexpressible in
its signature under any flag; it also validates against the HCA schema
registry, materializes the whole file, and writes one field per call. Only the
registry gate is about schema — the rest are why this is a separate entry
point (#629). Where scope is only "write a non-schema top-level key", a flag on
``set_uns`` would have been the right answer.

The guards here are **coherence** guards, not validity guards, which is what
keeps this on the right side of #614. That principle defers validity to
``validate_schema`` — but it presumes a validator with an opinion, and for a
producer-owned namespace there is none: an extra or wrongly-typed uns key is
not a schema violation, so nothing downstream would catch it. Refusing a path
that does not exist, and a value that would change the stored dtype, is what
replaces that missing backstop.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from ._io import read_edit_log_h5py, read_group, read_uns, write_edit_log_h5py
from ._keys import PROVENANCE_KEY
from ._serialize import make_serializable
from .guards import is_malformed_name
from .schema.helpers import non_producer_uns_roots, uns_field_registry
from .write import (
    build_edit_log,
    cleanup_previous_version,
    make_edit_entry,
    parse_edit_log,
    resolve_latest,
    snapshot_copy_hashed,
)


@dataclass(frozen=True)
class _PlannedWrite:
    """One validated field write, carried from validation to the write phase.

    Validation reads the source read-only and the write happens on a snapshot,
    so no h5py object survives between the two — the path segments and the
    already-coerced value do.

    ``expected`` is both what gets assigned and what the read-back must see:
    every value is coerced through the target dtype during validation, so
    assigning it is what makes the two agree by construction.
    """

    field: tuple[str, ...]
    expected: Any  # assigned, and what the read-back must see; JSON-shaped
    old_value: Any
    dtype: np.dtype


def _display(field: tuple[str, ...]) -> str:
    """A field path as the caller would subscript it: ``uns['a']['b']``."""
    return "uns" + "".join(f"[{segment!r}]" for segment in field)


def _parse_updates(updates: Any) -> tuple[list[tuple[tuple[str, ...], Any]], list[str]]:
    """Normalize the caller's ``updates`` into ``(field, value)`` pairs.

    MCP-exposed, so this arrives as decoded JSON and may hold anything.
    Structural problems are collected rather than raised so a caller who got
    two entries wrong learns both in one round trip.

    Returns:
        ``(parsed, problems)``. Only well-formed entries appear in ``parsed``;
        positions do not correspond to the input.
    """
    problems: list[str] = []
    if not isinstance(updates, list):
        return [], [f"updates must be a list of {{'field': [...], 'value': ...}} entries, got {type(updates).__name__}"]
    if not updates:
        return [], ["updates must not be empty — every write should change something"]

    parsed: list[tuple[tuple[str, ...], Any]] = []
    for i, entry in enumerate(updates):
        if not isinstance(entry, dict):
            problems.append(f"updates[{i}] must be an object with 'field' and 'value', got {type(entry).__name__}")
            continue
        if missing := {"field", "value"} - entry.keys():
            problems.append(f"updates[{i}] is missing {sorted(missing)}")
            continue
        field = entry["field"]
        # A slash-joined string is the likely mistake — it is how the path
        # reads in prose, and it is what a flat-key tool would take. Say so
        # rather than reporting a type error, because the fix is not obvious.
        if isinstance(field, str):
            problems.append(
                f"updates[{i}]['field'] must be a list of path segments, not the string {field!r} — "
                f"pass {[s for s in field.split('/') if s] or [field]} instead"
            )
            continue
        if not isinstance(field, list) or not field:
            problems.append(f"updates[{i}]['field'] must be a non-empty list of path segments")
            continue
        if bad := [s for s in field if not isinstance(s, str)]:
            problems.append(f"updates[{i}]['field'] segments must be strings; got {bad}")
            continue
        # Same predicate the obs guards use, different message: a segment
        # containing '/' would be resolved by h5py as a further link path, so
        # the check that runs and the walk that follows would disagree about
        # what was addressed.
        if malformed := [s for s in field if is_malformed_name(s)]:
            problems.append(
                f"updates[{i}]['field'] has segments that cannot name a uns key "
                f"(a segment cannot contain '/' or be blank): {malformed}"
            )
            continue
        parsed.append((tuple(field), entry["value"]))

    seen: set[tuple[str, ...]] = set()
    for field, _ in parsed:
        if field in seen:
            problems.append(f"{_display(field)} appears more than once in updates — the intended value is ambiguous")
        seen.add(field)

    return parsed, problems


def _namespace_problem(field: tuple[str, ...]) -> str | None:
    """Refuse a path this tool does not own: our provenance, or an HCA field.

    :func:`non_producer_uns_roots` decides *whether* to refuse; each message
    below is gated on its own reason, so a root added to that set for a third
    reason gets a true refusal rather than inheriting one of these.
    """
    root = field[0]
    if root not in non_producer_uns_roots():
        return None
    # Our audit trail lives at uns/provenance/edit_history. A tool that could
    # write arbitrary scalars in there could rewrite the record every other
    # tool's guarantees rest on, so the whole namespace is off limits —
    # including for a producer who put their own keys there (#576). Costs the
    # motivating case nothing: its namespace is 'ihbca_provenance', a
    # different key.
    if root == PROVENANCE_KEY:
        return (
            f"{_display(field)} is inside our own provenance namespace, which carries the edit log — "
            f"this tool will not write there"
        )
    # Coherence, not only routing — the distinction matters, because #621
    # removed a guard defended on routing grounds alone. Two of the five
    # registry fields hold *references into other groups*: set_uns checks
    # batch_condition against obs.columns and default_embedding against
    # obsm.keys(). Writing either raw through this tool could leave a
    # batch_condition naming an obs column that does not exist — a dangling
    # reference, which #614 puts squarely in the keep column. Routing is the
    # secondary reason: two doors to one field would let a caller pick the
    # one that checks less.
    #
    # Tested here rather than assumed from set membership: pointing a curator
    # at set_uns is only honest for a field set_uns can actually take, and
    # this justification is specific to those reference-holding fields.
    if root in uns_field_registry():
        return f"'{root}' is an HCA schema uns field — use set_uns, which validates it against the schema"
    # Unreachable while non_producer_uns_roots() is *derived* as exactly
    # registry + provenance, so the two branches above cover it. Here because
    # the set is derived rather than enumerated: widen that derivation and this
    # is what a root reserved for the new reason gets, instead of silently
    # inheriting the set_uns redirect above, which would be false for it.
    return f"{_display(field)} is inside a reserved uns root — this tool will not write there"


def _edit_log_target_problem(f: h5py.File) -> str | None:
    """Refuse now if the edit log could not be written later.

    Every write ends by stamping ``uns/provenance/edit_history``, and
    ``ensure_provenance_group`` needs ``uns['provenance']`` to be a group or
    absent. A producer who used that unnamespaced key for something else (#576)
    would otherwise get a raw h5py "Incompatible object (Dataset) already
    exists" *after* the copy — the same late refusal the ``parse_edit_log``
    check exists to avoid, so it belongs in the same read-only pass.
    """
    uns = read_uns(f)
    if uns is None:
        return None
    if PROVENANCE_KEY in uns and read_group(uns, PROVENANCE_KEY) is None:
        return (
            f"uns[{PROVENANCE_KEY!r}] is a value, not a group — the edit log is written inside it, so this "
            f"file cannot record the write"
        )
    return None


def _link_problem(node: h5py.Group, segment: str, field: tuple[str, ...], depth: int) -> str | None:
    """Refuse a member that is an HDF5 link, external or soft.

    h5py resolves both transparently — ``get`` returns the target, and the
    ``isinstance`` checks in :func:`_resolve` are True for it — so nothing else
    in the walk can tell a link from a real member. Both were verified to
    redirect a write, and neither is caught by anything else:

    * **External**: HDF5 propagates the parent's access flags to the target, so
      under the snapshot's ``"a"`` mode the foreign file is opened read-write
      and the assignment lands *there*. The tool reported success, the snapshot
      stayed byte-identical, and another h5ad was silently modified.
    * **Soft**: the target is elsewhere in *this* file, so the
      ``leaf.file.filename`` backstop cannot see it, and
      :func:`_namespace_problem` cannot either — it matches ``field[0]`` as a
      string, and a link never presents the string it resolves to. A soft link
      from a producer namespace to ``uns['title']`` wrote an HCA schema field
      through this tool, bypassing the registry refusal and ``set_uns``'s
      validation entirely.

    The read-back cannot substitute for this: it re-resolves through the same
    link and sees exactly what it wrote. So the refusal happens here, before
    the link is followed. Scanned the eight real breast objects — 1,443 ``uns``
    members, not one link of either kind — so nothing legitimate is lost.
    """
    link = node.get(segment, getlink=True)
    if isinstance(link, h5py.ExternalLink):
        return (
            f"{_display(field[: depth + 1])} is an external link into {link.filename!r} — writing through it "
            f"would modify that file instead of this one, leaving no record in either"
        )
    if isinstance(link, h5py.SoftLink):
        return (
            f"{_display(field[: depth + 1])} is a soft link to {link.path!r} — the guards here check the path "
            f"you named, so writing through it would edit something you did not name"
        )
    return None


def _resolve(f: h5py.File, field: tuple[str, ...]) -> tuple[h5py.Dataset | None, str]:
    """The scalar dataset ``field`` names, or the reason it cannot be reached.

    The message is empty exactly when a dataset is returned, so a caller
    that checks the dataset never has to invent a fallback string.

    Overwrite-only: every segment must already exist. Every target of a
    producer's correction does, so nothing is lost — and it means a misspelled
    segment is an error rather than a silently created key, which is the
    typo protection the schema registry gives ``set_uns`` and this tool,
    by definition, cannot have.

    Every step is also checked for an HDF5 link, including the leaf: the files
    this runs on come from third-party producers and from CAP, so the structure
    being walked is not ours.
    """
    node: h5py.Group | None = read_uns(f)
    if node is None:
        return None, f"the file has no uns group, so {_display(field)} cannot be reached"

    for depth, segment in enumerate(field[:-1]):
        if problem := _link_problem(node, segment, field, depth):
            return None, problem
        child = node.get(segment)
        if child is None:
            return None, f"{_display(field[: depth + 1])} does not exist (reaching {_display(field)})"
        if not isinstance(child, h5py.Group):
            return None, f"{_display(field[: depth + 1])} is a value, not a group, so {_display(field)} has no parent"
        node = child

    if problem := _link_problem(node, field[-1], field, len(field) - 1):
        return None, problem
    leaf = node.get(field[-1])
    if leaf is None:
        return None, f"{_display(field)} does not exist — this tool overwrites existing fields, it does not create them"
    if isinstance(leaf, h5py.Group):
        return None, f"{_display(field)} is a group, not a value"
    if not isinstance(leaf, h5py.Dataset):
        return None, f"{_display(field)} is neither a group nor a value ({type(leaf).__name__})"
    if leaf.shape != ():
        return None, (
            f"{_display(field)} holds an array of shape {leaf.shape}, not a scalar — "
            f"this tool writes scalar values only"
        )
    # Belt and braces over the per-segment check above: whatever mechanism got
    # us here, the node we are about to write must live in the file we opened.
    if leaf.file.filename != f.filename:
        return None, (
            f"{_display(field)} resolves into {leaf.file.filename!r}, not the file being edited — refusing to "
            f"write outside it"
        )
    return leaf, ""


def _as_dtype(value: Any, dtype: np.dtype, disp: str) -> tuple[Any, str | None]:
    """``value`` put through ``dtype``, or why it does not fit.

    Shared by the int and float branches, which differ in what they do with
    the result — the int branch demands it round-trip exactly, the float
    branch accepts the precision the dtype has.
    """
    try:
        # The cast is the probe, so its overflow warning is expected output,
        # not a problem to surface — the caller checks the result instead.
        with np.errstate(over="ignore", invalid="ignore"):
            coerced = np.asarray(value, dtype=dtype)
    except (OverflowError, ValueError, TypeError) as e:
        return None, f"{disp} has dtype {dtype} and cannot hold {value!r}: {e}"
    return make_serializable(coerced[()]), None


def _coerce(ds: h5py.Dataset, value: Any, disp: str) -> tuple[Any, str | None]:
    """The value to assign and expect on read-back, or why the type is wrong.

    The stored dtype is the contract. Writing ``False`` into a string field
    would store ``'false'`` and pass every downstream check, because a
    producer-owned field has no schema to violate — that silent mis-write is
    the whole reason this tool exists.
    """
    dtype = ds.dtype
    string_info = h5py.check_string_dtype(dtype)
    if string_info is not None:
        # Refused as a dtype, not case by case. anndata writes every string as
        # variable-length; a fixed-length one means the field was written by
        # something else, and supporting it would mean owning two hazards it
        # brings with it — HDF5 truncates an over-long value on assignment with
        # no error at all, and h5py reports these as ascii, so a non-ASCII
        # value raises out of the type check instead of being refused by it.
        # Scanned the eight real breast objects: 1,244 scalar uns datasets,
        # 1,041 of them strings, and not one is fixed-length. Nothing to gain.
        if string_info.length is not None:
            return None, (
                f"{disp} is a fixed-length string ({dtype}) — anndata writes strings as variable-length, "
                f"so this field was not written by anndata and HDF5 would truncate an over-long value "
                f"into it without reporting anything"
            )
        if not isinstance(value, str):
            return None, f"{disp} holds a string; got {type(value).__name__}"
        return value, None

    kind = dtype.kind
    # bool before int, always: isinstance(True, int) is True in Python, so an
    # int branch reached first would accept True and store it as 1.
    if kind == "b":
        if not isinstance(value, bool):
            return None, f"{disp} holds a boolean; got {type(value).__name__}"
        return value, None
    if kind in "iu":
        if isinstance(value, bool) or not isinstance(value, int):
            return None, f"{disp} holds an integer; got {type(value).__name__}"
        # Range, not just type: an out-of-bounds int either raises in _as_dtype
        # or wraps silently depending on the numpy version, and a wrapped value
        # is a wrong value that nothing downstream would question — so the
        # coerced result has to come back equal, not merely exist.
        stored, problem = _as_dtype(value, dtype, disp)
        if problem:
            return None, problem
        if stored != value:
            return None, f"{disp} has dtype {dtype}, which would store {value!r} as {stored!r}"
        return stored, None
    if kind == "f":
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None, f"{disp} holds a float; got {type(value).__name__}"
        # Non-finite is refused at both ends, and for two reasons that compound.
        # A wrong value: nan and inf mean nothing as a provenance scalar, and
        # 1e40 into a float32 silently becomes inf rather than the number asked
        # for. And an unreadable file: json.dumps writes them as the bare tokens
        # NaN and Infinity, which RFC 8259 does not allow — that entry would
        # make the file's *whole* edit_history unparseable to a strict reader,
        # including every entry written by every other tool. nan also defeats
        # the read-back by construction, since nan != nan.
        if not math.isfinite(value):
            return None, f"{disp}: {value!r} is not a finite number"
        # Int accepted as a widening: JSON has one number type, so a whole
        # float arrives as an int. Precision loss on a narrow float dtype is
        # allowed rather than refused — every float32 field would otherwise
        # reject most decimals — so the value that lands is the coerced one.
        stored, problem = _as_dtype(value, dtype, disp)
        if problem:
            return None, problem
        if not math.isfinite(stored):
            return None, f"{disp} has dtype {dtype}, which cannot hold {value!r} — it would overflow to {stored!r}"
        return stored, None

    return None, (
        f"{disp} has dtype {dtype}, which this tool cannot write — it writes string, boolean, integer and float scalars"
    )


def _plan(f: h5py.File, parsed: list[tuple[tuple[str, ...], Any]]) -> tuple[list[_PlannedWrite], list[str]]:
    """Validate every requested write against the source file.

    Runs to completion rather than short-circuiting: a caller who named one
    missing path and mistyped another value should learn both at once.
    """
    plans: list[_PlannedWrite] = []
    problems: list[str] = []
    for field, value in parsed:
        if problem := _namespace_problem(field):
            problems.append(problem)
            continue
        ds, problem = _resolve(f, field)
        if ds is None:
            problems.append(problem)
            continue
        expected, problem = _coerce(ds, value, _display(field))
        if problem:
            problems.append(problem)
            continue
        plans.append(
            _PlannedWrite(
                field=field,
                expected=expected,
                old_value=make_serializable(ds[()]),
                dtype=ds.dtype,
            )
        )
    return plans, problems


def set_producer_uns(path: str, updates: list[dict]) -> dict:
    """Overwrite scalar values at nested ``uns`` paths outside the HCA schema.

    All-or-nothing: every requested write is validated against the file before
    anything is copied, and the file is left untouched if any check fails.
    The whole batch then lands in one snapshot with one edit-log entry, which
    matters when the alternative is one full rewrite per field on a file of
    tens of gigabytes.

    Addresses by path segments (``["ihbca_provenance", "git_dirty"]``) rather
    than a slash-joined string, because ``/`` is how h5py spells a link path:
    a string form would make the checks and the walk capable of disagreeing
    about what was addressed.

    Values are assigned in place, which is what preserves the stored dtype and
    the ``encoding-type`` attrs anndata reads. Each write is read back and
    compared — value and dtype — before the snapshot is accepted, so a write
    that did not land the way it was asked for never becomes the latest
    version.

    Refuses a path that does not exist (it overwrites, it never creates), a
    value whose type does not match the stored dtype, a non-finite float, a
    fixed-length string field, an external link into another file, a
    non-scalar or group-valued target, a segment containing ``/``, our own
    ``provenance`` namespace, and any HCA schema field — those belong to ``set_uns``, which
    validates them. Whether the *result* is valid is ``validate_schema``'s
    verdict, not this tool's (#614) — though note that for a producer-owned
    namespace it will not have one, which is why the guards above are stricter
    than a schema-backed tool's would need to be.

    Args:
        path: Path to an .h5ad file. Auto-resolves to the latest timestamped
            edit snapshot before operating.
        updates: Entries of ``{"field": [segment, ...], "value": scalar}``.
            Each field must already exist and hold a scalar string, boolean,
            integer or float.

    Returns:
        Dict with ``output_path``, ``fields_written`` and ``updates`` (each
        with ``field``, ``old_value``, ``new_value`` and ``dtype``), or
        ``{"error": ...}``.
    """
    try:
        # MCP-exposed, so the arguments arrive as decoded JSON; checked before
        # resolve_latest, which does path arithmetic on it.
        if not isinstance(path, str):
            return {"error": f"path must be a string, got {type(path).__name__}"}
        path = resolve_latest(path)
        if not Path(path).is_file():
            return {"error": f"File not found: {path}"}

        parsed, problems = _parse_updates(updates)

        plans: list[_PlannedWrite] = []
        raw_log: str = "[]"
        if not problems:
            with h5py.File(path, "r") as f_in:
                plans, problems = _plan(f_in, parsed)
                if problem := _edit_log_target_problem(f_in):
                    problems.append(problem)
                # Read here, not from the snapshot: a corrupt log is a refusal,
                # and refusing it now costs a metadata read rather than a full
                # copy of a file that can run to tens of gigabytes (#597).
                raw_log = read_edit_log_h5py(f_in)
        if problems:
            return {"error": "Refusing to write: " + "; ".join(problems)}
        parsed_log = parse_edit_log(raw_log)
        if "error" in parsed_log:
            return parsed_log

        records = [
            {
                "field": list(p.field),
                "old_value": p.old_value,
                "new_value": p.expected,
                "dtype": str(p.dtype),
            }
            for p in plans
        ]

        with (
            snapshot_copy_hashed(path) as (output_path, source_sha256),
            h5py.File(output_path, "a") as f_out,
        ):
            for plan in plans:
                # Re-resolved in the snapshot rather than trusting the source
                # walk: the copy is byte-identical, so a failure here means the
                # copy is not what we validated, and shipping it would be worse
                # than raising.
                ds, problem = _resolve(f_out, plan.field)
                if ds is None:
                    raise RuntimeError(f"snapshot does not match the validated source: {problem}")
                ds[()] = plan.expected

            entry = make_edit_entry(
                operation="set_producer_uns",
                description=(
                    f"Set {len(plans)} producer uns field(s): "
                    + ", ".join(f"{_display(p.field)} {p.old_value!r} -> {p.expected!r}" for p in plans)
                ),
                details={"fields": records},
            )
            log_result = build_edit_log(raw_log, [entry], path, source_sha256)
            if "error" in log_result:
                raise RuntimeError(log_result["error"])
            write_edit_log_h5py(f_out, log_result["json"])

            # Read back before the snapshot is accepted. Value *and* dtype:
            # checking the value alone is what lets a bool-written-as-a-string
            # through, and this namespace has no validator behind it.
            #
            # A second pass, deliberately, not a check folded into the write
            # loop above: two distinct paths can name one dataset through an
            # HDF5 hard link, and only a pass that runs after every write
            # catches the second write clobbering the first. Duplicate *paths*
            # are already refused; aliases are not detectable up front.
            for plan in plans:
                ds, problem = _resolve(f_out, plan.field)
                if ds is None:
                    raise RuntimeError(f"{_display(plan.field)} vanished during the write: {problem}")
                stored = make_serializable(ds[()])
                if stored != plan.expected:
                    raise RuntimeError(f"{_display(plan.field)} read back as {stored!r}, expected {plan.expected!r}")
                if ds.dtype != plan.dtype:
                    raise RuntimeError(
                        f"{_display(plan.field)} changed dtype from {plan.dtype} to {ds.dtype} during the write"
                    )

        cleanup_previous_version(path, output_path)

        return {
            "output_path": output_path,
            "fields_written": len(plans),
            "updates": records,
        }

    except Exception as e:
        return {"error": str(e)}
