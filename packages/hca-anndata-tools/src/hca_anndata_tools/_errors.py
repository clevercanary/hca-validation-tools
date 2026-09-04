"""Report an exception nobody decided, whole rather than summarized.

Contract principle 15: a semantic refusal is a ``return`` and carries no
traceback because no exception exists to withhold one. An exception that
reaches a tool's broad ``except`` is something that happened to us — a full
disk mid-write, a bug of ours — and summarizing it to ``str(e)`` destroys the
only thing that would explain it.

A *load* failure is not one of them: ``gate_h5ad_paths`` opens every path
before the tool body runs and returns anndata's message verbatim, which
principle 11 makes deliberate. Those never reach a broad handler at all.
"""

from __future__ import annotations

import traceback

__all__ = ["Refusal", "describe_exception", "failure_result", "require_positive_int"]


class Refusal(ValueError):
    """A decision we made, raised instead of returned.

    Principle 15 draws the line by *origin*, not by mechanism: a refusal is
    ours whether it left the function as ``return {"error": ...}`` or came up
    the stack from a shared reader. The ones that travel by the stack need a
    type, because a handler cannot otherwise tell "the index has a null and
    cannot be joined on" — which we wrote, and which names its own remedy —
    from an exception that means our code is broken.

    Subclasses ``ValueError`` because that is what these sites raised before
    the type existed, so any caller already catching ``ValueError`` keeps
    working. The two mutating-write refusals were ``RuntimeError``; nothing
    catches them by type, checked at the time of the change.
    """


# Frames kept per traceback, counted from the raising end. Negative because
# that is how the stdlib asks for the *last* n rather than the first: the
# frames nearest the raise are the ones that name the element, and the
# outermost frames are our own call chain, which the reader already knows.
_FRAME_LIMIT = -12

# Total characters kept. The frame limit alone is not a bound: it applies to
# each traceback in a chain independently, so k chained exceptions yield up
# to k * 12 frames. This caps the whole report, chain included, so one
# failure cannot fill an MCP caller's context.
_MAX_CHARS = 4000

_TRUNCATION_NOTE = "[traceback truncated: kept the frames nearest the raise]\n"

# The summary is capped separately, and far shorter: it is the line an MCP
# client renders. Third-party messages are not bounded and not single-line —
# pandas and anndata both emit multi-line reprs — so neither property holds
# without enforcing it here. Nothing is lost: the untruncated message is the
# last line of the traceback beside it.
_MAX_SUMMARY_CHARS = 300


def describe_exception(exc: BaseException) -> tuple[str, str]:
    """Split a caught exception into a one-line summary and its traceback.

    Returns ``(error, traceback)``. They travel under separate keys rather
    than concatenated: an MCP client renders the summary, so it stays one
    line, while the frames sit beside it for an agent that can use them.
    Folding the stack into the summary would serve neither reader.

    The summary leads with the exception type. ``str(e)`` alone loses it, and
    a bare "Can't implicitly convert non-string objects to strings" does not
    even reveal whether the caller is looking at a write failure or a read
    one (hca-validation-tools#668).

    The traceback is bounded twice — per traceback, then over the whole
    report; see the module constants. Both trim the same end: frames are kept
    from the raise outward, because that is the end that names what failed,
    so truncation drops our own outer call chain first.
    """
    # split()/join collapses embedded newlines, so "one line" is true of the
    # value and not merely of the common case.
    summary = " ".join(f"{type(exc).__name__}: {exc}".split())
    if len(summary) > _MAX_SUMMARY_CHARS:
        summary = summary[: _MAX_SUMMARY_CHARS - 1] + "…"
    formatted = "".join(traceback.format_exception(exc, limit=_FRAME_LIMIT))
    if len(formatted) > _MAX_CHARS:
        # Keep the tail: with a chain, the exception raised last is printed
        # last, and it is the one the caller saw.
        formatted = _TRUNCATION_NOTE + formatted[-_MAX_CHARS:]
    return summary, formatted


def require_positive_int(name: str, value: object) -> None:
    """Refuse, by ``name``, a tool knob that is not a positive int.

    The one wording every knob (``chunk_nnz``, ``sample_size``) refuses
    with, raised as :class:`Refusal` so :func:`failure_result` returns it as
    ``{"error": ...}`` with no traceback. ``bool`` is rejected explicitly:
    ``isinstance(True, int)`` holds, and a knob set to ``True`` meaning ``1``
    is a mistake, not a request.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise Refusal(f"{name} must be a positive int, got {value!r}")


def failure_result(exc: Exception) -> dict[str, str]:
    """The error dict a tool's broad ``except`` should return.

    The classification lives here rather than at each handler because there
    are 28 of them (#657 sweeps the rest), and "is this ours?" answered
    per-site is answered wrong eventually — silently, since a refusal that
    grows a traceback still reads as an error and every existing test asserts
    on substrings.
    """
    if isinstance(exc, Refusal):
        return {"error": str(exc)}
    summary, tb = describe_exception(exc)
    return {"error": summary, "traceback": tb}
