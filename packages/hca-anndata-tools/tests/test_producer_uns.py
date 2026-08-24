"""Tests for set_producer_uns — writing scalars into producer-owned uns namespaces.

Every assertion on a written value also asserts its dtype. That is the point of
the tool: a producer namespace has no schema, so ``validate_schema`` has no
opinion on it, and a test that checked the value alone would pass on exactly
the mis-write this exists to prevent (a bool stored as the string 'false').
"""

import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from hca_anndata_tools import set_producer_uns, view_edit_log
from hca_anndata_tools._io import require_stamped_group


def _scalar(group: h5py.Group, name: str, value) -> None:
    """Create a scalar dataset stamped the way anndata stamps one."""
    group.create_dataset(name, data=value)
    encoding = "string" if isinstance(value, str) else "numeric-scalar"
    group[name].attrs["encoding-type"] = encoding
    group[name].attrs["encoding-version"] = "0.2.0"


@pytest.fixture
def producer_h5ad(sample_h5ad_for_write: Path) -> Path:
    """A file carrying a nested producer namespace shaped like the real one.

    Mirrors ``uns['ihbca_provenance']`` on the breast-v1 source datasets: a
    variable-length string, a bool, an int, a nested subgroup with a float,
    plus a fixed-length string and a non-scalar array as the shapes the tool
    has to refuse.
    """
    with h5py.File(sample_h5ad_for_write, "a") as f:
        group = require_stamped_group(f, "uns/ihbca_provenance")
        _scalar(group, "git_branch", "dev")
        _scalar(group, "git_hash", "f78d0212f9d8bd86e3cbbb47a269a33981346956")
        _scalar(group, "git_dirty", True)
        _scalar(group, "cell_count", np.int64(52681))
        _scalar(group, "small_count", np.int8(5))
        group.create_dataset("short_code", data=np.bytes_("dev"))
        group.create_dataset("unmapped_examples", data=np.array([b"ENSG1", b"ENSG2"]))
        nested = require_stamped_group(f, "uns/ihbca_provenance/mapping_stats")
        _scalar(nested, "pct_mapped", np.float64(90.385))
    return sample_h5ad_for_write


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        result = set_producer_uns(
            str(producer_h5ad),
            [{"field": ["ihbca_provenance", "mapping_stats", "pct_mapped"], "value": 91.5}],
        )

        assert "error" not in result, result.get("error")
        value, dtype, _ = _read(result["output_path"], "ihbca_provenance", "mapping_stats", "pct_mapped")
        assert value == pytest.approx(91.5)
        assert dtype == np.dtype(np.float64)


class TestTypeGuards:
    """The stored dtype is the contract; nothing downstream would catch a breach."""

    def test_bool_into_a_string_field_is_refused(self, producer_h5ad):
        result = set_producer_uns(str(producer_h5ad), [{"field": ["ihbca_provenance", "git_branch"], "value": False}])

        assert "holds a string" in result["error"]
        assert "bool" in result["error"]

    def test_string_into_a_bool_field_is_refused(self, producer_h5ad):
        result = set_producer_uns(str(producer_h5ad), [{"field": ["ihbca_provenance", "git_dirty"], "value": "false"}])

        assert "holds a boolean" in result["error"]

    def test_true_into_an_int_field_is_refused(self, producer_h5ad):
        """isinstance(True, int) is True in Python — an int check reached first
        would accept this and store 1."""
        result = set_producer_uns(str(producer_h5ad), [{"field": ["ihbca_provenance", "cell_count"], "value": True}])

        assert "holds an integer" in result["error"]
        assert "bool" in result["error"]

    def test_float_into_an_int_field_is_refused(self, producer_h5ad):
        result = set_producer_uns(str(producer_h5ad), [{"field": ["ihbca_provenance", "cell_count"], "value": 7.9}])

        assert "holds an integer" in result["error"]

    def test_out_of_range_int_is_refused(self, producer_h5ad):
        """Type alone is not enough: 999 is an int, and int8 cannot hold it."""
        result = set_producer_uns(str(producer_h5ad), [{"field": ["ihbca_provenance", "small_count"], "value": 999}])

        assert "int8" in result["error"]

    def test_int_widens_into_a_float_field(self, producer_h5ad):
        """JSON has one number type, so a whole float arrives as an int."""
        result = set_producer_uns(
            str(producer_h5ad),
            [{"field": ["ihbca_provenance", "mapping_stats", "pct_mapped"], "value": 90}],
        )

        assert "error" not in result, result.get("error")
        value, dtype, _ = _read(result["output_path"], "ihbca_provenance", "mapping_stats", "pct_mapped")
        assert value == pytest.approx(90.0)
        assert dtype == np.dtype(np.float64)
        assert result["updates"][0]["new_value"] == 90.0

    def test_fixed_length_string_truncation_is_refused(self, producer_h5ad):
        """HDF5 truncates a too-long value into a fixed-length string and
        reports success — the exact silent mis-write this tool guards."""
        result = set_producer_uns(
            str(producer_h5ad),
            [{"field": ["ihbca_provenance", "short_code"], "value": "a-much-longer-value"}],
        )

        assert "truncate" in result["error"]
        assert "3 bytes" in result["error"]

    def test_none_is_refused(self, producer_h5ad):
        result = set_producer_uns(str(producer_h5ad), [{"field": ["ihbca_provenance", "git_branch"], "value": None}])

        assert "holds a string" in result["error"]


class TestPathGuards:
    """Overwrite-only: every segment must already exist."""

    def test_missing_leaf_is_refused(self, producer_h5ad):
        result = set_producer_uns(str(producer_h5ad), [{"field": ["ihbca_provenance", "git_dity"], "value": "x"}])

        assert "does not exist" in result["error"]
        assert "does not create them" in result["error"]

    def test_missing_intermediate_is_refused(self, producer_h5ad):
        result = set_producer_uns(str(producer_h5ad), [{"field": ["ihbca_provnance", "git_dirty"], "value": False}])

        assert "does not exist" in result["error"]
        assert "ihbca_provnance" in result["error"]

    def test_intermediate_that_is_a_value_is_refused(self, producer_h5ad):
        result = set_producer_uns(
            str(producer_h5ad),
            [{"field": ["ihbca_provenance", "git_branch", "deeper"], "value": "x"}],
        )

        assert "is a value, not a group" in result["error"]

    def test_group_valued_target_is_refused(self, producer_h5ad):
        result = set_producer_uns(str(producer_h5ad), [{"field": ["ihbca_provenance", "mapping_stats"], "value": 1}])

        assert "is a group, not a value" in result["error"]

    def test_non_scalar_target_is_refused(self, producer_h5ad):
        result = set_producer_uns(
            str(producer_h5ad),
            [{"field": ["ihbca_provenance", "unmapped_examples"], "value": "x"}],
        )

        assert "not a scalar" in result["error"]

    def test_segment_containing_a_slash_is_refused(self, producer_h5ad):
        """h5py would resolve it as a further link path, so the check that runs
        and the walk that follows could disagree about what was addressed."""
        result = set_producer_uns(
            str(producer_h5ad),
            [{"field": ["ihbca_provenance/git_dirty"], "value": False}],
        )

        assert "cannot contain '/'" in result["error"]

    def test_slash_joined_string_is_refused_with_the_list_form(self, producer_h5ad):
        result = set_producer_uns(
            str(producer_h5ad),
            [{"field": "ihbca_provenance/git_dirty", "value": False}],
        )

        assert "must be a list of path segments" in result["error"]
        assert "['ihbca_provenance', 'git_dirty']" in result["error"]


class TestOwnership:
    """Paths this tool does not own."""

    def test_hca_schema_field_is_refused_and_names_set_uns(self, producer_h5ad):
        result = set_producer_uns(str(producer_h5ad), [{"field": ["title"], "value": "New title"}])

        assert "HCA schema uns field" in result["error"]
        assert "set_uns" in result["error"]

    def test_our_provenance_namespace_is_refused(self, producer_h5ad):
        """The edit log lives there; a tool that could rewrite it would undo
        every other tool's guarantee."""
        result = set_producer_uns(
            str(producer_h5ad),
            [{"field": ["provenance", "edit_history"], "value": "[]"}],
        )

        assert "provenance namespace" in result["error"]
        assert "edit log" in result["error"]


class TestAllOrNothing:
    def test_one_bad_entry_leaves_the_file_untouched(self, producer_h5ad):
        before = _sha256(producer_h5ad)

        result = set_producer_uns(
            str(producer_h5ad),
            [
                {"field": ["ihbca_provenance", "git_branch"], "value": "main"},
                {"field": ["ihbca_provenance", "git_dirty"], "value": "false"},
            ],
        )

        assert "error" in result
        assert _sha256(producer_h5ad) == before
        assert sorted(p.name for p in producer_h5ad.parent.glob("*.h5ad")) == [producer_h5ad.name]

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
        result = set_producer_uns(str(producer_h5ad), [{"field": ["ihbca_provenance", 3], "value": 1}])

        assert "segments must be strings" in result["error"]

    def test_missing_file_is_reported(self, tmp_path):
        result = set_producer_uns(str(tmp_path / "nope.h5ad"), THE_CORRECTION)

        assert "File not found" in result["error"]

    def test_file_with_no_uns_group_is_refused(self, producer_h5ad):
        with h5py.File(producer_h5ad, "a") as f:
            del f["uns"]

        result = set_producer_uns(str(producer_h5ad), THE_CORRECTION)

        assert "no uns group" in result["error"]
