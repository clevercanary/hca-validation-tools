"""Build the retired-gene-id event table that check_retired_feature_ids reads.

Run by hand; the output is committed. Refresh when a new Ensembl release lands.

    uv run --no-project --with pymysql python scripts/build_gene_id_events.py

A retired Ensembl identifier is a warning here and an error at CELLxGENE, so
every atlas heading for CZI has to clear them -- but the warnings alone say
nothing about what to do next. Ensembl records what became of each identifier in
``stable_id_event``, which is what this table ships.

Sessions are selected by ``mapping_session``'s own assembly columns rather than
by release number, so the GRCh37->GRCh38 boundary session (75->76) is excluded by
construction: its old coordinates are on a different assembly and are not
comparable to the new ones. Measured against r116, that leaves 30 sessions
covering r76-r116.

``score`` is deliberately not read. Of the gene events carrying a successor since
r98, 1,202 fall in 0.9-0.999 and 2 sit at exactly 1.0, so a threshold in that
band separates nothing; and the column is ``float NOT NULL DEFAULT '0'``, so an
exact zero cannot be told apart from "never scored" -- precisely the rows one
would want to treat as suspicious. A number uninformative where it is dense and
unexplainable where it is sparse does not belong in a curator-facing artifact.

Chains are not resolved here. Ensembl may replace A with B and later B with C,
and a curator following only the first hop lands on an identifier CELLxGENE
still rejects. Every hop is a row in this table, so the consumer walks them;
keeping the table a transcription of Ensembl's bookkeeping means every row can
be checked against the server it came from.
"""

from __future__ import annotations

import argparse
import itertools
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from _ensembl import HOST, connect, core_db, list_releases, require_driver, write_csv_gz

# The assembly both sides of a session must name. Anything else describes a
# change between genomes rather than within one, and its coordinates cannot be
# compared across the event.
ASSEMBLY_NAME = "GRCh38"
DEFAULT_OUT = (
    Path(__file__).resolve().parent.parent
    / "packages/hca-schema-validator/src/hca_schema_validator/gene_id_events.csv.gz"
)
FIELDS = [
    "old_id",
    "new_id",
    "event",
    "old_chrom",
    "old_start",
    "old_end",
    "old_strand",
    "old_release",
    "new_chrom",
    "new_start",
    "new_end",
    "new_strand",
]


def check_sessions(sessions: list[tuple[int, int]], covered: tuple[int, int]) -> list[tuple[int, int]]:
    """Refuse a duplicated session, and report where the chain jumps.

    ``sessions`` is (old_release, new_release) pairs, sorted; ``covered`` is the
    (first, last) release the server serves a core database for. Returns the gaps
    as (last_release_before, first_release_after) pairs, for check_gap_builds to
    account for -- including the two at the ends, where a missing session is
    invisible in the chain itself. A release published before its mapping session
    would otherwise have every event in it silently omitted. Both failures are
    invisible in the committed artifact, which is a binary whose diff reads only
    as "a few hundred KB changed".

    A repeated session double-counts its events. Cardinality is what ``event``
    is derived from, so a duplicated row turns a rename into a merge: two
    identical old->new rows look exactly like two old identifiers arriving at
    one new gene.

    A gap is not refused here, because the chain is legitimately not contiguous:
    Ensembl creates a mapping session when the gene set is rebuilt, and in the
    early GRCh38 range releases came out faster than gene builds did. Ten of the
    thirty sessions between r76 and r116 are missing for that reason -- r78 ships
    r77's gene set unchanged, down to every stable id, version and span -- and
    r78's own database records no 77->78 session either, so there is nothing the
    current archive could have pruned. What matters is not that a gap exists but
    whether a gene build happened inside it, which check_gap_builds decides.
    """
    if not sessions:
        raise SystemExit(f"archive served no {ASSEMBLY_NAME}-to-{ASSEMBLY_NAME} mapping session")
    seen = set()
    for pair in sessions:
        if pair in seen:
            raise SystemExit(
                f"archive listed session r{pair[0]}->r{pair[1]} more than once; refusing to build a "
                f"table whose event classes would be derived from double-counted rows"
            )
        seen.add(pair)
    gaps = [(new, nxt_old) for (_, new), (nxt_old, _) in itertools.pairwise(sessions) if new != nxt_old]
    # The two the chain cannot show: a release served before its mapping session
    # exists, at either end, leaves the chain looking continuous while every event
    # in that release is missing.
    first, last = covered
    if sessions[0][0] > first:
        gaps.insert(0, (first, sessions[0][0]))
    if sessions[-1][1] < last:
        gaps.append((sessions[-1][1], last))
    return gaps


def check_gap_builds(gaps: list[tuple[int, int]], builds: dict[int, str | None]) -> None:
    """Refuse a gap in the session chain that a gene build happened inside.

    ``builds`` maps a release to its ``genebuild.last_geneset_update``. A session
    exists because the gene set was rebuilt, so the two statements "no session
    here" and "no rebuild here" are the same one, and the key is Ensembl's own
    record of it. Measured across r76-r116: identical on all ten gaps, different
    on every transition that does have a session.

    A gap whose sides were built from different gene sets means a session really
    is missing from the archive. Every identifier changed across it would then be
    absent from the table -- reported as unclassified, or worse, read from an
    older event that has since been superseded, naming a successor that is no
    longer the answer.

    Compared rather than counted, because a stretch that lost one gene and gained
    another is the same size on both sides and would pass a count comparison.

    An absent key is refused rather than worked around: it is the evidence this
    check rests on, every release in the covered range has it, and the script is
    run by hand with someone there to look.
    """
    for before, after in gaps:
        missing = [r for r in (before, after) if not builds.get(r)]
        if missing:
            raise SystemExit(
                f"r{', r'.join(str(r) for r in missing)} does not record genebuild.last_geneset_update, "
                f"so the gap r{before}->r{after} in the session chain cannot be accounted for; refusing "
                f"to build a table that may silently omit the identifiers changed in it"
            )
        if builds[before] != builds[after]:
            raise SystemExit(
                f"the session chain jumps from r{before} to r{after}, and their gene sets were built at "
                f"different times ({builds[before]} and {builds[after]}); refusing to build a table that "
                f"would silently omit every identifier changed in between"
            )


def classify(successors_by_old: dict[str, set[str]]) -> dict[str, str]:
    """Name each retired identifier's event from cardinality alone.

    Nothing is inferred beyond counting, so every class is a statement about
    Ensembl's own bookkeeping that a curator can go and check:

    - retired  -- no successor
    - renamed  -- one successor, which no other identifier names
    - merged   -- one successor, which other identifiers also name
    - split    -- several successors

    A split identifier contributes one row per successor, and each of those rows
    carries ``split`` rather than being re-examined for merge-ness. The old gene
    did not become that successor; it became all of them, and saying "merged" of
    one piece would invite a curator to sum two columns that hold different
    parts of a locus.
    """
    incoming = Counter(new for news in successors_by_old.values() for new in news)

    events = {}
    for old, news in successors_by_old.items():
        if not news:
            events[old] = "retired"
        elif len(news) > 1:
            events[old] = "split"
        else:
            events[old] = "merged" if incoming[next(iter(news))] > 1 else "renamed"
    return events


def latest_events(rows: list[tuple[str, str | None, int, int]]) -> dict[str, tuple[int, set[str]]]:
    """Reduce raw event rows to each identifier's last word, keyed by old id.

    ``rows`` is (old_id, new_id, old_release, new_release). An identifier can
    appear in several sessions -- renamed at r90 and the result retired at r100
    -- and only the newest says what it is now. Returns the old_release of that
    newest session, which is the last release the identifier existed in and so
    the one its coordinates must come from, together with its successors there.

    A ``None`` new_id means retirement and is dropped from the successor set
    rather than carried as a value, so "no successor" is an empty set, not a set
    holding nothing-in-particular.
    """
    newest: dict[str, int] = {}
    for old, _, _, new_release in rows:
        if new_release > newest.get(old, 0):
            newest[old] = new_release

    out: dict[str, tuple[int, set[str]]] = {}
    for old, new, old_release, new_release in rows:
        if new_release != newest[old]:
            continue
        release, news = out.setdefault(old, (old_release, set()))
        if new:
            news.add(new)
        # The same session can only have one old_release, so this is a
        # consistency check rather than a choice between candidates.
        assert release == old_release, f"{old}: session r{new_release} has two old releases"
    return out


def build_rows(
    events: dict[str, str],
    successors_by_old: dict[str, set[str]],
    release_by_old: dict[str, int],
    old_coords: dict[tuple[str, int], tuple[str, int, int, int]],
    new_coords: dict[str, tuple[str, int, int, int]],
) -> list[list]:
    """Assemble the committed rows, one per (retired identifier, successor).

    Coordinates are left empty rather than guessed at when the server does not
    have them: an old identifier its release no longer lists, or a successor
    absent from the current one -- 42 of 1,101 today, every one of them a
    successor that has since been retired itself.
    """
    rows = []
    for old in sorted(events):
        release = release_by_old[old]
        old_span = old_coords.get((old, release), ("", "", "", ""))
        news = sorted(successors_by_old[old]) or [""]
        for new in news:
            new_span = new_coords.get(new, ("", "", "", "")) if new else ("", "", "", "")
            rows.append([old, new, events[old], *old_span, release, *new_span])
    return rows


def newest_release(con) -> int:
    """The newest GRCh38 core database the server serves.

    Read from the archive rather than hardcoded, so the table follows Ensembl
    without an edit here, and so the release the new coordinates come from is a
    measurement rather than an assumption.
    """
    releases = list_releases(con)
    if not releases:
        raise SystemExit(f"no {ASSEMBLY_NAME} core database found on {HOST}")
    return max(releases)


def geneset_build(con, release: int) -> str | None:
    """When the gene set a release ships was last rebuilt, as Ensembl records it."""
    con.select_db(core_db(release))
    cur = con.cursor()
    cur.execute("SELECT meta_value FROM meta WHERE meta_key = 'genebuild.last_geneset_update'")
    row = cur.fetchone()
    return row[0] if row else None


def sessions_and_events(
    con, release: int, covered: tuple[int, int]
) -> tuple[list[tuple[int, int]], list[tuple[int, int]], list[tuple[str, str | None, int, int]]]:
    """Every within-assembly gene change event, with the sessions they came from.

    One query each. ``old_release`` and ``new_release`` are varchar, so they are
    cast before being compared or ordered -- lexically '99' beats '116', which
    is how this table came to be described as stopping at r99.

    Self-mappings are excluded: a row whose new id equals its old one records
    that the identifier survived the session, which is not an event.

    Returns the sessions, the gaps in their chain, and the events.
    """
    con.select_db(core_db(release))
    cur = con.cursor()
    cur.execute(
        """
        SELECT CAST(old_release AS UNSIGNED), CAST(new_release AS UNSIGNED)
        FROM mapping_session
        WHERE old_assembly = %s AND new_assembly = %s
        ORDER BY CAST(old_release AS UNSIGNED)
        """,
        (ASSEMBLY_NAME, ASSEMBLY_NAME),
    )
    sessions = [(int(old), int(new)) for old, new in cur.fetchall()]
    gaps = check_sessions(sessions)

    cur.execute(
        """
        SELECT e.old_stable_id, e.new_stable_id,
               CAST(m.old_release AS UNSIGNED), CAST(m.new_release AS UNSIGNED)
        FROM stable_id_event e
        JOIN mapping_session m USING (mapping_session_id)
        WHERE e.type = 'gene'
          AND m.old_assembly = %s AND m.new_assembly = %s
          AND e.old_stable_id IS NOT NULL
          AND (e.new_stable_id IS NULL OR e.new_stable_id <> e.old_stable_id)
        """,
        (ASSEMBLY_NAME, ASSEMBLY_NAME),
    )
    events = [(old, new, int(old_r), int(new_r)) for old, new, old_r, new_r in cur.fetchall()]
    return sessions, gaps, events


def coords_in(con, release: int, wanted: set[str] | None = None) -> dict[str, tuple[str, int, int, int]]:
    """Spans for the requested genes as one release placed them, or for all of them.

    ``wanted`` is asked for by name rather than fetched and filtered here. The
    sets are small -- a median of 72 identifiers per release and 3,467 at the
    largest -- while a release holds about 86,000 genes, so filtering client-side
    sent 2.5 million rows across thirty releases to keep 7,132 of them.
    ``stable_id`` is indexed, so naming them is also the faster query: measured
    against a slow server, 19-30s for a full scan against 0.2s for 55 identifiers
    and 2.3s for the largest set.

    ``wanted`` of None fetches the release whole, which is what the current
    release needs: the resurrection check asks whether any supposedly retired
    identifier is still listed, and that cannot be answered from a list of the
    identifiers already believed retired.
    """
    con.select_db(core_db(release))
    cur = con.cursor()
    columns = "g.stable_id, sr.name, g.seq_region_start, g.seq_region_end, g.seq_region_strand"
    source = "gene g JOIN seq_region sr ON g.seq_region_id = sr.seq_region_id"
    if wanted is None:
        cur.execute(f"SELECT {columns} FROM {source} WHERE g.stable_id LIKE 'ENSG%%'")
    else:
        # Sorted so the query text for a given set is stable, which keeps a rerun
        # comparable when something has to be debugged against the server.
        names = sorted(wanted)
        placeholders = ", ".join(["%s"] * len(names))
        cur.execute(f"SELECT {columns} FROM {source} WHERE g.stable_id IN ({placeholders})", names)
    return {
        stable_id: (chrom, int(start), int(end), int(strand)) for stable_id, chrom, start, end, strand in cur.fetchall()
    }


def main() -> int:
    require_driver()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    # One connection for the whole run, switched between databases with
    # select_db. Opening one per query cost 0.8s of handshake each, 43s over the
    # 54 the run used to make -- and 54 chances for a four-minute run against a
    # public server to fail partway through.
    con = connect()
    releases = list_releases(con)
    if not releases:
        raise SystemExit(f"no {ASSEMBLY_NAME} core database found on {HOST}")
    current = max(releases)
    print(f"newest {ASSEMBLY_NAME} core database: r{current}", file=sys.stderr)

    t = time.time()
    sessions, gaps, events = sessions_and_events(con, current, (min(releases), current))
    print(
        f"{len(sessions)} {ASSEMBLY_NAME} sessions r{sessions[0][0]}-r{sessions[-1][1]}, "
        f"{len(events):,} gene event rows ({time.time() - t:.1f}s)",
        file=sys.stderr,
    )

    # Ensembl creates a session when the gene set is rebuilt, not when a release
    # is issued, so the chain is legitimately not contiguous. Each gap is held
    # against Ensembl's own record of when the gene set was last built; a gap
    # with a build inside it means a session is missing rather than never made.
    t = time.time()
    builds = {r: geneset_build(con, r) for gap in gaps for r in gap}
    check_gap_builds(gaps, builds)
    if gaps:
        print(
            f"{len(gaps)} gap(s) in the chain, no gene build in any: "
            f"{', '.join(f'r{a}->r{b} ({builds[a]})' for a, b in gaps)} ({time.time() - t:.1f}s)",
            file=sys.stderr,
        )

    latest = latest_events(events)
    successors_by_old = {old: news for old, (_, news) in latest.items()}
    release_by_old = {old: release for old, (release, _) in latest.items()}

    # The current release is read once, whole, and used for two things: which
    # identifiers are still listed, and where the successors sit. It used to be
    # scanned twice -- the first result was a subset of the second's keys.
    t = time.time()
    current_coords = coords_in(con, current)
    resurrected = sorted(set(successors_by_old) & set(current_coords))
    for old in resurrected:
        del successors_by_old[old]
        del release_by_old[old]
    print(
        f"r{current}: {len(current_coords):,} genes ({time.time() - t:.1f}s). "
        f"{len(successors_by_old):,} retired identifiers; dropped {len(resurrected)} present again "
        f"in r{current}: {', '.join(resurrected[:5])}",
        file=sys.stderr,
    )

    events_by_old = classify(successors_by_old)

    wanted_old: defaultdict[int, set[str]] = defaultdict(set)
    for old, release in release_by_old.items():
        wanted_old[release].add(old)
    old_coords: dict[tuple[str, int], tuple[str, int, int, int]] = {}
    for release in sorted(wanted_old):
        t = time.time()
        found = coords_in(con, release, wanted_old[release])
        old_coords.update(((gene, release), span) for gene, span in found.items())
        print(
            f"  r{release}: {len(found):,}/{len(wanted_old[release]):,} coordinates ({time.time() - t:.1f}s)",
            file=sys.stderr,
        )

    successors = {new for news in successors_by_old.values() for new in news}
    new_coords = {gene: span for gene, span in current_coords.items() if gene in successors}
    con.close()
    print(f"  r{current}: {len(new_coords):,}/{len(successors):,} successor coordinates", file=sys.stderr)

    rows = build_rows(events_by_old, successors_by_old, release_by_old, old_coords, new_coords)

    size = write_csv_gz(
        args.out,
        f"ensembl {ASSEMBLY_NAME} retired gene ids, sessions r{sessions[0][0]}-r{sessions[-1][1]}, "
        f"successor coordinates from r{current}",
        FIELDS,
        rows,
    )
    print(f"\n{len(rows):,} rows -> {args.out} ({size / 2**10:.0f} KB)", file=sys.stderr)
    counts = Counter(events_by_old.values())
    for event in ("retired", "renamed", "merged", "split"):
        print(f"  {event:8} {counts[event]:>6,} identifiers", file=sys.stderr)
    missing_old = sum(1 for old, release in release_by_old.items() if (old, release) not in old_coords)
    print(
        f"{len(successors) - len(new_coords)} successor(s) absent from r{current}, "
        f"{missing_old} identifier(s) absent from the release they were last changed in",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
