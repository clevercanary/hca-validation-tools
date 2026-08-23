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
            assert schemaview.get_class(class_name) is not None, f"{class_name} missing from schemaview"


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
# The consumer that motivated this was `drop_obs_columns`' schema guard (#531/#539),
# removed in #619 when guards were rescoped to coherence-only (#614). The annotation
# itself stays load-bearing: `iter_coverage_slots` in schema_utils reads it.
_OBS_ANNOTATED_SLOTS = [
    ("Cell", "author_cell_type"),
    ("Cell", "cell_type_ontology_term_id"),
    ("Sample", "is_primary_data"),
    ("Sample", "sample_collection_method"),
]


# A Sample row that satisfies every required slot, so a test can vary one field and be
# sure any failure came from that field. The models set `extra = "forbid"`, so this must
# name only declared slots.
_MINIMAL_SAMPLE = {
    "sample_id": "S1",
    "donor_id": "D1",
    "dataset_id": "DS1",
    "institute": "X",
    "cell_enrichment": "na",
    "library_id": "L1",
    "library_preparation_batch": "b1",
    "library_sequencing_run": "r1",
    "sample_collection_method": "biopsy",
    "sample_preservation_method": "fresh",
    "sample_source": "surgical donor",
    "sampled_site_condition": "healthy",
    "suspension_type": "cell",
    "tissue_type": "tissue",
    "tissue_ontology_term_id": "UBERON:0000955",
    "disease_ontology_term_id": "PATO:0000461",
    "development_stage_ontology_term_id": "HsapDv:0000237",
}


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


def test_is_primary_data_stays_sheet_inert():
    """#538 annotated `is_primary_data` but deliberately left it a deprecated_slot.

    This is the load-bearing property: entry sheet validation runs
    `Sample.model_validate(row_dict)` on data taken straight from sheet columns, so the
    slot's `range` decides what curators may type. As an unconstrained string it accepts
    anything, including the "na" convention this schema documents elsewhere
    (`cell_enrichment`, `suspension_type`). Giving it `range: boolean` would start
    rejecting those values, so sheets that validate today would begin failing.

    Annotations are inert for validation, which is what lets the obs annotation coexist
    with the placeholder — see the slot's comments and #544.
    """
    assert not schema.Sample.model_fields["is_primary_data"].is_required()

    # The behavioural check, and the one that matters: these are the values a sheet
    # might plausibly carry, and all of them must still pass. This also subsumes an
    # annotation-equality assertion — if the slot regained `range: boolean`, "na",
    # "unknown" and "primary" would each raise here.
    for value in ("TRUE", "true", "na", "unknown", "primary", None):
        assert schema.Sample.model_validate({**_MINIMAL_SAMPLE, "is_primary_data": value}), (
            f"{value!r} should be accepted"
        )
