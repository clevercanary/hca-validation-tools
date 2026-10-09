"""Build the gene -> release-interval table that check_gene_annotation_version reads.

Run by hand; the output is committed. Refresh when a new Ensembl release lands.
The vendored GENCODE pin does not affect this table -- it is derived only from
Ensembl -- and the ambiguity ceiling the check reads from it is looked up at
runtime, so bumping cellxgene-schema needs no rebuild.

    uv run --no-project --with pymysql python scripts/build_gene_release_intervals.py

Ensembl keeps a core database per release on its public MySQL server, so the
whole history is a query per release rather than a download. Measured at about
two seconds each, so roughly ninety seconds for the full GRCh38 range.

``stable_id_event`` is not usable for this, though it is the right source for
retirement history, which build_gene_id_events.py takes from it. Self-mappings
are not recorded exhaustively -- at r116 TP53 has 24 rows across the 74 sessions -- so an
identifier's absence from a session says nothing about whether it existed then,
and presence at a given release cannot be derived from the table. That is a
limit on deriving *presence*, not on reading *events*.

This file used to give a second reason, that ``mapping_session`` stops at r99.
That was wrong. ``old_release`` and ``new_release`` are varchar, so ``MAX()``
compares them lexically and '99' beats '116'; cast numerically and the sessions
run continuously to r116, the newest being 115->116, created 2025-08-07.

Genes are occasionally resurrected, so presence is stored as intervals rather
than one (first, last) pair. ENSG00000288593 is retired at r105 and returns at
r109; a flat pair would claim it existed at r106-r108. This script measures that
rather than assuming it, and reports what it finds.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from _ensembl import FIRST_GRCH38, HOST, check_releases, connect, core_db, list_releases, require_driver, write_csv_gz

# Release 76 is the first GRCh38 core database; below that is GRCh37, a
# different assembly whose gene sets are not comparable.
DEFAULT_OUT = (
    Path(__file__).resolve().parent.parent
    / "packages/hca-schema-validator/src/hca_schema_validator/gene_release_intervals.csv.gz"
)


def available_releases() -> list[int]:
    """GRCh38 human core databases the server currently serves, oldest first."""
    con = connect()
    try:
        releases = list_releases(con)
    finally:
        con.close()
    return check_releases([r for r in releases if r >= FIRST_GRCH38])


def genes_in(release: int) -> set[str]:
    """Every human gene stable id present in one release."""
    con = connect(core_db(release))
    try:
        cur = con.cursor()
        cur.execute("SELECT stable_id FROM gene WHERE stable_id LIKE 'ENSG%%'")
        return {row[0] for row in cur.fetchall()}
    finally:
        con.close()


def intervals(present: list[int], releases: list[int]) -> list[tuple[int, int]]:
    """Contiguous runs of releases, given the sorted releases a gene appears in.

    A gene is normally one run. A resurrected gene is two or more, which is why
    this returns a list rather than a single pair.
    """
    if not present:
        return []
    index = {r: i for i, r in enumerate(releases)}
    runs, start, prev = [], present[0], present[0]
    for r in present[1:]:
        if index[r] == index[prev] + 1:
            prev = r
            continue
        runs.append((start, prev))
        start = prev = r
    runs.append((start, prev))
    return runs


def main() -> int:
    require_driver()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    releases = available_releases()
    if not releases:
        sys.exit(f"no GRCh38 core databases found on {HOST}")
    print(f"{len(releases)} GRCh38 releases: r{releases[0]}-r{releases[-1]}", file=sys.stderr)

    presence: dict[str, list[int]] = {}
    for r in releases:
        t = time.time()
        for gene in genes_in(r):
            presence.setdefault(gene, []).append(r)
        print(f"  r{r}: {time.time() - t:4.1f}s", file=sys.stderr)

    rows, resurrected = [], []
    for gene in sorted(presence):
        runs = intervals(presence[gene], releases)
        if len(runs) > 1:
            resurrected.append((gene, runs))
        rows.extend((gene, first, last) for first, last in runs)

    size = write_csv_gz(
        args.out,
        f"ensembl GRCh38 gene presence, releases {releases[0]}-{releases[-1]}",
        ["gene_id", "first_release", "last_release"],
        rows,
    )
    print(f"\n{len(presence):,} genes, {len(rows):,} intervals -> {args.out} ({size / 2**10:.0f} KB)", file=sys.stderr)
    print(f"{len(resurrected)} gene(s) present in more than one run:", file=sys.stderr)
    for gene, runs in resurrected[:10]:
        print(f"   {gene}: {runs}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
