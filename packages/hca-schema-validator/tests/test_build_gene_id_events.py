"""Tests for the Ensembl gene id event generator.

The generator is run by hand and its output is committed, so a defect in it
reaches the package as a binary whose diff reads only as "122 KB changed".
Nothing downstream could tell a wrong table from a right one, which is why the
refusals below matter more than they would in code that fails loudly.

Only the pure functions are covered: the parts that talk to Ensembl need the
network and the driver, and are exercised by actually regenerating the table.
"""

from __future__ import annotations

import pytest

from ._generators import load_script

gen = load_script("build_gene_id_events")


# --- check_sessions --------------------------------------------------------


def test_contiguous_chain_has_no_gaps():
    assert gen.check_sessions([(76, 77), (77, 78), (78, 79)], (76, 79)) == []


def test_gap_is_reported_not_refused():
    """Ensembl skips a session when no gene build happened, which is not an error.

    Ten of the thirty GRCh38 sessions are missing for this reason, so refusing
    here would make the table unbuildable rather than wrong.
    """
    assert gen.check_sessions([(76, 77), (78, 79)], (76, 79)) == [(77, 78)]


def test_several_missing_sessions_are_one_gap():
    """r85->r87 skips two sessions and is still a single stretch to account for."""
    assert gen.check_sessions([(84, 85), (87, 88)], (84, 88)) == [(85, 87)]


def test_a_missing_trailing_session_is_a_gap():
    """A release published before its mapping session would otherwise lose every
    event in it, invisibly: the chain itself looks continuous."""
    assert gen.check_sessions([(76, 77), (77, 78)], (76, 80)) == [(78, 80)]


def test_a_missing_leading_session_is_a_gap():
    assert gen.check_sessions([(80, 81)], (76, 81)) == [(76, 80)]


def test_duplicate_session_is_refused():
    """A repeated session double-counts its rows, which turns a rename into a merge."""
    with pytest.raises(SystemExit, match="more than once"):
        gen.check_sessions([(76, 77), (76, 77), (77, 78)], (76, 78))


def test_no_sessions_is_refused():
    with pytest.raises(SystemExit, match="no GRCh38-to-GRCh38 mapping session"):
        gen.check_sessions([], (76, 116))


# --- check_gap_builds ------------------------------------------------------


def test_gap_without_a_gene_build_is_accepted():
    """The same build on both sides means there was nothing to map across the gap."""
    gen.check_gap_builds([(77, 78)], {77: "2014-08", 78: "2014-08"})


def test_gap_containing_a_gene_build_is_refused():
    """A build inside a gap means a session is missing, and with it every event in it."""
    with pytest.raises(SystemExit, match="different times"):
        gen.check_gap_builds([(77, 78)], {77: "2014-08", 78: "2015-01"})


def test_gap_is_refused_when_the_build_is_unrecorded():
    """Without the key there is no evidence either way, and silence would invent some."""
    with pytest.raises(SystemExit, match="does not record genebuild"):
        gen.check_gap_builds([(77, 78)], {77: "2014-08", 78: None})


def test_every_gap_is_checked_not_just_the_first():
    with pytest.raises(SystemExit, match=r"r79 to r80"):
        gen.check_gap_builds(
            [(77, 78), (79, 80)],
            {77: "2014-08", 78: "2014-08", 79: "2015-01", 80: "2015-06"},
        )


# --- classify --------------------------------------------------------------


def test_no_successor_is_retired():
    assert gen.classify({"A": set()}) == {"A": "retired"}


def test_sole_claimant_is_renamed():
    assert gen.classify({"A": {"X"}}) == {"A": "renamed"}


def test_shared_successor_is_merged():
    """Merge-ness is a property of the successor, so both olds are named by it."""
    assert gen.classify({"A": {"X"}, "B": {"X"}}) == {"A": "merged", "B": "merged"}


def test_several_successors_is_split():
    assert gen.classify({"A": {"X", "Y"}}) == {"A": "split"}


def test_a_split_piece_is_not_called_a_merge():
    """A gene that became several is split, even where one piece is shared.

    Calling the shared piece a merge would invite a curator to sum two columns
    that hold different parts of a locus.
    """
    events = gen.classify({"A": {"X", "Y"}, "B": {"Y"}})
    assert events["A"] == "split"
    assert events["B"] == "merged"


# --- latest_events ---------------------------------------------------------


def test_the_newest_session_is_the_one_that_counts():
    """Renamed at r90, then the result retired at r100: only the last word stands."""
    latest = gen.latest_events([("A", "B", 90, 91), ("A", None, 99, 100)])
    assert latest == {"A": (99, set())}


def test_successors_within_one_session_are_collected():
    latest = gen.latest_events([("A", "X", 100, 101), ("A", "Y", 100, 101)])
    assert latest == {"A": (100, {"X", "Y"})}


def test_an_older_session_does_not_contribute_successors():
    latest = gen.latest_events([("A", "X", 90, 91), ("A", "Y", 100, 101)])
    assert latest == {"A": (100, {"Y"})}


def test_old_release_is_the_last_release_the_gene_existed_in():
    """Coordinates come from this release, so it must be the session's old side."""
    ((release, _),) = gen.latest_events([("A", None, 112, 113)]).values()
    assert release == 112


# --- build_rows ------------------------------------------------------------


def test_a_retirement_is_one_row_with_an_empty_successor():
    rows = gen.build_rows(
        {"A": "retired"},
        {"A": set()},
        {"A": 113},
        {("A", 113): ("7", 100, 200, 1)},
        {},
    )
    assert rows == [["A", "", "retired", "7", 100, 200, 1, 113, "", "", "", ""]]


def test_a_split_is_one_row_per_successor():
    rows = gen.build_rows(
        {"A": "split"},
        {"A": {"Y", "X"}},
        {"A": 100},
        {("A", 100): ("18", 10, 20, -1)},
        {"X": ("18", 10, 15, -1), "Y": ("18", 16, 20, -1)},
    )
    assert [row[1] for row in rows] == ["X", "Y"]
    assert rows[0] == ["A", "X", "split", "18", 10, 20, -1, 100, "18", 10, 15, -1]


def test_a_successor_absent_from_the_current_release_has_empty_coordinates():
    """42 successors have been retired themselves, so there is no span to give."""
    rows = gen.build_rows({"A": "renamed"}, {"A": {"X"}}, {"A": 100}, {}, {})
    assert rows == [["A", "X", "renamed", "", "", "", "", 100, "", "", "", ""]]


def test_rows_are_ordered_by_identifier():
    """A stable order keeps the committed artifact's bytes reproducible."""
    rows = gen.build_rows(
        {"B": "retired", "A": "retired"},
        {"A": set(), "B": set()},
        {"A": 100, "B": 100},
        {},
        {},
    )
    assert [row[0] for row in rows] == ["A", "B"]


def test_coordinates_are_keyed_by_release_as_well_as_gene():
    """The same identifier means a different span in a different release."""
    rows = gen.build_rows(
        {"A": "retired"},
        {"A": set()},
        {"A": 113},
        {("A", 100): ("7", 1, 2, 1)},
        {},
    )
    assert rows[0][3:7] == ["", "", "", ""]


# --- sessions_and_events, through a stand-in connection ----------------------


class _FakeCursor:
    """Answers the two queries sessions_and_events makes, in order."""

    def __init__(self, sessions, events):
        self._answers = [sessions, events]
        self._rows = []

    def execute(self, sql, params=None):
        self._rows = self._answers.pop(0)

    def fetchall(self):
        return self._rows


class _FakeConnection:
    def __init__(self, sessions, events):
        self._cursor = _FakeCursor(sessions, events)

    def select_db(self, name):
        pass

    def cursor(self):
        return self._cursor


def test_sessions_and_events_runs_end_to_end():
    """The network path, driven without the network.

    A round of review changed check_sessions's signature and updated every call
    but the one inside this function; the pure-function tests passed and every
    real run raised TypeError after its first query. This is the call they did
    not reach.
    """
    con = _FakeConnection(
        sessions=[("76", "77"), ("77", "78")],
        events=[("ENSG1", "ENSG2", "76", "77"), ("ENSG3", None, "77", "78")],
    )
    sessions, gaps, events = gen.sessions_and_events(con, 78, (76, 78))
    assert sessions == [(76, 77), (77, 78)]
    assert gaps == []
    assert events == [("ENSG1", "ENSG2", 76, 77), ("ENSG3", None, 77, 78)]
