"""
Tests for data dictionary generation, in particular the folding of bionetwork subclass slots
into their base class with a `bioNetworks` annotation.
"""

import textwrap

import pytest
from linkml_runtime import SchemaView

from hca_validation.data_dictionary.generate_dictionary import transform_schema_to_data_dictionary
from hca_validation.schema_utils.schema_utils import load_schemaview


@pytest.fixture(scope="module")
def data_dictionary():
    return transform_schema_to_data_dictionary(load_schemaview())


def _attribute(data_dictionary, class_name, attribute_name):
    entity_class = next(c for c in data_dictionary["classes"] if c["name"] == class_name)
    return next(a for a in entity_class["attributes"] if a["name"] == attribute_name)


def _schemaview(tmp_path, classes):
    """Build a SchemaView for a small schema with a Dataset base class and the given subclasses."""
    schema = textwrap.dedent(
        """
        id: https://example.org/test
        name: test
        prefixes:
          linkml: https://w3id.org/linkml/
        default_range: string
        imports:
          - linkml:types
        enums:
          BioNetwork:
            permissible_values:
              gut: {}
              heart: {}
              lung: {}
        slots:
          title:
            required: true
          shared_field:
            required: true
          gut_field: {}
        classes:
          Dataset:
            slots:
              - title
        """
    ) + textwrap.indent(textwrap.dedent(classes), "  ")
    path = tmp_path / "schema.yaml"
    path.write_text(schema)
    return SchemaView(str(path))


# The four slots only bionetwork subclasses add, as the HCA Data Portal's tier-1.json scopes them.
@pytest.mark.parametrize(
    ("class_name", "attribute_name", "networks"),
    [
        ("dataset", "ambient_count_correction", ["adipose", "gut", "musculoskeletal"]),
        ("dataset", "doublet_detection", ["adipose", "gut", "musculoskeletal"]),
        ("sample", "radial_tissue_term", ["gut"]),
        ("sample", "dissociation_protocol", ["adipose", "gut"]),
    ],
)
def test_bionetwork_slots_are_folded(data_dictionary, class_name, attribute_name, networks):
    attribute = _attribute(data_dictionary, class_name, attribute_name)
    assert attribute["annotations"]["bioNetworks"] == networks
    assert attribute["required"] is True


def test_core_slots_have_every_network(data_dictionary):
    networks = _attribute(data_dictionary, "dataset", "title")["annotations"]["bioNetworks"]
    assert len(networks) == 18
    assert "oral-and-craniofacial" in networks
    assert networks == sorted(networks)


def test_every_attribute_has_bionetworks(data_dictionary):
    for entity_class in data_dictionary["classes"]:
        for attribute in entity_class["attributes"]:
            assert attribute["annotations"]["bioNetworks"], f"{entity_class['name']}.{attribute['name']}"


def test_attributes_stay_sorted_by_name(data_dictionary):
    for entity_class in data_dictionary["classes"]:
        names = [attribute["name"] for attribute in entity_class["attributes"]]
        assert names == sorted(names), entity_class["name"]


def test_slot_added_by_several_subclasses_is_folded_once(tmp_path):
    schemaview = _schemaview(
        tmp_path,
        """
        LungDataset:
          is_a: Dataset
          annotations:
            bioNetwork: lung
          slots:
            - shared_field
        GutDataset:
          is_a: Dataset
          annotations:
            bioNetwork: gut
          slots:
            - shared_field
            - gut_field
        """,
    )
    (dataset,) = transform_schema_to_data_dictionary(schemaview)["classes"]
    by_name = {attribute["name"]: attribute for attribute in dataset["attributes"]}

    assert list(by_name) == ["gut_field", "shared_field", "title"]
    assert by_name["shared_field"]["annotations"]["bioNetworks"] == ["gut", "lung"]
    assert by_name["shared_field"]["required"] is True
    assert by_name["gut_field"]["annotations"]["bioNetworks"] == ["gut"]
    assert by_name["title"]["annotations"]["bioNetworks"] == ["gut", "heart", "lung"]


def test_unknown_bionetwork_key_is_refused(tmp_path):
    schemaview = _schemaview(
        tmp_path,
        """
        GutDataset:
          is_a: Dataset
          annotations:
            bioNetwork: guts
          slots:
            - gut_field
        """,
    )
    with pytest.raises(ValueError, match="'guts', which is not in the BioNetwork enum"):
        transform_schema_to_data_dictionary(schemaview)


def test_subclass_without_bionetwork_is_refused(tmp_path):
    schemaview = _schemaview(
        tmp_path,
        """
        GutDataset:
          is_a: Dataset
          slots:
            - gut_field
        """,
    )
    with pytest.raises(ValueError, match="GutDataset extends Dataset but has no bioNetwork annotation"):
        transform_schema_to_data_dictionary(schemaview)


def test_conflicting_definitions_are_refused(tmp_path):
    schemaview = _schemaview(
        tmp_path,
        """
        LungDataset:
          is_a: Dataset
          annotations:
            bioNetwork: lung
          slots:
            - gut_field
        GutDataset:
          is_a: Dataset
          annotations:
            bioNetwork: gut
          slots:
            - gut_field
          slot_usage:
            gut_field:
              required: true
        """,
    )
    with pytest.raises(ValueError, match="define 'gut_field' differently"):
        transform_schema_to_data_dictionary(schemaview)
