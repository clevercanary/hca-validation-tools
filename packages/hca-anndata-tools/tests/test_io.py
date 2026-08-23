"""Tests for the _io helpers that narrow uns access (#617)."""

import h5py
import pytest

from hca_anndata_tools._io import (
    read_batch_condition,
    read_edit_log_h5py,
    read_provenance,
    read_uns,
    require_stamped_group,
)
from hca_anndata_tools.inspect import _read_schema_version


@pytest.fixture
def h5(tmp_path):
    with h5py.File(tmp_path / "f.h5", "a") as f:
        yield f


def test_read_uns_absent(h5):
    assert read_uns(h5) is None


def test_read_uns_group(h5):
    group = h5.create_group("uns")
    assert read_uns(h5) == group


def test_read_uns_dataset(h5):
    """A scalar Dataset at 'uns' is the malformed shape that made membership
    tests raise TypeError and attribute access raise AttributeError."""
    h5["uns"] = "not a group"
    assert read_uns(h5) is None


def test_require_stamped_group_stamps_a_new_group(h5):
    group = require_stamped_group(h5, "uns")
    assert isinstance(group, h5py.Group)
    assert group.attrs["encoding-type"] == "dict"
    assert group.attrs["encoding-version"] == "0.1.0"


def test_require_stamped_group_preserves_existing_attrs(h5):
    """setdefault semantics: an already-stamped group keeps its attrs, so a
    re-run never rewrites what anndata wrote."""
    h5.create_group("uns").attrs["encoding-version"] = "0.2.0"

    group = require_stamped_group(h5, "uns")

    assert group.attrs["encoding-version"] == "0.2.0"
    assert group.attrs["encoding-type"] == "dict"  # missing attr still filled


def test_read_batch_condition_none():
    assert read_batch_condition(None) == []


def test_read_batch_condition_absent(h5):
    assert read_batch_condition(h5.create_group("uns")) == []


def test_read_batch_condition_array(h5):
    uns = h5.create_group("uns")
    uns.create_dataset("batch_condition", data=["donor_id", "sample_id"])
    assert read_batch_condition(uns) == ["donor_id", "sample_id"]


def test_read_batch_condition_scalar(h5):
    uns = h5.create_group("uns")
    uns["batch_condition"] = "donor_id"
    assert read_batch_condition(uns) == ["donor_id"]


def test_read_provenance_none():
    assert read_provenance(None) is None


def test_read_provenance_absent(h5):
    assert read_provenance(h5.create_group("uns")) is None


def test_read_provenance_dataset(h5):
    uns = h5.create_group("uns")
    uns["provenance"] = "not a group"
    assert read_provenance(uns) is None


def test_read_provenance_group(h5):
    prov = h5.create_group("uns/provenance")
    assert read_provenance(h5["uns"]) == prov


def test_read_edit_log_group_at_edit_history(h5):
    """A Group at uns/provenance/edit_history is narrowed to the no-log
    answer instead of raising through every caller."""
    h5.create_group("uns/provenance/edit_history")

    assert read_edit_log_h5py(h5) == "[]"


def test_read_edit_log_numeric_at_edit_history(h5):
    """A numeric scalar there is not a log either — narrowed to "[]" rather
    than handing a float to json.loads downstream."""
    h5.create_group("uns/provenance")["edit_history"] = 3.14

    assert read_edit_log_h5py(h5) == "[]"


def test_read_schema_version_group_at_leaf(h5):
    """A Group at uns['schema_version'] is narrowed to None instead of
    raising TypeError from the scalar read."""
    h5.create_group("uns/schema_version")

    assert _read_schema_version(h5) is None
