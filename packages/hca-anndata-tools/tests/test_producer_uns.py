"""Tests for set_producer_uns — writing scalars into producer-owned uns namespaces.

Every assertion on a written value also asserts its dtype. That is the point of
the tool: a producer namespace has no schema, so ``validate_schema`` has no
opinion on it, and a test that checked the value alone would pass on exactly
the mis-write this exists to prevent (a bool stored as the string 'false').
"""

import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from hca_anndata_tools import list_uns_fields, set_producer_uns, view_edit_log
from hca_anndata_tools._io import require_stamped_group, write_edit_log_h5py
from hca_anndata_tools.edit import _type_display
from hca_anndata_tools.schema.helpers import uns_field_registry


def _scalar(group: h5py.Group, name: str, value) -> None:
    """Create a scalar dataset stamped the way anndata stamps one."""
    group.create_dataset(name, data=value)
    encoding = "string" if isinstance(value, str) else "numeric-scalar"
    group[name].attrs["encoding-type"] = encoding
    group[name].attrs["encoding-version"] = "0.2.0"


def _stamp(dataset, encoding: str):
    """Mark a dataset with the ``encoding-type`` attrs anndata reads."""
    dataset.attrs["encoding-type"] = encoding
    dataset.attrs["encoding-version"] = "0.2.0"
    return dataset


@pytest.fixture
def producer_h5ad(sample_h5ad_for_write: Path) -> Path:
    """A file carrying a nested producer namespace shaped like the real one.

    Mirrors ``uns['ihbca_provenance']`` on the breast-v1 source datasets: a
    variable-length string, a bool, an int, a nested subgroup with a float,
    plus a fixed-length string and a non-scalar array as the shapes the tool
    has to refuse.

    The two refusal shapes carry ``encoding-type`` stamps, which the real
    files have and an earlier version of this fixture omitted. Unstamped,
    anndata cannot read them at all ("string indices must be integers", #632)
    — which since #661 means the file never reaches the tool, and 35 tests
    below would have been asserting the gate's refusal rather than
    ``set_producer_uns``'s own. Stamping preserves the ``|S3``/``|S5`` dtypes
    that are the actual subject of the refusal tests. All eight real breast-v1
    files open through anndata, so this is the shape the tool meets in
    production.
    """
    with h5py.File(sample_h5ad_for_write, "a") as f:
        group = require_stamped_group(f, "uns/ihbca_provenance")
        _scalar(group, "git_branch", "dev")
        _scalar(group, "git_hash", "f78d0212f9d8bd86e3cbbb47a269a33981346956")
        _scalar(group, "git_dirty", True)
        _scalar(group, "cell_count", np.int64(52681))
        _scalar(group, "small_count", np.int8(5))
        _stamp(group.create_dataset("short_code", data=np.bytes_("dev")), "string")
        _stamp(
            group.create_dataset("unmapped_examples", data=np.array([b"ENSG1", b"ENSG2"])),
            "string-array",
        )
        nested = require_stamped_group(f, "uns/ihbca_provenance/mapping_stats")
        _scalar(nested, "pct_mapped", np.float64(90.385))
    return sample_h5ad_for_write


def _set(h5ad: Path, field, value):
    """One-update call — the shape most tests here need."""
    return set_producer_uns(str(h5ad), [{"field": field, "value": value}])


def _read(path: str, *segments: str):
    """``(value, dtype, attrs)`` at a uns path in the written file."""
    with h5py.File(path, "r") as f:
        ds = f["uns"]
        for segment in segments:
            ds = ds[segment]
        return ds[()], ds.dtype, dict(ds.attrs)


THE_CORRECTION = [
    {"field": ["ihbca_provenance", "git_hash"], "value": "0454dde01415d16382d355f7d5d64325ef47ca65"},
    {"field": ["ihbca_provenance", "git_branch"], "value": "main"},
    {"field": ["ihbca_provenance", "git_dirty"], "value": False},
]


class TestTheCorrection:
    """The motivating case: hca-ingest-coordination#23's three-field patch."""

    def test_writes_every_field_with_its_dtype_intact(self, producer_h5ad):
        result = set_producer_uns(str(producer_h5ad), THE_CORRECTION)

        assert "error" not in result, result.get("error")
        assert result["fields_written"] == 3

        value, dtype, attrs = _read(result["output_path"], "ihbca_provenance", "git_dirty")
        assert bool(value) is False
        assert dtype == np.dtype(bool), "a bool stored as anything else is the failure this tool exists to prevent"
        assert attrs["encoding-type"] == "numeric-scalar"

        value, dtype, attrs = _read(result["output_path"], "ihbca_provenance", "git_branch")
        assert value == b"main"
        assert h5py.check_string_dtype(dtype) is not None
        assert attrs["encoding-type"] == "string"

        value, _, _ = _read(result["output_path"], "ihbca_provenance", "git_hash")
        assert value == b"0454dde01415d16382d355f7d5d64325ef47ca65"

    def test_reports_old_and_new_values(self, producer_h5ad):
        result = set_producer_uns(str(producer_h5ad), THE_CORRECTION)

        by_field = {tuple(u["field"]): u for u in result["updates"]}
        dirty = by_field[("ihbca_provenance", "git_dirty")]
        assert dirty["old_value"] is True
        assert dirty["new_value"] is False
        assert dirty["dtype"] == "bool"
        assert by_field[("ihbca_provenance", "git_branch")]["old_value"] == "dev"

    def test_batch_is_one_snapshot_and_one_edit_log_entry(self, producer_h5ad):
        before = len(view_edit_log(str(producer_h5ad)).get("entries", []))

        result = set_producer_uns(str(producer_h5ad), THE_CORRECTION)

        written = sorted(p.name for p in producer_h5ad.parent.glob("*.h5ad"))
        assert len(written) == 2, f"expected the source plus one snapshot, got {written}"
        entries = view_edit_log(result["output_path"])["entries"]
        assert len(entries) == before + 1, "three fields must not produce three log entries"
        assert entries[-1]["operation"] == "set_producer_uns"

    def test_edit_log_details_carry_every_field(self, producer_h5ad):
        result = set_producer_uns(str(producer_h5ad), THE_CORRECTION)

        entry = view_edit_log(result["output_path"])["entries"][-1]
        fields = entry["details"]["fields"]
        assert {tuple(f["field"]) for f in fields} == {
            ("ihbca_provenance", "git_hash"),
            ("ihbca_provenance", "git_branch"),
            ("ihbca_provenance", "git_dirty"),
        }
        dirty = next(f for f in fields if f["field"][-1] == "git_dirty")
        assert (dirty["old_value"], dirty["new_value"], dirty["dtype"]) == (True, False, "bool")
        # The entry has to survive the JSON round trip the log is stored as —
        # a numpy scalar left in details would raise on write, not on read.
        json.dumps(entry)

    def test_nested_subgroup_is_reachable(self, producer_h5ad):
        result = _set(producer_h5ad, ["ihbca_provenance", "mapping_stats", "pct_mapped"], 91.5)

        assert "error" not in result, result.get("error")
        value, dtype, _ = _read(result["output_path"], "ihbca_provenance", "mapping_stats", "pct_mapped")
        assert value == pytest.approx(91.5)
        assert dtype == np.dtype(np.float64)


class TestTypeGuards:
    """The stored dtype is the contract; nothing downstream would catch a breach."""

    def test_bool_into_a_string_field_is_refused(self, producer_h5ad):
        result = _set(producer_h5ad, ["ihbca_provenance", "git_branch"], False)

        assert "holds a string" in result["error"]
        assert "bool" in result["error"]

    def test_string_into_a_bool_field_is_refused(self, producer_h5ad):
        result = _set(producer_h5ad, ["ihbca_provenance", "git_dirty"], "false")

        assert "holds a boolean" in result["error"]

    def test_true_into_an_int_field_is_refused(self, producer_h5ad):
        """isinstance(True, int) is True in Python — an int check reached first
        would accept this and store 1."""
        result = _set(producer_h5ad, ["ihbca_provenance", "cell_count"], True)

        assert "holds an integer" in result["error"]
        assert "bool" in result["error"]

    def test_float_into_an_int_field_is_refused(self, producer_h5ad):
        result = _set(producer_h5ad, ["ihbca_provenance", "cell_count"], 7.9)

        assert "holds an integer" in result["error"]

    def test_out_of_range_int_is_refused(self, producer_h5ad):
        """Type alone is not enough: 999 is an int, and int8 cannot hold it."""
        result = _set(producer_h5ad, ["ihbca_provenance", "small_count"], 999)

        assert "int8" in result["error"]

    def test_int_widens_into_a_float_field(self, producer_h5ad):
        """JSON has one number type, so a whole float arrives as an int."""
        result = _set(producer_h5ad, ["ihbca_provenance", "mapping_stats", "pct_mapped"], 90)

        assert "error" not in result, result.get("error")
        value, dtype, _ = _read(result["output_path"], "ihbca_provenance", "mapping_stats", "pct_mapped")
        assert value == pytest.approx(90.0)
        assert dtype == np.dtype(np.float64)
        assert result["updates"][0]["new_value"] == 90.0

    def test_fixed_length_string_field_is_refused(self, producer_h5ad):
        """Refused as a dtype rather than supported. anndata writes every
        string as variable-length, so a fixed-length one was written by
        something else — and HDF5 truncates an over-long value into it with no
        error at all. None of the eight real breast objects has one."""
        result = _set(producer_h5ad, ["ihbca_provenance", "short_code"], "abc")

        assert "fixed-length string" in result["error"]
        assert "truncate" in result["error"]

    def test_fixed_length_refusal_does_not_depend_on_the_value(self, producer_h5ad):
        """Including a non-ASCII one — h5py reports |S as ascii, so encoding it
        to measure a length would raise out of the type check instead of being
        refused by it. Refusing the dtype means never reaching that."""
        result = _set(producer_h5ad, ["ihbca_provenance", "short_code"], "é")

        assert "fixed-length string" in result["error"]

    def test_nan_is_refused(self, producer_h5ad):
        """nan defeats the read-back by construction (nan != nan), and
        json.dumps writes it as the bare token NaN, which is not valid JSON."""
        result = _set(producer_h5ad, ["ihbca_provenance", "mapping_stats", "pct_mapped"], float("nan"))

        assert "not a finite number" in result["error"]

    def test_float_overflow_is_refused(self, producer_h5ad, tmp_path):
        """A finite input that the dtype turns into inf is a wrong value, and
        it would write Infinity into the shared edit log."""
        with h5py.File(producer_h5ad, "a") as f:
            _scalar(f["uns/ihbca_provenance"], "narrow", np.float32(1.5))

        result = _set(producer_h5ad, ["ihbca_provenance", "narrow"], 1e40)

        assert "overflow" in result["error"]
        assert "float32" in result["error"]

    def test_none_is_refused(self, producer_h5ad):
        result = _set(producer_h5ad, ["ihbca_provenance", "git_branch"], None)

        assert "holds a string" in result["error"]


class TestPathGuards:
    """Overwrite-only: every segment must already exist."""

    def test_missing_leaf_is_refused(self, producer_h5ad):
        result = _set(producer_h5ad, ["ihbca_provenance", "git_dity"], "x")

        assert "does not exist" in result["error"]
        assert "does not create them" in result["error"]

    def test_missing_intermediate_is_refused(self, producer_h5ad):
        result = _set(producer_h5ad, ["ihbca_provnance", "git_dirty"], False)

        assert "does not exist" in result["error"]
        assert "ihbca_provnance" in result["error"]

    def test_intermediate_that_is_a_value_is_refused(self, producer_h5ad):
        result = _set(producer_h5ad, ["ihbca_provenance", "git_branch", "deeper"], "x")

        assert "is a value, not a group" in result["error"]

    def test_group_valued_target_is_refused(self, producer_h5ad):
        result = _set(producer_h5ad, ["ihbca_provenance", "mapping_stats"], 1)

        assert "is a group, not a value" in result["error"]

    def test_non_scalar_target_is_refused(self, producer_h5ad):
        result = _set(producer_h5ad, ["ihbca_provenance", "unmapped_examples"], "x")

        assert "not a scalar" in result["error"]

    def test_segment_containing_a_slash_is_refused(self, producer_h5ad):
        """h5py would resolve it as a further link path, so the check that runs
        and the walk that follows could disagree about what was addressed."""
        result = _set(producer_h5ad, ["ihbca_provenance/git_dirty"], False)

        assert "cannot contain '/'" in result["error"]

    def test_slash_joined_string_is_refused_with_the_list_form(self, producer_h5ad):
        result = _set(producer_h5ad, "ihbca_provenance/git_dirty", False)

        assert "must be a list of path segments" in result["error"]
        assert "['ihbca_provenance', 'git_dirty']" in result["error"]


class TestLinks:
    """h5py resolves an external link transparently, so without an explicit
    refusal the walk follows it into another file — and because the snapshot is
    opened "a", HDF5 opens that file read-write and the assignment lands there.
    Verified before the guard existed: the tool reported success, the snapshot
    kept the link unchanged, and a different h5ad was modified. The read-back
    could not catch it; it re-resolves through the same link. These files come
    from third-party producers and from CAP, so the structure is not ours.
    """

    @pytest.fixture
    def victim(self, tmp_path) -> Path:
        path = tmp_path / "victim.h5ad"
        with h5py.File(path, "w") as f:
            group = require_stamped_group(f, "uns/ihbca_provenance")
            _scalar(group, "git_branch", "PRISTINE")
        return path

    def test_linked_namespace_is_refused(self, producer_h5ad, victim, no_snapshot):
        with h5py.File(producer_h5ad, "a") as f:
            del f["uns"]["ihbca_provenance"]
            f["uns"]["ihbca_provenance"] = h5py.ExternalLink(str(victim), "/uns/ihbca_provenance")

        result = _set(producer_h5ad, ["ihbca_provenance", "git_branch"], "TAMPERED")

        assert "external link" in result["error"]
        assert no_snapshot(producer_h5ad)
        with h5py.File(victim, "r") as f:
            assert f["uns/ihbca_provenance/git_branch"][()] == b"PRISTINE"

    def test_linked_leaf_is_refused(self, producer_h5ad, victim, no_snapshot):
        """A single crafted scalar is enough — the walk never sees a group."""
        with h5py.File(producer_h5ad, "a") as f:
            del f["uns"]["ihbca_provenance"]["git_branch"]
            f["uns"]["ihbca_provenance"]["git_branch"] = h5py.ExternalLink(
                str(victim), "/uns/ihbca_provenance/git_branch"
            )

        result = _set(producer_h5ad, ["ihbca_provenance", "git_branch"], "TAMPERED")

        assert "external link" in result["error"]
        assert no_snapshot(producer_h5ad)
        with h5py.File(victim, "r") as f:
            assert f["uns/ihbca_provenance/git_branch"][()] == b"PRISTINE"

    def test_soft_linked_leaf_is_refused(self, producer_h5ad, no_snapshot):
        """A soft link stays inside this file, so the file-identity backstop
        cannot see it — and _namespace_problem cannot either, because it
        matches field[0] as a string and a link never presents the string it
        resolves to. Verified before the guard: this wrote uns['title'], an
        HCA schema field, straight through the producer tool."""
        with h5py.File(producer_h5ad, "a") as f:
            del f["uns"]["ihbca_provenance"]["git_branch"]
            f["uns"]["ihbca_provenance"]["git_branch"] = h5py.SoftLink("/uns/title")

        result = _set(producer_h5ad, ["ihbca_provenance", "git_branch"], "HIJACKED")

        assert "soft link" in result["error"]
        assert no_snapshot(producer_h5ad)
        with h5py.File(producer_h5ad, "r") as f:
            assert f["uns/title"][()] != b"HIJACKED"

    def test_soft_linked_group_is_refused(self, producer_h5ad, no_snapshot):
        """The same at an intermediate segment, not just the leaf."""
        with h5py.File(producer_h5ad, "a") as f:
            f["uns"]["aliased"] = h5py.SoftLink("/uns/ihbca_provenance")

        result = _set(producer_h5ad, ["aliased", "git_branch"], "HIJACKED")

        assert "soft link" in result["error"]
        assert no_snapshot(producer_h5ad)

    def test_linked_leaf_is_not_read_either(self, producer_h5ad, victim):
        """The refusal also closes the read side: old_value travels back in the
        MCP response, so following a link would leak a foreign file's scalar."""
        with h5py.File(producer_h5ad, "a") as f:
            del f["uns"]["ihbca_provenance"]["git_branch"]
            f["uns"]["ihbca_provenance"]["git_branch"] = h5py.ExternalLink(
                str(victim), "/uns/ihbca_provenance/git_branch"
            )

        result = _set(producer_h5ad, ["ihbca_provenance", "git_branch"], "TAMPERED")

        assert "PRISTINE" not in str(result)


class TestOwnership:
    """Paths this tool does not own."""

    def test_hca_schema_field_is_refused_and_names_set_uns(self, producer_h5ad):
        result = _set(producer_h5ad, ["title"], "New title")

        assert "HCA schema uns field" in result["error"]
        assert "set_uns" in result["error"]

    def test_our_provenance_namespace_is_refused(self, producer_h5ad):
        """The edit log lives there; a tool that could rewrite it would undo
        every other tool's guarantee."""
        result = _set(producer_h5ad, ["provenance", "edit_history"], "[]")

        assert "provenance namespace" in result["error"]
        assert "edit log" in result["error"]


class TestRefusesBeforeCopying:
    """The expensive half is the snapshot copy — up to 27 GB. Anything
    knowable from the source read-only should refuse before paying it."""

    def test_provenance_as_a_value_refuses_before_the_copy(self, producer_h5ad, no_snapshot):
        """#576: uns['provenance'] is unnamespaced and shared with producers.
        One that used it for a string would otherwise get a raw h5py
        'Incompatible object' error after the whole file had been copied."""
        with h5py.File(producer_h5ad, "a") as f:
            if "provenance" in f["uns"]:
                del f["uns"]["provenance"]
            _stamp(f["uns"].create_dataset("provenance", data="a producer put a string here"), "string")

        result = _set(producer_h5ad, ["ihbca_provenance", "git_branch"], "main")

        assert result["error"].startswith("Refusing to write:")
        assert "edit log is written inside it" in result["error"]
        assert no_snapshot(producer_h5ad)

    def test_corrupt_edit_log_refuses_before_the_copy(self, producer_h5ad, no_snapshot):
        with h5py.File(producer_h5ad, "a") as f:
            prov = f["uns"].require_group("provenance")
            if "edit_history" in prov:
                del prov["edit_history"]
            _stamp(prov, "dict")
            _stamp(prov.create_dataset("edit_history", data="{not json"), "string")

        result = _set(producer_h5ad, ["ihbca_provenance", "git_branch"], "main")

        assert "error" in result
        assert no_snapshot(producer_h5ad)


class TestAllOrNothing:
    def test_one_bad_entry_leaves_the_file_untouched(self, producer_h5ad, no_snapshot):
        before = producer_h5ad.read_bytes()

        result = set_producer_uns(
            str(producer_h5ad),
            [
                {"field": ["ihbca_provenance", "git_branch"], "value": "main"},
                {"field": ["ihbca_provenance", "git_dirty"], "value": "false"},
            ],
        )

        assert "error" in result
        assert producer_h5ad.read_bytes() == before
        assert no_snapshot(producer_h5ad)

    def test_every_problem_is_reported_in_one_pass(self, producer_h5ad):
        result = set_producer_uns(
            str(producer_h5ad),
            [
                {"field": ["ihbca_provenance", "nope"], "value": "x"},
                {"field": ["ihbca_provenance", "git_dirty"], "value": "false"},
            ],
        )

        assert "does not exist" in result["error"]
        assert "holds a boolean" in result["error"]

    def test_duplicate_field_is_refused(self, producer_h5ad):
        result = set_producer_uns(
            str(producer_h5ad),
            [
                {"field": ["ihbca_provenance", "git_branch"], "value": "main"},
                {"field": ["ihbca_provenance", "git_branch"], "value": "dev"},
            ],
        )

        assert "more than once" in result["error"]


class TestRequestShape:
    def test_empty_updates_is_refused(self, producer_h5ad):
        assert "must not be empty" in set_producer_uns(str(producer_h5ad), [])["error"]

    def test_non_list_updates_is_refused(self, producer_h5ad):
        assert "must be a list" in set_producer_uns(str(producer_h5ad), {"field": ["a"], "value": 1})["error"]

    def test_entry_missing_a_key_is_refused(self, producer_h5ad):
        result = set_producer_uns(str(producer_h5ad), [{"field": ["ihbca_provenance", "git_dirty"]}])

        assert "missing ['value']" in result["error"]

    def test_non_string_segments_are_refused(self, producer_h5ad):
        result = _set(producer_h5ad, ["ihbca_provenance", 3], 1)

        assert "segments must be strings" in result["error"]

    def test_missing_file_is_reported(self, tmp_path):
        result = set_producer_uns(str(tmp_path / "nope.h5ad"), THE_CORRECTION)

        assert "File not found" in result["error"]

    def test_file_with_no_uns_group_is_refused(self, producer_h5ad):
        with h5py.File(producer_h5ad, "a") as f:
            del f["uns"]

        result = set_producer_uns(str(producer_h5ad), THE_CORRECTION)

        assert "no uns group" in result["error"]


class TestRedirectStaysHonest:
    """set_producer_uns refuses HCA registry roots and tells the caller to use
    set_uns. That advice is only good while set_uns can actually handle every
    field it refuses — set_uns takes ``str | list[str]`` at the top level only.
    The first registry field that is a scalar bool/int, or nested, would be
    reachable by neither tool, and the caller would follow the redirect into a
    second refusal. Pin it here so a schema change fails a test, not a curator.
    """

    def test_every_registry_field_is_flat_and_set_uns_typed(self):
        unreachable = {
            name: info.annotation
            for name, info in uns_field_registry().items()
            if _type_display(info.annotation) not in {"str", "list[str]"}
        }
        assert not unreachable, (
            f"these HCA uns fields are refused by set_producer_uns but set_uns cannot take them, "
            f"so the 'use set_uns' redirect is a dead end: {unreachable}"
        )


class TestSharedWithListUnsFields:
    """The point of #631: what list_uns_fields reports as an editable producer
    key and what set_producer_uns refuses are complements of one set. Computed
    separately they could drift, and the drift would be silent — a curator told
    to fix something the tools then refuse to touch."""

    @pytest.fixture
    def readable_h5ad(self, sample_h5ad_for_write: Path) -> Path:
        """A file carrying one root of each kind, that anndata can read.

        The main ``producer_h5ad`` fixture carries a fixed-length ``|S3``
        field, and anndata cannot read one of those in ``uns`` at all — it
        raises ``string indices must be integers``, so ``list_uns_fields``
        returns an error rather than a report (#632). That is exactly why
        ``set_producer_uns`` refuses the dtype; here it just means these tests
        need a file both consumers can open.
        """
        with h5py.File(sample_h5ad_for_write, "a") as f:
            _scalar(require_stamped_group(f, "uns/ihbca_provenance"), "git_branch", "dev")
            write_edit_log_h5py(f, "[]")
        return sample_h5ad_for_write

    def test_a_new_reserved_root_moves_both_consumers(self, readable_h5ad, monkeypatch):
        """Add a root to the shared derivation; both consumers must follow it.

        Patches each consumer's bound name rather than the registry: that is
        what pins the *sharing*, because monkeypatch.setattr raises if a
        consumer stopped importing the shared derivation. Patching the registry
        instead would reach a reintroduced local copy just as well, and prove
        only that each consumer reads the registry.
        """
        from hca_anndata_tools import edit, producer_uns
        from hca_anndata_tools.schema import helpers

        assert "ihbca_provenance" in list_uns_fields(str(readable_h5ad))["extra_uns_keys"]
        assert "error" not in _set(readable_h5ad, ["ihbca_provenance", "git_branch"], "main")

        def extended():
            return helpers.non_producer_uns_roots() | {"ihbca_provenance"}

        monkeypatch.setattr(edit, "non_producer_uns_roots", extended)
        monkeypatch.setattr(producer_uns, "non_producer_uns_roots", extended)

        assert "ihbca_provenance" not in list_uns_fields(str(readable_h5ad))["extra_uns_keys"]
        error = _set(readable_h5ad, ["ihbca_provenance", "git_branch"], "main")["error"]
        # Truthfully, too: a root reserved for a third reason must not inherit
        # the set_uns redirect, which would send a curator to a tool that then
        # rejects it as unknown.
        assert "reserved uns root" in error
        assert "set_uns" not in error
