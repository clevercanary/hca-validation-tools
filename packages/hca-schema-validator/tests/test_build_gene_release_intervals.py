"""Tests for the Ensembl release interval generator.

The generator is run by hand and its output is committed, so a defect in it
reaches the package as a binary whose diff reads only as "249 KB changed".
Nothing downstream could tell a wrong table from a right one, which is why the
refusals below matter more than they would in code that fails loudly.

Only the pure functions are covered: the parts that talk to Ensembl need the
network and the driver, and are exercised by actually regenerating the table.
"""

from __future__ import annotations

import pytest

from ._generators import load_script

gen = load_script("build_gene_release_intervals")
# release_from_name moved into the module both generators share, so it is tested
# there: one suite covers both callers.
ens = load_script("_ensembl")


# --- write_csv_gz (shared, scripts/_ensembl.py) -----------------------------


def test_write_csv_gz_is_byte_reproducible_whatever_the_output_is_called(tmp_path):
    """The reproducible-bytes guarantee, held by a test rather than by inspection.

    gzip.open embeds the current time and the output basename in the header, so
    a writer that lost mtime=0 or filename="" would make every regeneration a
    diff against the committed artifact -- indistinguishable from a real change
    in the data, which is the one failure nothing downstream can detect.
    """
    rows = [["ENSG00000000001", "76", "116"], ["ENSG00000000002", "90", "100"]]
    first = tmp_path / "one.csv.gz"
    second = tmp_path / "two.csv.gz"
    ens.write_csv_gz(first, "comment", ["gene_id", "first_release", "last_release"], rows)
    ens.write_csv_gz(second, "comment", ["gene_id", "first_release", "last_release"], rows)
    assert first.read_bytes() == second.read_bytes()
    # two writes in the same second would agree even with the clock embedded;
    # the gzip header's MTIME field (bytes 4-8) must be zero on its own
    assert first.read_bytes()[4:8] == b"\x00\x00\x00\x00"
    # and the bytes are the data, not the clock: a rewrite of the same path matches too
    before = first.read_bytes()
    ens.write_csv_gz(first, "comment", ["gene_id", "first_release", "last_release"], rows)
    assert first.read_bytes() == before


# --- release_from_name (shared, scripts/_ensembl.py) ------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("homo_sapiens_core_116_38", 116),
        ("homo_sapiens_core_76_38", 76),
        # In MySQL LIKE, "_" matches any single character, so an unescaped
        # 'homo_sapiens_core_%_38' also matches these. They have five parts and a
        # number in the fourth, so a filter checking only that read them as
        # releases -- 27 of the 41 names the unescaped pattern returns for _37
        # are not core databases at all.
        ("homo_sapiens_coreexpressionatlas_63_37", None),
        ("homo_sapiens_coreexpressionest_55_37", None),
        ("homo_sapiens_funcgen_116_38", None),
        ("mus_musculus_core_116_39", None),
        ("homo_sapiens_core_abc_38", None),
        # The assembly is checked too. The query filters to _38, but this
        # function is the last guard and must not rely on the pattern it sits
        # behind -- a broadened discovery query would otherwise feed GRCh37
        # releases into a GRCh38 table.
        ("homo_sapiens_core_116_37", None),
        ("homo_sapiens_core_75_37", None),
        ("homo_sapiens_core_116", None),
        ("", None),
    ],
)
def test_release_from_name(name, expected):
    assert ens.release_from_name(name) == expected


# --- check_releases --------------------------------------------------------


def test_check_releases_accepts_a_contiguous_run():
    found = list(range(gen.FIRST_GRCH38, gen.FIRST_GRCH38 + 5))
    assert gen.check_releases(found) == found


def test_check_releases_refuses_an_empty_archive():
    with pytest.raises(SystemExit, match="served no GRCh38 release"):
        gen.check_releases([])


def test_check_releases_refuses_a_hole():
    # A missing release is absorbed into the surrounding run, so the table would
    # claim presence at a release never queried.
    found = [gen.FIRST_GRCH38, gen.FIRST_GRCH38 + 1, gen.FIRST_GRCH38 + 3]
    with pytest.raises(SystemExit, match="missing release"):
        gen.check_releases(found)


def test_check_releases_refuses_a_narrower_floor():
    # Counted from FIRST_GRCH38, not from the earliest release found: a table
    # starting one release late is not obviously broken, and the check reads its
    # floor as a fact about Ensembl rather than about what the server served.
    found = list(range(gen.FIRST_GRCH38 + 1, gen.FIRST_GRCH38 + 4))
    with pytest.raises(SystemExit, match="missing release"):
        gen.check_releases(found)


def test_check_releases_refuses_a_duplicate():
    # The hole check cannot see this -- a repeat leaves no gap -- and a repeat
    # breaks every gene's run at that point, manufacturing one resurrection per
    # gene across the whole table.
    found = [gen.FIRST_GRCH38, gen.FIRST_GRCH38 + 1, gen.FIRST_GRCH38 + 1, gen.FIRST_GRCH38 + 2]
    with pytest.raises(SystemExit, match="more than once"):
        gen.check_releases(found)


# --- intervals -------------------------------------------------------------


def test_intervals_folds_a_contiguous_run_into_one_pair():
    assert gen.intervals([76, 77, 78], [76, 77, 78]) == [(76, 78)]


def test_intervals_keeps_a_resurrection_as_separate_runs():
    # ENSG00000288593 is retired at r105 and returns at r109; a single pair would
    # claim it existed at r106-r108. The second argument is every release the
    # archive serves, not the gene's own -- adjacency is judged against that.
    served = list(range(100, 111))
    assert gen.intervals([100, 101, 109, 110], served) == [(100, 101), (109, 110)]


def test_intervals_splits_on_list_adjacency_not_arithmetic():
    # Runs are split on position in the available-release list, which is what
    # lets a sparse archive be represented faithfully -- and why a duplicate in
    # that list is refused before it gets here.
    # Where the archive serves only 100 and 104, a gene in both is unbroken.
    assert gen.intervals([100, 104], [100, 104]) == [(100, 104)]
    # Where it also serves 102, the same gene is absent from one and splits.
    assert gen.intervals([100, 104], [100, 102, 104]) == [(100, 100), (104, 104)]


def test_intervals_handles_a_single_release_and_none():
    assert gen.intervals([76], [76, 77]) == [(76, 76)]
    assert gen.intervals([], [76, 77]) == []
