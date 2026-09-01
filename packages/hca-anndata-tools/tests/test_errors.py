"""The broad handler's report: bounded, serializable, chain intact (#669)."""

import pytest

from hca_anndata_tools._errors import (
    _MAX_CHARS,
    _MAX_SUMMARY_CHARS,
    _TRUNCATION_NOTE,
    Refusal,
    describe_exception,
    failure_result,
)
from hca_anndata_tools.guards import GuardRefusal
from hca_anndata_tools.write import MissingLineageRootError, SameSecondSnapshotError


def test_summary_leads_with_the_exception_type():
    """Pins the type prefix the function docstring argues for (#668)."""
    with pytest.raises(ValueError) as excinfo:
        raise ValueError("no conversion path")

    error, _ = describe_exception(excinfo.value)
    assert error == "ValueError: no conversion path"


def test_traceback_names_the_raising_frame():
    """Pins the frames that ``str(e)`` discarded: what raised, and where."""

    def inner_frame_with_a_distinctive_name():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError) as excinfo:
        inner_frame_with_a_distinctive_name()

    _, tb = describe_exception(excinfo.value)
    assert "inner_frame_with_a_distinctive_name" in tb
    assert "test_errors.py" in tb


def test_the_chain_survives():
    """Principle 15 says *chained* and tracebacked.

    The cause is where the explanation usually is: a wrapper's own message is
    rarely the one that identifies the element.
    """
    with pytest.raises(RuntimeError) as excinfo:
        try:
            raise ValueError("the underlying cause")
        except ValueError as cause:
            raise RuntimeError("the wrapper") from cause

    _, tb = describe_exception(excinfo.value)
    assert "the underlying cause" in tb
    assert "the wrapper" in tb


def test_a_deep_chain_stays_bounded():
    """Pins the chain case the ``_MAX_CHARS`` comment names.

    40 links is not arbitrary: at 20 the report is still under the cap, so
    the truncation assertion below would pass vacuously.
    """

    def deep(n):
        if n:
            return deep(n - 1)
        raise ValueError("bottom")

    exc = None
    for i in range(40):
        try:
            if exc is None:
                deep(60)
            else:
                raise RuntimeError(f"link {i}") from exc
        except Exception as e:
            exc = e

    assert exc is not None
    _, tb = describe_exception(exc)
    assert len(tb) <= _MAX_CHARS + len(_TRUNCATION_NOTE)
    assert _TRUNCATION_NOTE in tb


def test_the_summary_is_one_line_and_bounded():
    """The summary is the line an MCP client renders, so both must hold.

    Third-party messages guarantee neither: pandas and anndata emit
    multi-line reprs, and h5py embeds whole array reprs. Nothing is lost by
    capping — the full message is the traceback's last line.
    """
    with pytest.raises(ValueError) as excinfo:
        raise ValueError("first\nsecond\nthird")

    error, _ = describe_exception(excinfo.value)
    assert error == "ValueError: first second third"

    with pytest.raises(ValueError) as excinfo:
        raise ValueError("x" * 20000)

    error, tb = describe_exception(excinfo.value)
    assert len(error) <= _MAX_SUMMARY_CHARS
    assert error.endswith("…")
    # The untruncated message is still recoverable beside it.
    assert "x" * 500 in tb


# --- who owns the failure decides the shape (#669) --------------------------


def test_a_refusal_is_reported_without_frames():
    """Ours: the message already names its subject and its remedy."""
    with pytest.raises(Refusal) as excinfo:
        raise Refusal("obs index has a null and cannot be joined on")

    assert failure_result(excinfo.value) == {"error": "obs index has a null and cannot be joined on"}


def test_a_plain_valueerror_still_gets_frames():
    """The discriminating case, because ``Refusal`` subclasses ``ValueError``.

    If the check were ``isinstance(exc, ValueError)`` every numeric parse bug
    in the package would silently lose its traceback, and no test asserting
    on substrings would notice.
    """
    with pytest.raises(ValueError) as excinfo:
        raise ValueError("not ours")

    result = failure_result(excinfo.value)
    assert result["error"] == "ValueError: not ours"
    assert "traceback" in result


def test_every_guard_and_write_refusal_is_a_refusal():
    """The roster, so a new refusal type cannot quietly skip the carve-out."""
    assert issubclass(GuardRefusal, Refusal)
    assert issubclass(SameSecondSnapshotError, Refusal)
    assert issubclass(MissingLineageRootError, Refusal)
