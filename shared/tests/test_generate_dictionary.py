"""
Tests for data dictionary generation: the folding of bionetwork subclass slots into their base class with a
`bioNetworks` annotation, and (#548) how a slot maps to an attribute, pinned against a small fixed schema.
"""

import json
import textwrap

import pytest
from linkml_runtime import SchemaView

from hca_validation.data_dictionary.generate_dictionary import generate_dictionary, transform_schema_to_data_dictionary


@pytest.fixture(scope="module")
def data_dictionary(schemaview):
    return transform_schema_to_data_dictionary(schemaview)


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
# The two Dataset slots have no tier yet (#760), so their tier is not checked.
@pytest.mark.parametrize(
    ("class_name", "attribute_name", "networks", "tier"),
    [
        ("dataset", "ambient_count_correction", ["adipose", "gut", "musculoskeletal"], None),
        ("dataset", "doublet_detection", ["adipose", "gut", "musculoskeletal"], None),
        ("sample", "radial_tissue_term", ["gut"], "Tier 1"),
        ("sample", "dissociation_protocol", ["adipose", "gut"], "Tier 1"),
    ],
)
def test_bionetwork_slots_are_folded(data_dictionary, class_name, attribute_name, networks, tier):
    attribute = _attribute(data_dictionary, class_name, attribute_name)
    assert attribute["annotations"]["bioNetworks"] == networks
    assert attribute["annotations"]["annDataLocation"] == "obs"
    if tier is not None:
        assert attribute["annotations"]["tier"] == tier
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


# Fields the dictionary may emit without an annDataLocation: dataset_id is Dataset's identifier
# and Donor's and Sample's foreign key, and the tracker supplies it rather than the h5ad
_UNLOCATED_ATTRIBUTES = {"dataset_id"}


def test_every_attribute_has_anndata_location(data_dictionary):
    missing = [
        f"{entity_class['name']}.{attribute['name']}"
        for entity_class in data_dictionary["classes"]
        for attribute in entity_class["attributes"]
        if attribute["name"] not in _UNLOCATED_ATTRIBUTES
        and attribute["annotations"].get("annDataLocation") not in {"obs", "uns"}
    ]
    assert not missing, f"no annDataLocation of obs or uns: {', '.join(missing)}"


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


def test_changed_base_slot_is_refused(tmp_path):
    schemaview = _schemaview(
        tmp_path,
        """
        GutDataset:
          is_a: Dataset
          annotations:
            bioNetwork: gut
          slot_usage:
            title:
              required: false
        """,
    )
    with pytest.raises(ValueError, match="GutDataset changes Dataset's 'title'"):
        transform_schema_to_data_dictionary(schemaview)


# The dictionary doesn't show `pattern`, so these differences are invisible in its output and must still be refused
def test_base_slot_pattern_change_is_refused(tmp_path):
    schemaview = _schemaview(
        tmp_path,
        """
        GutDataset:
          is_a: Dataset
          annotations:
            bioNetwork: gut
          slot_usage:
            title:
              pattern: "^G"
        """,
    )
    with pytest.raises(ValueError, match="GutDataset changes Dataset's 'title'"):
        transform_schema_to_data_dictionary(schemaview)


def test_conflicting_patterns_are_refused(tmp_path):
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
              pattern: "^G"
        """,
    )
    with pytest.raises(ValueError, match="define 'gut_field' differently"):
        transform_schema_to_data_dictionary(schemaview)


@pytest.mark.parametrize(
    "classes",
    [
        pytest.param(
            """
            NetworkDataset:
              is_a: Dataset
              abstract: true
            GutDataset:
              is_a: NetworkDataset
              annotations:
                bioNetwork: gut
              slots:
                - gut_field
            """,
            id="abstract-intermediate",
        ),
        pytest.param(
            """
            GutDataset:
              is_a: Dataset
              annotations:
                bioNetwork: gut
            GutPediatricDataset:
              is_a: GutDataset
              annotations:
                bioNetwork: gut
              slots:
                - gut_field
            """,
            id="grandchild",
        ),
    ],
)
def test_indirect_subclass_is_refused(tmp_path, classes):
    schemaview = _schemaview(tmp_path, classes)
    with pytest.raises(ValueError, match="is not a direct, concrete subclass of Dataset"):
        transform_schema_to_data_dictionary(schemaview)


# Slot-to-attribute mapping (#548). These run against a small schema written to a temporary directory rather
# than core.yaml, so they pin the generator's behaviour and do not move when the real schema changes. That the
# committed dictionary matches core.yaml is CI's generated-schema job.

_MAPPING_SCHEMA = """
id: https://example.org/dictionary-test
name: dictionary_test
prefixes:
  linkml: https://w3id.org/linkml/
imports:
  - linkml:types

enums:
  BioNetwork:
    permissible_values:
      gut:
      heart:
  Colour:
    permissible_values:
      red:
      blue:

slots:
  title:
    title: Title
    description: The dataset title.
    required: true
    examples:
      - value: first example
      - value: second example
    annotations:
      annDataLocation: uns
      cxg: title
  rationale_slot:
    comments:
      - First comment.
      - Second comment.
    notes:
      - First note.
      - Second note.
  bare:
  colour:
    range: Colour
    notes:
      - Replaced by the enum values.
  donor_id:
    multivalued: true

classes:
  Dataset:
    description: A dataset.
    slots:
      - title
      - rationale_slot
      - bare
      - colour
  Donor:
    slots:
      - donor_id
  Base:
    abstract: true
    slots:
      - bare
  # Sample and Cell are included classes, so an abstract one must still be skipped.
  Sample:
    abstract: true
    slots:
      - bare
  Unlisted:
    slots:
      - bare
"""

_ALL_NETWORKS = ["gut", "heart"]


@pytest.fixture(scope="module")
def mapping_schema_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("schema") / "dictionary_test.yaml"
    path.write_text(_MAPPING_SCHEMA)
    return path


@pytest.fixture(scope="module")
def mapping_dictionary(mapping_schema_path):
    return transform_schema_to_data_dictionary(SchemaView(str(mapping_schema_path), merge_imports=True))


def _class_entry(dictionary, class_name):
    [entry] = [c for c in dictionary["classes"] if c["title"] == class_name]
    return entry


def _attributes(dictionary, class_name):
    return {a["name"]: a for a in _class_entry(dictionary, class_name)["attributes"]}


def test_only_included_concrete_classes_are_emitted(mapping_dictionary):
    # Base and Unlisted are not in the included set; Sample is, but is abstract.
    assert [c["title"] for c in mapping_dictionary["classes"]] == ["Dataset", "Donor"]


def test_class_entry(mapping_dictionary):
    dataset = _class_entry(mapping_dictionary, "Dataset")
    assert dataset["name"] == "dataset"
    assert dataset["description"] == "A dataset."
    assert _class_entry(mapping_dictionary, "Donor")["description"] == ""


def test_list_comments_and_notes_are_joined_with_newlines(mapping_dictionary):
    slot = _attributes(mapping_dictionary, "Dataset")["rationale_slot"]
    assert slot["rationale"] == "First comment.\nSecond comment."
    assert slot["values"] == "First note.\nSecond note."


def test_enum_values_are_flattened_and_replace_notes(mapping_dictionary):
    assert _attributes(mapping_dictionary, "Dataset")["colour"]["values"] == "red; blue"


def test_populated_slot(mapping_dictionary):
    assert _attributes(mapping_dictionary, "Dataset")["title"] == {
        "name": "title",
        "title": "Title",
        "description": "The dataset title.",
        "range": "string",
        "required": True,
        "multivalued": False,
        "example": "first example",
        "annotations": {"annDataLocation": "uns", "cxg": "title", "bioNetworks": _ALL_NETWORKS},
    }


def test_bare_slot_gets_defaults_and_only_bionetworks(mapping_dictionary):
    assert _attributes(mapping_dictionary, "Dataset")["bare"] == {
        "name": "bare",
        "title": "bare",
        "description": "",
        "range": "string",
        "required": False,
        "multivalued": False,
        "annotations": {"bioNetworks": _ALL_NETWORKS},
    }


def test_multivalued(mapping_dictionary):
    assert _attributes(mapping_dictionary, "Donor")["donor_id"]["multivalued"] is True


def test_generate_dictionary_writes_json(mapping_schema_path, mapping_dictionary, tmp_path):
    output = tmp_path / "out.json"
    generate_dictionary(mapping_schema_path, output)
    assert json.loads(output.read_text()) == mapping_dictionary
