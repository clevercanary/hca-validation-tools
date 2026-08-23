"""Tests for the shared coherence guards (#622).

These pin the extracted helpers directly. The per-tool suites still cover
each tool's *policy* — what it does with what these find.
"""

import pytest

from hca_anndata_tools._io import obs_index_name
from hca_anndata_tools.cap import cap_palette_keys
from hca_anndata_tools.guards import (
    GuardRefusal,
    ObsColumnReferences,
    batch_condition_refusal,
    detect_obs_references,
    direct_members,
    is_malformed_name,
    legacy_layout_problems,
    malformed_name_problems,
    obs_index_problems,
    obs_name_problems,
    require_obs_group,
)


def _obs(f, *, index_name="_index", columns=()):
    obs = f.create_group("obs")
    obs.attrs["_index"] = index_name
    obs.create_dataset(index_name, data=["c1", "c2"])
    for c in columns:
        obs.create_dataset(c, data=[1, 2])
    return obs


# --- structural invariants ---------------------------------------------------


@pytest.mark.parametrize("name", ["/X", "obs/donor_id", "a/b", "", "   "])
def test_malformed_names_are_rejected(name):
    """'/' resolves as an HDF5 link path, so such a name would reach outside
    the group being edited; blank names name nothing."""
    assert is_malformed_name(name)
    assert malformed_name_problems([name])


@pytest.mark.parametrize("name", ["donor_id", "cell_type--label", "x.y"])
def test_well_formed_names_pass(name):
    assert not is_malformed_name(name)
    assert malformed_name_problems([name]) == []


def test_malformed_names_are_reported_together():
    """All bad names in one round trip, not the first one found."""
    problems = malformed_name_problems(["/X", "ok", ""])
    assert len(problems) == 1
    assert "/X" in problems[0] and "''" in problems[0]
    assert "ok" not in problems[0]


def test_obs_index_name_reads_the_attr(h5):
    assert obs_index_name(_obs(h5, index_name="cellID")) == "cellID"


def test_obs_index_name_defaults(h5):
    obs = h5.create_group("obs")
    assert obs_index_name(obs) == "_index"


def test_obs_index_is_refused_with_the_caller_s_verb(h5):
    obs = _obs(h5, index_name="cellID")

    problems = obs_index_problems(obs, ["cellID"], verbing="deleting")

    assert len(problems) == 1
    assert "cellID" in problems[0]
    assert "deleting it would destroy the file" in problems[0]


def test_obs_index_problems_empty_when_not_named(h5):
    assert obs_index_problems(_obs(h5), ["donor_id"], verbing="deleting") == []


def test_direct_members_does_not_resolve_link_paths(h5):
    """`"/X" in obs` is True whenever the file has a root X — the trap the
    membership set exists to avoid."""
    h5.create_dataset("X", data=[1])
    obs = _obs(h5, columns=["donor_id"])

    assert "/X" in obs  # h5py's answer, and why we do not use it
    assert "/X" not in direct_members(obs)
    assert "donor_id" in direct_members(obs)


def test_require_obs_group_returns_the_group(h5):
    obs = _obs(h5)
    assert require_obs_group(h5) == obs


def test_require_obs_group_absent(h5):
    with pytest.raises(GuardRefusal, match="no obs group"):
        require_obs_group(h5)


def test_require_obs_group_not_a_group(h5):
    """A Dataset at 'obs' is a different repair than a missing one, so it gets
    its own message."""
    h5["obs"] = "not a group"
    with pytest.raises(GuardRefusal, match="predates the modern h5ad layout"):
        require_obs_group(h5)


def test_legacy_layout_is_refused(h5):
    uns = h5.create_group("uns")
    uns["cellannotation_schema_version"] = "0.1.0"
    assert legacy_layout_problems(uns)


def test_legacy_layout_absent_and_none(h5):
    assert legacy_layout_problems(h5.create_group("uns")) == []
    assert legacy_layout_problems(None) == []


# --- the reference detector --------------------------------------------------


def test_detect_finds_nothing_without_uns():
    assert detect_obs_references(None, ["donor_id"]) == ObsColumnReferences(
        batch_condition=[], batch_condition_declared=[], palettes={}, cap_columns=[]
    )


def test_detect_by_value_batch_condition(h5):
    uns = h5.create_group("uns")
    uns.create_dataset("batch_condition", data=["donor_id", "sample_id"])

    refs = detect_obs_references(uns, ["sample_id", "cell_type"])

    assert refs.batch_condition == ["sample_id"]  # only the requested one


def test_detect_by_key_palette(h5):
    uns = h5.create_group("uns")
    uns.create_dataset("donor_id_colors", data=["#fff"])

    refs = detect_obs_references(uns, ["donor_id", "cell_type"])

    assert refs.palettes == {"donor_id": "donor_id_colors"}


def test_detect_by_convention_cap_columns(h5):
    uns = h5.create_group("uns")
    uns.create_group("cap_metadata")

    refs = detect_obs_references(uns, ["myset--cell_fullname", "donor_id"])

    assert refs.cap_columns == ["myset--cell_fullname"]


def test_cap_columns_need_the_declaration(h5):
    """The '--' convention alone is not a CAP set: without cap_metadata there
    is no declaration to break."""
    refs = detect_obs_references(h5.create_group("uns"), ["myset--cell_fullname"])
    assert refs.cap_columns == []


def test_detect_finds_all_three_mechanisms_at_once(h5):
    """The point of one detector: per-site reasoning kept missing one."""
    uns = h5.create_group("uns")
    uns.create_dataset("batch_condition", data=["donor_id"])
    uns.create_dataset("donor_id_colors", data=["#fff"])
    uns.create_group("cap_metadata")

    refs = detect_obs_references(uns, ["donor_id", "myset--cell_fullname"])

    assert refs.batch_condition == ["donor_id"]
    assert refs.palettes == {"donor_id": "donor_id_colors"}
    assert refs.cap_columns == ["myset--cell_fullname"]


def test_batch_condition_refusal_carries_the_tool_s_verb():
    message = batch_condition_refusal(["donor_id"], verbing="dropping")
    assert "batch_condition" in message
    assert "donor_id" in message
    assert "dropping one changes" in message


def test_cap_palette_keys_finds_cap_shaped_palettes():
    keys = ["myset--cell_fullname_colors", "donor_id_colors", "cap_metadata", "other"]
    assert cap_palette_keys(keys) == ["myset--cell_fullname_colors"]


def test_cap_palette_keys_finds_orphans():
    """A palette whose column an earlier overwrite era already deleted still
    counts — nothing else would ever collect it."""
    assert cap_palette_keys(["gone--label_colors"]) == ["gone--label_colors"]


def test_detect_carries_the_whole_declaration_for_repair(h5):
    """A refusal reports the intersection; a repair rewrites the whole list,
    which the intersection alone cannot support."""
    uns = h5.create_group("uns")
    uns.create_dataset("batch_condition", data=["donor_id", "sample_id"])

    refs = detect_obs_references(uns, ["sample_id"])

    assert refs.batch_condition == ["sample_id"]
    assert refs.batch_condition_declared == ["donor_id", "sample_id"]  # file order kept


def test_obs_name_problems_collects_all_three_structural_faults(h5):
    """One entry point for any name source — a caller's request, or the
    file's own column-order attribute."""
    obs = _obs(h5, index_name="cellID", columns=["donor_id"])

    problems = obs_name_problems(obs, ["/X", "cellID", "absent", "donor_id"], verbing="deleting")

    assert len(problems) == 3
    assert any("/X" in p for p in problems)
    assert any("cellID" in p and "obs index" in p for p in problems)
    assert any("absent" in p for p in problems)
    assert not any("donor_id" in p for p in problems)


def test_obs_name_problems_reports_a_malformed_name_once(h5):
    """'/X' is necessarily absent from the members too; listing it under both
    would imply its only fault was being missing."""
    problems = obs_name_problems(_obs(h5), ["/X"], verbing="deleting")
    assert len(problems) == 1


def test_obs_name_problems_checks_every_name_not_just_the_reported_ones(h5):
    """The message is capped; the checking is not. Truncating the input would
    let a name past the cap reach the delete unchecked (#623) — which for a
    '/' name means h5py resolving a link path outside obs."""
    obs = _obs(h5, columns=[f"col{i}" for i in range(8)])
    names = [f"col{i}" for i in range(8)] + ["late/bad"]

    problems = obs_name_problems(obs, names, verbing="removing")

    assert any("late/bad" in p for p in problems), "a malformed name past the report cap was not checked"


def test_obs_name_problems_caps_what_it_reports(h5):
    """A malformed file can list hundreds of stale entries, and the string
    travels back through an MCP tool response."""
    obs = _obs(h5)
    problems = obs_name_problems(obs, [f"bad{i}/x" for i in range(9)], verbing="removing")

    assert len(problems) == 1
    assert "(+4 more)" in problems[0]


def test_palette_detection_does_not_resolve_link_paths(h5):
    """'/X' would make h5py resolve '/X_colors' from the file root, reporting
    an unrelated root dataset as this column's palette — which drop would then
    delete with the column. Malformed names are refused before any write, so
    this is the belt to that brace (#623)."""
    h5.create_dataset("X_colors", data=["#fff"])
    uns = h5.create_group("uns")

    refs = detect_obs_references(uns, ["/X"])

    assert "/X_colors" in uns, "h5py resolves the path — this is the trap"
    assert "/X_colors" not in direct_members(uns)  # and this is how we avoid it
    assert refs.palettes == {}
