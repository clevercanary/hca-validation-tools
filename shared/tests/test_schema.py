"""
Test script for schema functionality.
"""

import pytest

import hca_validation.schema.generated.core as schema
from hca_validation.schema_utils.schema_utils import (
    coverage_classes,
    get_slot_anndata_location,
    load_schemaview,
    schema_classes,
)


@pytest.fixture(scope="module")
def schemaview():
    """Shared across the module because `class_induced_slots` is the expensive part —
    linkml_runtime memoizes it per SchemaView instance, so a fresh instance per test
    re-pays roughly 40ms per class. Mirrors the fixture in the dataset-validator's
    coverage tests."""
    return load_schemaview()


def test_schemaview_classes(schemaview):
    """
    Test that all classes in the mapping exist in the schema when loaded as a schemaview.
    """
    for classes in schema_classes.values():
        for class_name in classes.values():
            print(class_name)
            assert schemaview.get_class(class_name) is not None


def test_generated_classes():
    """
    Test that all classes in the mapping exist in the exported Pydantic schema.
    """
    for classes in schema_classes.values():
        for class_name in classes.values():
            assert hasattr(schema, class_name)


# Columns that live in obs and that consumers discover by walking the schema for an
# `annDataLocation: obs` annotation. Before #538 these four were invisible to that walk:
# the Cell pair had no home in the model at all, and the Sample pair carried no
# annotation.
#
# The consumer that motivated this is `drop_obs_columns` (#531, landing in #539), whose
# delete guard refuses any column the schema names — so while these four were invisible
# it would happily delete columns the h5ad validator requires. Note that tool is not on
# `main` yet, so grepping for it here will come up empty until #539 merges; the other
# reader of this annotation today is `iter_coverage_slots` in schema_utils.
_OBS_ANNOTATED_SLOTS = [
    ("Cell", "author_cell_type"),
    ("Cell", "cell_type_ontology_term_id"),
    ("Sample", "is_primary_data"),
    ("Sample", "sample_collection_method"),
]


@pytest.mark.parametrize(("class_name", "slot_name"), _OBS_ANNOTATED_SLOTS)
def test_obs_slots_carry_anndata_location(schemaview, class_name, slot_name):
    """Regression guard for #538.

    Asserted through `get_slot_anndata_location` rather than by reading the YAML,
    because that resolution is the thing consumers depend on — a slot can be declared
    correctly and still fail to induce onto its class.
    """
    slots = {s.name: s for s in schemaview.class_induced_slots(class_name)}
    assert slot_name in slots, f"{slot_name} does not induce onto {class_name}"
    assert get_slot_anndata_location(slots[slot_name]) == "obs"


def test_cell_class_excluded_from_coverage(schemaview):
    """Cell has slots as of #538, so its exclusion from coverage is now a deliberate
    choice rather than a side effect of the class being empty. See `coverage_classes`
    in schema_utils for why it stays excluded and when to remove it.
    """
    assert schemaview.class_induced_slots("Cell"), "Cell should have slots after #538"
    assert "Cell" not in coverage_classes(schemaview)


def test_is_primary_data_is_no_longer_a_deprecated_placeholder():
    """#538 restored it to a real boolean slot. It stays optional until entry sheets
    carry the column (#544) — LinkML's `required` is enforced against entry sheet rows,
    so flipping it would fail every sheet lacking it."""
    field = schema.Sample.model_fields["is_primary_data"]
    assert field.annotation == (bool | None), field.annotation
    assert not field.is_required()
