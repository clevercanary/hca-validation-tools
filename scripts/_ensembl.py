"""Pieces the Ensembl reference-table generators must agree on.

Imported by ``build_gene_release_intervals.py`` and ``build_gene_id_events.py``,
which are run as files rather than as a package -- Python puts the script's own
directory first on the path, so a plain ``import _ensembl`` resolves from any
working directory.

Everything the two generators must agree on lives here: where the server is
and how a release's database is named, which releases it serves, how a name is
read as a release, and how a committed table is written.

    write_csv_gz       the reproducible-bytes guarantee, which is the only check
                       there is that a regenerated artifact is right
    release_from_name  reading a release number out of a core database name,
                       which is the last point at which the wrong database could
                       be mistaken for a release
    connect, core_db   where the server is and how a release's database is named
    list_releases      which releases it serves, read through release_from_name
"""

from __future__ import annotations

import csv
import gzip
import io
from collections.abc import Iterable, Sequence
from pathlib import Path

try:
    import pymysql
except ImportError:  # pragma: no cover - the generators are run by hand
    # Deferred rather than fatal at import, so the pure functions here stay
    # testable without the driver. Each generator's main() reports it before
    # touching the server.
    pymysql = None

# Ensembl's public server. Anonymous, no password, read-only.
HOST = "ensembldb.ensembl.org"
USER = "anonymous"
PORT = 3306
# The assembly both generators speak for, as it appears in a core database name.
ASSEMBLY_SUFFIX = "38"


def release_from_name(name: str, assembly: str = ASSEMBLY_SUFFIX) -> int | None:
    """The release a core database name carries, or None if it is not one.

    Every part is checked, not just that the fourth is a number. The callers
    escape the underscores in their ``SHOW DATABASES LIKE`` pattern so the server
    should return only core databases, but a name is cheap to verify and this is
    the last point at which a wrong one could be read as a release. Unescaped,
    that pattern also matched ``homo_sapiens_coreexpressionatlas_63_37``.
    """
    parts = name.split("_")
    if len(parts) != 5:
        return None
    organism_genus, organism_species, kind, release, found_assembly = parts
    if (organism_genus, organism_species, kind, found_assembly) != ("homo", "sapiens", "core", assembly):
        return None
    return int(release) if release.isdigit() else None


def write_csv_gz(path: Path, comment: str, header: Sequence[str], rows: Iterable[Sequence]) -> int:
    """Write a committed reference table, byte-reproducibly. Returns its size.

    Written through GzipFile with mtime=0 and no stored filename, so the same
    Ensembl data produces the same bytes. ``gzip.open`` embeds the current time
    and the output basename in the header, which would make every rerun of a
    generator a diff against the committed artifact even when nothing about
    Ensembl had changed -- and there would be no way to tell that from a run that
    did pick something up.

    That property is the only check there is that a regenerated table is right:
    these artifacts are binaries whose diffs read as "a few hundred KB changed",
    and nothing downstream can tell a good table from a bad one. It is stated
    here once rather than once per generator, because a copy that quietly lost
    ``mtime=0`` would produce a spurious diff indistinguishable from a real
    change in the data.

    The ``#`` comment line records what the table covers; both readers in the
    validator skip lines starting with it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=9, mtime=0, filename="") as gz:
        fh = io.TextIOWrapper(gz, encoding="utf-8", newline="")
        fh.write(f"# {comment}\n")
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
        fh.flush()
        fh.detach()
    return path.stat().st_size


def connect(database: str | None = None):
    """Open a connection to Ensembl's public server, optionally on one database.

    Checks for the driver itself, so a direct call without it fails with the
    same message main() would have given rather than an AttributeError on None.
    """
    require_driver()
    return pymysql.connect(host=HOST, user=USER, port=PORT, database=database, connect_timeout=60)


def core_db(release: int, assembly: str = ASSEMBLY_SUFFIX) -> str:
    """The core database name for one release."""
    return f"homo_sapiens_core_{release}_{assembly}"


def list_releases(con, assembly: str = ASSEMBLY_SUFFIX) -> list[int]:
    """Every release the server serves a core database for, oldest first.

    The underscores in the pattern are escaped: in MySQL LIKE, "_" matches any
    single character, so the unescaped form also matched
    ``homo_sapiens_coreexpressionatlas_63_37`` and friends. Measured against the
    live server: unescaped returns 41 names for _37 of which 27 are not core
    databases; escaped returns 14, all of them real. Ensembl publishes no such
    database for _38 today, which is the only reason the unescaped pattern was
    harmless there.

    Names are read through release_from_name rather than by counting
    underscores, so a database the pattern should not have returned cannot be
    mistaken for a release.
    """
    cur = con.cursor()
    cur.execute(rf"SHOW DATABASES LIKE 'homo\_sapiens\_core\_%%\_{assembly}'")
    found = (release_from_name(name, assembly) for (name,) in cur.fetchall())
    return sorted(r for r in found if r is not None)


def require_driver() -> None:
    """Refuse clearly when the MySQL driver is absent.

    The import above is deferred so the pure functions here stay testable
    without the driver; this is where a generator finds out, before it reaches
    the server rather than part-way through a four-minute run.
    """
    if pymysql is None:
        raise SystemExit("pymysql is required:  uv run --no-project --with pymysql python scripts/...")
