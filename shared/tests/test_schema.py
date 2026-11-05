"""
Test script for schema functionality.
"""

import hca_metadata_schema.generated.core as schema
import pytest
from pydantic import ValidationError

from hca_validation.schema_utils.schema_utils import (
    coverage_classes,
    get_bionetwork_keys,
    get_class_bionetwork,
    get_slot_anndata_location,
    schema_classes,
)


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


def _bionetwork_annotations(schemaview):
    """Map every class carrying a `bioNetwork` annotation, at any depth, to its network."""
    annotated = {}
    for class_name, class_info in schemaview.all_classes().items():
        network = get_class_bionetwork(class_info)
        if network is not None:
            annotated[class_name] = network
    return annotated


def test_bionetwork_annotations_are_enum_keys(schemaview):
    """Every subclass's `bioNetwork` annotation is a key of the BioNetwork enum."""
    keys = get_bionetwork_keys(schemaview)
    annotated = _bionetwork_annotations(schemaview)
    assert annotated, "no class carries a bioNetwork annotation"
    for class_name, network in annotated.items():
        assert network in keys, f"{class_name} has bioNetwork {network!r}, not a BioNetwork key"


def test_generated_bionetwork_enum_matches_schema(schemaview):
    """The generated `BioNetwork` the entry-sheet validator checks against is current with `enums.yaml`."""
    assert sorted(network.value for network in schema.BioNetwork) == get_bionetwork_keys(schemaview)


def test_bionetwork_annotations_match_schema_classes(schemaview):
    """`schema_classes` and the `bioNetwork` annotations name the same subclass for each network.

    The two record the same fact; until one is derived from the other, this keeps them from drifting.
    """
    from_schema_classes = {
        class_name: network
        for classes in schema_classes.values()
        for network, class_name in classes.items()
        if network != "DEFAULT"
    }
    assert _bionetwork_annotations(schemaview) == from_schema_classes


# The schema version checks (one version, in core.yaml, mirrored everywhere release-please bumps it)
# live with the schema, in packages/hca-metadata-schema/tests/.


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
    ("Sample", "sample_collection_method"),
    # #604: in obs in the tracker's h5ad files, the six deprecated ones included.
    ("Dataset", "publication_doi"),
    ("Dataset", "contact_email"),
    ("Dataset", "consortia"),
    ("Dataset", "assay_ontology_term"),
    ("Donor", "sex_ontology_term"),
    ("Sample", "age_range"),
    ("Sample", "tissue_ontology_term"),
    ("Sample", "disease_ontology_term"),
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


@pytest.mark.parametrize("model", [schema.Sample, schema.AdiposeSample, schema.GutSample])
@pytest.mark.parametrize("slot_name", ["library_preparation_batch", "library_sequencing_run"])
def test_library_slots_are_optional_on_sheets(model, slot_name):
    """#761: `recommended: true` has no Pydantic warning level, so on entry sheets these are simply optional."""
    assert not model.model_fields[slot_name].is_required()


@pytest.mark.parametrize("slot_name", ["library_preparation_batch", "library_sequencing_run"])
def test_sample_validates_with_or_without_library_slots(slot_name):
    assert schema.Sample.model_validate(_MINIMAL_SAMPLE)
    assert schema.Sample.model_validate({**_MINIMAL_SAMPLE, slot_name: "b1"})


def test_sample_rejects_is_primary_data():
    """#836 removed the slot: it is a CELLxGENE field with no HCA meaning, so a sheet column of that name is unknown."""
    with pytest.raises(ValidationError) as excinfo:
        schema.Sample.model_validate({**_MINIMAL_SAMPLE, "is_primary_data": "TRUE"})
    assert [(e["type"], e["loc"]) for e in excinfo.value.errors()] == [("extra_forbidden", ("is_primary_data",))]
