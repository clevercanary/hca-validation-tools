"""Enforcement of the contract's Scope rule: we operate on files anndata can read.

``docs/anndata-tools-contract.md`` (Scope) has always said that a file
``ad.read_h5ad`` cannot open is out of scope — refused, not repaired, not
partially processed — but nothing enforced it. Fifteen tools reached the file
with raw h5py and ran to completion on a file nobody can open: ten of them
left a snapshot behind and reported success (#661).

Two properties are under test here, and they are different in kind:

- **AC1/AC3, behavioural** — every gated path refuses a truncated file, the
  writers leave nothing on disk, and the refusal carries anndata's own words.
- **AC2, structural** — the roster above is *complete*. A tool added later
  that skips the gate fails this suite rather than silently joining the
  fifteen. This is the check the design turns on: #651's rejected approach
  needed a roster over shapes in an open file format, unbounded and defined
  outside this repo, and eight review rounds went into patching it. This
  roster is over ``hca_anndata_tools.__all__`` — closed, ours, enumerable.
"""

from __future__ import annotations

import inspect

import anndata as ad
import pytest

import hca_anndata_tools as tools
from hca_anndata_tools._io import gate_h5ad_paths
from hca_anndata_tools.testing import (
    assert_no_snapshot_written,
    create_sample_h5ad,
    create_truncated_h5ad,
)

# Public names with a path-shaped parameter that never opens an h5ad. Named
# individually, with the reason, so that "everything else is gated" is a claim
# this file can make without a judgement call at read time.
#
# The test is "opens no h5ad", not "touches no file": several of these stat a
# directory, glob it, or read the bytes to hash them. What none of them does
# is decode the file as an h5ad, which is the only thing the gate can check
# and the only thing an unopenable file breaks.
OMISSIONS = {
    "locate_files": "scans a directory for h5ad files; opens none of them",
    "write_h5ad": (
        "takes an in-memory AnnData. It does stat source_path and read its bytes for the "
        "provenance sha256, but never decodes it as an h5ad — and its callers have already "
        "gated the path the AnnData came from"
    ),
    "generate_output_path": "derives a name and checks the lineage root is beside it; opens no h5ad",
    "resolve_latest": "globs the directory for the newest snapshot name; opens nothing",
    "strip_timestamp": "string manipulation on a filename",
}


@pytest.fixture
def good(tmp_path) -> str:
    """A valid h5ad, for the other side of the two-file tools."""
    return str(create_sample_h5ad(tmp_path / "good.h5ad"))


@pytest.fixture
def truncated(tmp_path) -> str:
    """A half-written h5ad — the ordinary way a file fails to open."""
    return str(create_truncated_h5ad(tmp_path / "truncated.h5ad"))


def _cases(bad: str, good: str) -> list[tuple[str, object, dict, bool]]:
    """(id, tool, kwargs, writes_a_snapshot) for every gated path.

    One entry per *path*, not per tool. copy_cap_annotations is the reason:
    it opened its source through anndata and read its target with raw h5py,
    so it passed a per-tool audit while an unopenable target was still
    snapshotted and written.
    """
    return [
        # --- Newly gated by #661: reached the file with raw h5py ---
        (
            "rename_cell_ids",
            tools.rename_cell_ids,
            {"path": bad, "column": "donor_id", "value": "d1", "prefix_from": "cell", "prefix_to": "c"},
            True,
        ),
        (
            "backfill_obs_from_source[target]",
            tools.backfill_obs_from_source,
            {"target_path": bad, "source_path": good, "columns": ["donor_id"]},
            True,
        ),
        (
            "backfill_obs_from_source[source]",
            tools.backfill_obs_from_source,
            {"target_path": good, "source_path": bad, "columns": ["donor_id"]},
            True,
        ),
        ("copy_cap_annotations[source]", tools.copy_cap_annotations, {"source_path": bad, "target_path": good}, True),
        ("copy_cap_annotations[target]", tools.copy_cap_annotations, {"source_path": good, "target_path": bad}, True),
        ("drop_obs_columns", tools.drop_obs_columns, {"path": bad, "columns": ["donor_id"]}, True),
        ("strip_forbidden_obs_columns", tools.strip_forbidden_obs_columns, {"path": bad}, True),
        ("strip_cap_annotations", tools.strip_cap_annotations, {"path": bad}, True),
        (
            "merge_obs_categories",
            tools.merge_obs_categories,
            {"path": bad, "column": "donor_id", "from_value": "a", "to_value": "b"},
            True,
        ),
        ("rename_obs_column", tools.rename_obs_column, {"path": bad, "column": "donor_id", "new_name": "donor"}, True),
        ("set_producer_uns", tools.set_producer_uns, {"path": bad, "updates": []}, True),
        ("replace_placeholder_values", tools.replace_placeholder_values, {"path": bad, "columns": ["donor_id"]}, True),
        ("validate_marker_genes", tools.validate_marker_genes, {"path": bad}, False),
        ("view_edit_log", tools.view_edit_log, {"path": bad}, False),
        ("check_x_normalization", tools.check_x_normalization, {"path": bad}, False),
        ("check_schema_type", tools.check_schema_type, {"path": bad}, False),
        ("check_raw_counts", tools.check_raw_counts, {"path": bad}, False),
        ("check_duplicate_cells", tools.check_duplicate_cells, {"path": bad}, False),
        ("get_storage_info", tools.get_storage_info, {"path": bad}, False),
        # --- Already correct: open through open_h5ad in the body. Here so the
        # AC2 roster covers the whole public surface rather than only the
        # tools this issue changed.
        ("get_summary", tools.get_summary, {"path": bad}, False),
        ("get_descriptive_stats", tools.get_descriptive_stats, {"path": bad}, False),
        ("view_data", tools.view_data, {"path": bad}, False),
        ("get_cap_annotations", tools.get_cap_annotations, {"path": bad}, False),
        ("plot_embedding", tools.plot_embedding, {"path": bad}, False),
        ("list_uns_fields", tools.list_uns_fields, {"path": bad}, False),
        ("set_uns", tools.set_uns, {"path": bad, "field": "title", "value": "t"}, True),
        ("convert_cellxgene_to_hca", tools.convert_cellxgene_to_hca, {"path": bad}, True),
        ("compress_h5ad", tools.compress_h5ad, {"path": bad}, True),
        ("normalize_raw", tools.normalize_raw, {"path": bad}, True),
    ]


def _ids() -> list[str]:
    return [c[0] for c in _cases("bad", "good")]


# The cases are parametrized by index rather than by value because building
# them needs the tmp_path fixtures, which do not exist at collection time.
# _cases() is called twice with placeholder paths purely to get the ids and
# the count; the real paths arrive inside each test.


@pytest.mark.parametrize("index", range(len(_ids())), ids=_ids())
def test_refuses_truncated_file(index, truncated, good):
    """AC1 — every gated path refuses, and no writer leaves a snapshot behind."""
    case_id, fn, kwargs, writes = _cases(truncated, good)[index]

    result = fn(**kwargs)

    assert isinstance(result, dict), f"{case_id} did not return the tool error shape"
    assert "error" in result, f"{case_id} accepted a file anndata cannot open: {result}"
    if writes:
        # Both fixtures live in the same tmp_path, so one scan covers a
        # snapshot taken beside either side of a two-file tool.
        assert_no_snapshot_written(truncated)


@pytest.mark.parametrize(
    "index",
    [i for i, c in enumerate(_cases("bad", "good")) if hasattr(c[1], "__gated_paths__")],
    ids=[c[0] for c in _cases("bad", "good") if hasattr(c[1], "__gated_paths__")],
)
def test_refusal_is_anndatas_own_words(index, truncated, good):
    """AC3 — the message is anndata's, with nothing of ours around it.

    Asserted by equality against what ``ad.read_h5ad`` itself raises rather
    than by matching wording, so it stays true when anndata changes its text.

    Scoped to the paths this issue gates. The tools that already opened
    through ``open_h5ad`` in their own bodies shape their errors to their own
    conventions, which #661 does not touch.
    """
    case_id, fn, kwargs, _ = _cases(truncated, good)[index]

    try:
        ad.read_h5ad(truncated, backed="r")
    except Exception as e:
        expected = str(e)
    else:  # pragma: no cover - the truncated fixture guards against this
        pytest.fail("the truncated fixture opened cleanly")

    assert fn(**kwargs)["error"] == expected, f"{case_id} added wording of its own"


def test_missing_file_keeps_each_tools_own_message(tmp_path, good):
    """The gate fires only on a file that exists, so 'File not found' survives.

    A missing file is not an unopenable one, so the gate must leave it alone
    and let each tool answer in its own words. Most say "File not found";
    copy_cap_annotations has no existence check at all and surfaces h5py's
    errno-2 text, which is pre-existing and equally unchanged by the gate.
    """
    absent = str(tmp_path / "absent.h5ad")

    for case_id, fn, kwargs, _ in _cases(absent, good):
        gated = getattr(fn, "__gated_paths__", ())
        # Only where the absent path is the first one the tool reaches. Give
        # copy_cap_annotations a good source and a missing target and it
        # rejects the source for having no CAP metadata long before the
        # target matters — a real early return, but not this property.
        if not gated or kwargs.get(gated[0]) != absent:
            continue
        error = fn(**kwargs)["error"].lower()
        assert "not found" in error or "no such file" in error, f"{case_id}: {error}"


def test_every_public_path_is_gated_or_named():
    """AC2 — the roster is complete, and stays complete without anyone's attention.

    The oracle here is deliberately *not* ``GATED_PATH_PARAMS``. Checking the
    decorator's names against the same constant the decorator selects with
    would compare an expression to itself: a path parameter the constant does
    not name would be defined out of existence rather than flagged. So the
    expected set is derived independently, from the parameter names alone.

    Two ways a tool can satisfy this. A decorated tool must gate *every* one
    of its path parameters — that is what ``copy_cap_annotations`` failed,
    gating its source while its target was snapshotted unopened. An
    undecorated tool must be exercised by the refusal tests above (the ten
    that open through ``open_h5ad`` in their own bodies, which keeps them
    from paying a second, redundant anndata open), and may have only one path
    to prove: a second one is unprovable that way and needs the decorator.
    """
    covered = {case_id.split("[")[0] for case_id, *_ in _cases("bad", "good")}

    for name in tools.__all__:
        obj = getattr(tools, name)
        if not callable(obj) or name in OMISSIONS:
            continue
        try:
            params = inspect.signature(obj).parameters
        except (TypeError, ValueError):
            continue
        pathish = {p for p in params if "path" in p.lower()}
        if not pathish:
            continue

        gated = getattr(obj, "__gated_paths__", None)
        if gated is not None:
            assert set(gated) == pathish, (
                f"{name} gates {sorted(gated)} but takes {sorted(pathish)} — "
                f"a path left ungated is a file written without being opened. "
                f"If the new parameter is not an input h5ad, rename it so it "
                f"does not read as one."
            )
            continue

        assert name in covered, (
            f"{name} takes a path but no refusal test above proves it refuses a file "
            f"anndata cannot open. Gate it with @gate_h5ad_paths and add it to "
            f"_cases(), or add it to OMISSIONS with the reason it opens no h5ad."
        )
        assert len(pathish) == 1, (
            f"{name} takes {sorted(pathish)} but is not decorated, so only one of them "
            f"is proven by its refusal test. Gate it with @gate_h5ad_paths."
        )


def test_decorator_refuses_a_function_with_no_path():
    """Decorating something ungateable is a mistake, caught at decoration time.

    That is import time for a module the caller imports directly, but
    ``__init__`` is lazy (``_LAZY_IMPORTS``), so for a tool reached only
    through the package it is the first attribute access.
    """
    with pytest.raises(TypeError, match="no parameter"):

        @gate_h5ad_paths
        def not_a_file_tool(columns: list[str]) -> dict:
            return {}


def test_good_files_are_unaffected(sample_h5ad):
    """AC4 — the gate is invisible on a file anndata can open."""
    assert "error" not in tools.get_storage_info(str(sample_h5ad))
    assert "error" not in tools.check_schema_type(str(sample_h5ad))
    assert "error" not in tools.view_edit_log(str(sample_h5ad))
    assert "error" not in tools.check_x_normalization(str(sample_h5ad))


def test_gate_resolves_to_the_latest_snapshot(tmp_path):
    """The gate opens the file the tool will operate on, not the base name.

    A valid original beside a truncated ``-edit-`` snapshot is the shape that
    would slip through if the gate ran before ``resolve_latest``.
    """
    original = create_sample_h5ad(tmp_path / "d.h5ad")
    snapshot = create_truncated_h5ad(tmp_path / "d-edit-2026-01-01-00-00-00.h5ad", source=original)

    result = tools.get_storage_info(str(original))

    assert "error" in result, "the gate opened the original, not the snapshot in use"
    assert snapshot.is_file()
