"""
Tests for data dictionary generation: the folding of bionetwork subclass slots into their base class with a
`bioNetworks` annotation, and (#548) how a slot maps to an attribute, pinned against a small fixed schema.
"""

import json
import re
import textwrap

import pytest
from linkml_runtime import SchemaView
from linkml_runtime.linkml_model import Example, SlotDefinition

from hca_validation.data_dictionary.generate_dictionary import (
    TIER_2_LAYOUT_PATH,
    fold_bionetwork_slots,
    generate_dictionary,
    generate_tier_1_dictionary,
    generate_tier_2_dictionary,
    load_layout,
    load_schemas,
    slot_to_attribute,
    transform_layout_to_data_dictionary,
    transform_schema_to_data_dictionary,
)
from hca_validation.schema_utils.schema_utils import _annotation_value, get_bionetwork_subclasses, get_tier_2_mixins

_CXG = "https://example.org/cxg"


@pytest.fixture(scope="module")
def data_dictionary(schemaview):
    return transform_schema_to_data_dictionary(schemaview, _CXG)


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
@pytest.mark.parametrize("dictionary", ["data_dictionary", "tier_1_dictionary"])
def test_bionetwork_slots_are_folded(request, dictionary, class_name, attribute_name, networks):
    attribute = _attribute(request.getfixturevalue(dictionary), class_name, attribute_name)
    assert attribute["annotations"]["bioNetworks"] == networks
    assert attribute["annotations"]["annDataLocation"] == "obs"
    assert attribute["annotations"]["tier"] == "Tier 1"
    assert attribute["required"] is True


@pytest.mark.parametrize("attribute_name", ["library_preparation_batch", "library_sequencing_run"])
def test_library_slots_are_strongly_recommended(data_dictionary, attribute_name):
    # The only two fields the portal's tier-1.json marks strongly recommended, as the h5ad validator does (#761).
    assert _attribute(data_dictionary, "sample", attribute_name)["required"] == "strongly recommended"


def test_title_is_required_without_entry_sheet_relaxation(data_dictionary):
    # #836: h5ad files require title; the entry-sheet tag never reaches the dictionary (#850).
    title = _attribute(data_dictionary, "dataset", "title")
    assert title["required"] is True
    assert title["annotations"]["tier"] == "Tier 1"
    assert "entrySheetRequired" not in title["annotations"]


def test_real_schema_shows_display_ranges(schemaview, data_dictionary):
    # #762: the portal shows `string` for enums and classes, and `decimal` for cell_viability_percentage.
    assert _attribute(data_dictionary, "sample", "cell_viability_percentage")["range"] == "decimal"
    assert _attribute(data_dictionary, "dataset", "contact_email")["range"] == "string"
    named = set(schemaview.all_enums()) | set(schemaview.all_classes())
    assert not [a["name"] for c in data_dictionary["classes"] for a in c["attributes"] if a["range"] in named]


def test_no_schema_text_ends_in_whitespace(schemaview):
    # Checks the YAML rather than the dictionary, whose generator strips it; a block scalar written `|` or `>` keeps
    # a trailing newline that the generated models carry too (#762).
    padded = []
    for class_name in schemaview.all_classes():
        for slot in schemaview.class_induced_slots(class_name):
            texts = [slot.title, slot.description, *slot.comments, *slot.notes, *(e.value for e in slot.examples)]
            if any(text is not None and text != text.rstrip() for text in texts):
                padded.append(f"{class_name}.{slot.name}")
    assert not padded, f"trailing whitespace: {', '.join(padded)}"


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
    (dataset,) = transform_schema_to_data_dictionary(schemaview, _CXG)["classes"]
    by_name = {attribute["name"]: attribute for attribute in dataset["attributes"]}

    assert list(by_name) == ["gut_field", "shared_field", "title"]
    assert by_name["shared_field"]["annotations"]["bioNetworks"] == ["gut", "lung"]
    assert by_name["shared_field"]["required"] is True
    assert by_name["gut_field"]["annotations"]["bioNetworks"] == ["gut"]
    assert by_name["title"]["annotations"]["bioNetworks"] == ["gut", "heart", "lung"]


def _tier_2_mixin(name, network, slot, base="Dataset", extra=""):
    return f"""
        {name}:
          mixin: true
          annotations:
            bioNetwork: {network}
            tier: Tier 2
            baseClass: {base}
          slots:
            - {slot}
        {extra}"""


def test_tier_2_mixins_fold_apart_from_subclasses(tmp_path):
    # A Tier 2 mixin isn't a subclass: Tier 1 and the core export fold only the subclass, Tier 2 only the mixin.
    schemaview = _schemaview(
        tmp_path,
        """
        GutDataset:
          is_a: Dataset
          annotations:
            bioNetwork: gut
          slots:
            - gut_field
        """
        + _tier_2_mixin("GutDatasetTier2", "gut", "shared_field"),
    )
    (dataset,) = transform_schema_to_data_dictionary(schemaview, _CXG)["classes"]
    assert [a["name"] for a in dataset["attributes"]] == ["gut_field", "title"]
    tier_2 = fold_bionetwork_slots(schemaview, "Dataset", set(), get_tier_2_mixins(schemaview, "Dataset"))
    assert {name: a["annotations"]["bioNetworks"] for name, a in tier_2.items()} == {"shared_field": ["gut"]}


def test_tier_2_slot_of_several_networks_is_folded_once(tmp_path):
    schemaview = _schemaview(
        tmp_path,
        _tier_2_mixin("LungDatasetTier2", "lung", "shared_field")
        + _tier_2_mixin("GutDatasetTier2", "gut", "shared_field"),
    )
    tier_2 = fold_bionetwork_slots(schemaview, "Dataset", set(), get_tier_2_mixins(schemaview, "Dataset"))
    assert tier_2["shared_field"]["annotations"]["bioNetworks"] == ["gut", "lung"]


def test_tier_2_mixins_defining_a_slot_differently_are_refused(tmp_path):
    schemaview = _schemaview(
        tmp_path,
        _tier_2_mixin("LungDatasetTier2", "lung", "shared_field")
        + _tier_2_mixin(
            "GutDatasetTier2",
            "gut",
            "shared_field",
            extra="  slot_usage:\n            shared_field:\n              required: false",
        ),
    )
    with pytest.raises(ValueError, match="define 'shared_field' differently"):
        fold_bionetwork_slots(schemaview, "Dataset", set(), get_tier_2_mixins(schemaview, "Dataset"))


def test_tier_2_layout_leaving_out_a_mixin_slot_is_refused(tmp_path):
    _schemaview(tmp_path, _tier_2_mixin("GutDatasetTier2", "gut", "shared_field"))
    layout = _layout(tmp_path, "DatasetSection:\n  mixins: [Dataset]\n  slots: [title]\n")
    with pytest.raises(ValueError, match="No section lists shared_field, which networks add to Dataset"):
        transform_layout_to_data_dictionary(*load_schemas(tmp_path / "schema.yaml", layout), get_tier_2_mixins)


def test_other_mixins_are_not_tier_2(tmp_path):
    # Only a mixin annotated `tier: Tier 2` is one; an ordinary LinkML mixin is left alone.
    schemaview = _schemaview(tmp_path, "HasProvenance:\n  mixin: true\n  slots:\n    - gut_field\n")
    assert get_tier_2_mixins(schemaview, "Dataset") == {}


@pytest.mark.parametrize(
    ("mixin", "match"),
    [
        (
            "GutDatasetTier2:\n  mixin: true\n  annotations:\n    bioNetwork: gut\n    tier: Tier 2\n",
            "no bioNetwork or baseClass",
        ),
        (
            "GutDatasetTier2:\n  mixin: true\n  annotations:\n    tier: Tier 2\n    baseClass: Dataset\n",
            "no bioNetwork or baseClass",
        ),
        (_tier_2_mixin("GutDatasetTier2", "guts", "gut_field"), "'guts', which is not in the BioNetwork enum"),
        (_tier_2_mixin("GutDatasetTier2", "gut", "gut_field", base="Datset"), "'Datset', which is not a class"),
    ],
    ids=["no-base-class", "no-network", "unknown-network", "unknown-class"],
)
def test_bad_tier_2_mixins_are_refused(tmp_path, mixin, match):
    with pytest.raises(ValueError, match=match):
        get_tier_2_mixins(_schemaview(tmp_path, mixin), "Dataset")


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
        transform_schema_to_data_dictionary(schemaview, _CXG)


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
        transform_schema_to_data_dictionary(schemaview, _CXG)


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
        transform_schema_to_data_dictionary(schemaview, _CXG)


def test_subclass_adding_only_entry_sheet_required_folds(tmp_path):
    # #850: the annotation relaxes entry sheets only, so it is not a definition change the dictionary must refuse.
    schemaview = _schemaview(
        tmp_path,
        """
        GutDataset:
          is_a: Dataset
          annotations:
            bioNetwork: gut
          slot_usage:
            title:
              annotations:
                entrySheetRequired: false
        """,
    )
    title = _attribute(transform_schema_to_data_dictionary(schemaview, _CXG), "dataset", "title")
    assert title["required"] is True
    assert "entrySheetRequired" not in title.get("annotations", {})


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
        transform_schema_to_data_dictionary(schemaview, _CXG)


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
        transform_schema_to_data_dictionary(schemaview, _CXG)


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
        transform_schema_to_data_dictionary(schemaview, _CXG)


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
        transform_schema_to_data_dictionary(schemaview, _CXG)


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

types:
  Email:
    typeof: string

slots:
  title:
    title: Title
    description: The dataset title.
    required: true
    examples:
      - value: first example
      - value: "second; example"
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
  # Block scalars end in a newline, which must not reach any joined text (#762).
  colour:
    range: Colour
    notes:
      - |
        Pick a colour.
  padded:
    description: |
      A padded description.
    comments:
      - |
        A padded comment.
  email:
    range: Email
  owner:
    range: Donor
  count:
    range: integer
  decimal_or_text:
    any_of:
      - range: decimal
      - range: string
  donor_id:
    multivalued: true
  sheet_optional:
    required: true
    annotations:
      tier: Tier 1
      entrySheetRequired: false
  recommended_slot:
    recommended: true
  required_and_recommended:
    required: true
    recommended: true
  unlisted_slot:

classes:
  Dataset:
    description: A dataset.
    slots:
      - title
      - rationale_slot
      - bare
      - colour
      - padded
      - email
      - owner
      - count
      - decimal_or_text
      - recommended_slot
      - required_and_recommended
      - sheet_optional
      - unlisted_slot
  Donor:
    slots:
      - donor_id
    slot_usage:
      donor_id:
        required: true
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
    return transform_schema_to_data_dictionary(SchemaView(str(mapping_schema_path), merge_imports=True), _CXG)


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


def test_enum_values_follow_the_notes(mapping_dictionary):
    # #762: a slot with an enum range and notes keeps both, the notes first.
    assert _attributes(mapping_dictionary, "Dataset")["colour"]["values"] == "Pick a colour.\n\nred; blue"


def test_description_and_rationale_drop_trailing_whitespace(mapping_dictionary):
    padded = _attributes(mapping_dictionary, "Dataset")["padded"]
    assert (padded["description"], padded["rationale"]) == ("A padded description.", "A padded comment.")


@pytest.mark.parametrize(
    ("attribute_name", "expected"),
    [
        ("colour", "string"),  # enum
        ("owner", "string"),  # class
        ("email", "string"),  # custom type, shown as its built-in type
        ("count", "integer"),  # built-in type, unchanged
        ("decimal_or_text", "decimal"),  # any_of shows its first member
        ("bare", "string"),  # no range
    ],
)
def test_display_ranges(mapping_dictionary, attribute_name, expected):
    assert _attributes(mapping_dictionary, "Dataset")[attribute_name]["range"] == expected


def test_populated_slot(mapping_dictionary):
    assert _attributes(mapping_dictionary, "Dataset")["title"] == {
        "name": "title",
        "title": "Title",
        "description": "The dataset title.",
        "range": "string",
        "required": True,
        "multivalued": False,
        "examples": ["first example", "second; example"],
        "annotations": {"annDataLocation": "uns", "cxg": "title", "bioNetworks": _ALL_NETWORKS},
    }


def test_example_without_a_value_is_refused(schemaview):
    slot = SlotDefinition(name="title", examples=[Example(description="any free text")])
    with pytest.raises(ValueError, match="'title' has an example with no value"):
        slot_to_attribute(schemaview, slot, set())


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


@pytest.mark.parametrize(
    ("attribute_name", "required"),
    [("recommended_slot", "strongly recommended"), ("required_and_recommended", True)],
)
def test_requirement_levels(mapping_dictionary, attribute_name, required):
    # The portal's three levels (#761): LinkML's `recommended` metaslot is "strongly recommended", and `required` wins.
    assert _attributes(mapping_dictionary, "Dataset")[attribute_name]["required"] == required


def test_entry_sheet_required_stays_out_of_the_dictionary(mapping_dictionary):
    # #850: the portal's dictionary reports the `required` level only, never the entry-sheet relaxation.
    attribute = _attributes(mapping_dictionary, "Dataset")["sheet_optional"]
    assert attribute["required"] is True
    assert attribute["annotations"] == {"tier": "Tier 1", "bioNetworks": _ALL_NETWORKS}


def test_multivalued(mapping_dictionary):
    assert _attributes(mapping_dictionary, "Donor")["donor_id"]["multivalued"] is True


def test_generate_dictionary_writes_json(mapping_schema_path, mapping_layout, mapping_dictionary, tmp_path):
    output = tmp_path / "out.json"
    generate_dictionary(output, mapping_schema_path, mapping_layout)
    assert json.loads(output.read_text()) == mapping_dictionary


# The HCA Data Portal's Tier 1 dictionary, laid out by dictionary.yaml (#760)


@pytest.fixture(scope="module")
def tier_1_dictionary():
    return transform_layout_to_data_dictionary(*load_schemas(), get_bionetwork_subclasses)


def test_every_cellxgene_link_names_the_layouts_schema_version(schemaview, tier_1_dictionary):
    # #859: the matrix layers note links CELLxGENE's schema in full, so a version bump to the layout's `cxg` prefix
    # must reach those links too.
    cxg_reference = load_layout().prefixes["cxg"].prefix_reference
    linked = json.dumps([tier_1_dictionary, transform_schema_to_data_dictionary(schemaview, cxg_reference)])
    version = re.compile(r"single-cell-curation/blob/main/schema/([^/]+)/")
    assert set(version.findall(linked)) == set(version.findall(cxg_reference))


# The HCA Data Portal's tier-1.json, which shows fields in file order
_PORTAL_LAYOUT = {
    "dataset": [
        "study_pi", "batch_condition", "default_embedding", "sequencing_platform", "assay_ontology_term_id",
        "reference_genome", "alignment_software", "intron_inclusion", "sequenced_fragment", "gene_annotation_version",
        "comments", "protocol_url", "title", "ambient_count_correction", "doublet_detection", "X_{suffix}",
    ],
    "donor": ["donor_id", "organism_ontology_term_id", "manner_of_death", "sex_ontology_term_id"],
    "sample": [
        "sample_id", "tissue_ontology_term_id", "tissue_free_text", "sample_source", "sample_collection_method",
        "tissue_type", "sampled_site_condition", "disease_ontology_term_id", "sample_preservation_method",
        "suspension_type", "is_primary_data", "development_stage_ontology_term_id", "radial_tissue_term",
        "dissociation_protocol", "cell_enrichment", "sample_collection_year", "sample_collection_site",
        "sample_collection_relative_time_point", "cell_number_loaded", "cell_viability_percentage", "institute",
        "author_batch_notes",
    ],
    "library": ["library_id", "library_id_repository", "library_preparation_batch", "library_sequencing_run"],
    "cell": ["author_cell_type", "cell_type_ontology_term_id"],
    "feature": ["index of pandas.DataFrame", "feature_is_filtered"],
    "matrixLayers": ["X; raw.X"],
}  # fmt: skip


def test_tier_1_sections_and_fields_match_the_portal(tier_1_dictionary):
    layout = {c["name"]: [a["name"] for a in c["attributes"]] for c in tier_1_dictionary["classes"]}
    assert list(layout.items()) == list(_PORTAL_LAYOUT.items())


def test_tier_1_fields_are_the_tier_1_slots(schemaview, tier_1_dictionary):
    # A field is shown only when a section lists it, so a new Tier 1 slot left out of dictionary.yaml fails here.
    attributes = {a["name"]: a for c in tier_1_dictionary["classes"] for a in c["attributes"]}
    untiered = [name for name, a in attributes.items() if a["annotations"].get("tier") != "Tier 1"]
    assert not untiered, f"shown but not Tier 1: {', '.join(untiered)}"
    tier_1 = {
        slot.name
        for class_name in schemaview.all_classes()
        for slot in schemaview.class_induced_slots(class_name)
        if _annotation_value(slot, "tier") == "Tier 1"
    }
    missing = tier_1 - set(attributes)
    assert not missing, f"Tier 1 but in no section: {', '.join(sorted(missing))}"


def test_tier_1_fields_have_anndata_locations_and_networks(tier_1_dictionary):
    for entity_class in tier_1_dictionary["classes"]:
        for attribute in entity_class["attributes"]:
            assert attribute["annotations"]["annDataLocation"], f"{entity_class['name']}.{attribute['name']}"
            assert attribute["annotations"]["bioNetworks"], f"{entity_class['name']}.{attribute['name']}"


def test_tier_1_keeps_the_library_fields_strongly_recommended(tier_1_dictionary):
    required = {a["name"]: a["required"] for a in _class_entry(tier_1_dictionary, "Library")["attributes"]}
    assert required["library_preparation_batch"] == required["library_sequencing_run"] == "strongly recommended"


# The HCA Data Portal's Tier 2 dictionary, laid out by tier_2_dictionary.yaml (#790)

# The portal's tier-2.json fields, in its order
_TIER_2_DONOR_FIELDS = [
    "age_value",
    "age_unit",
    "bmi",
    "height",
    "weight",
    "genderidentity_selfreported",
    "ethnicity_selfreported_freetext",
    "ethnicity_question_text",
    "language_donor_primary_language",
    "geography_currentresidence_location_country_state",
    "geography_currentresidence_location_granular",
    "occupation",
    "comorbidities",
    "genotype",
    "medication",
    "diet_meat_consumption",
    "medical_test_results",
    "treatments",
    "previous_surgery",
    "previous_surgery_relative_time_point",
    "previous_surgery_relative_time_unit",
    "history_of_injury_type",
    "history_of_injury_type_relative_time_point",
    "history_of_injury_type_relative_time_unit",
    "alcohol_status",
    "alcohol_type",
    "alcohol_usage_duration",
    "alcohol_units",
    "smoking_status",
    "years_since_smoking_cessation",
    "smoking_pack_years",
    "nutritional_state",
    "physical_activity_physical_exposure",
    "handedness",
    "microanatomical_region",
    "geography_collectionsite_latitude_longitude",
    "geography_currentresidence_duration",
    "geography_currentresidence_urbanrural",
    "geography_placeofbirth_location_country_state",
    "geography_placeofbirth_location_granular",
    "geography_placeofbirth_duration",
    "geography_placeofbirth_urbanrural",
    "ethnicity_parents_selfreported_freetext",
    "language_mother_father_tongue",
    "menarche_age",
    "reproductive_menopause",
    "reproductive_number_children",
    "reproductive_number_pregnancies",
]
_TIER_2_SAMPLE_FIELDS = [
    "collected_tissue_processing",
    "tissue_transportation",
    "time_to_laboratory",
    "side_of_tissue_collected",
    "sample_storage_method",
    "sample_storage_relative_time_point",
    "sample_storage_relative_time_unit",
    "sample_dissociation_relative_time_point",
    "sample_dissociation_relative_time_unit",
    "digestion_temperature",
    "dissociation_description",
    "dissociation_doi",
    "cell_suspension_storage_time",
    "cell_suspension_storage_time_unit",
    "library_prep_relative_time_point",
    "library_prep_relative_time_unit",
]
# The fields the portal also scopes to genetic-diversity; every Tier 2 field is musculoskeletal
_TIER_2_GENETIC_DIVERSITY_FIELDS = {
    "age_unit",
    "age_value",
    "bmi",
    "diet_meat_consumption",
    "ethnicity_parents_selfreported_freetext",
    "ethnicity_question_text",
    "ethnicity_selfreported_freetext",
    "genderidentity_selfreported",
    "geography_collectionsite_latitude_longitude",
    "geography_currentresidence_duration",
    "geography_currentresidence_location_country_state",
    "geography_currentresidence_location_granular",
    "geography_currentresidence_urbanrural",
    "geography_placeofbirth_duration",
    "geography_placeofbirth_location_country_state",
    "geography_placeofbirth_location_granular",
    "geography_placeofbirth_urbanrural",
    "height",
    "language_donor_primary_language",
    "language_mother_father_tongue",
    "medication",
    "menarche_age",
    "reproductive_menopause",
    "reproductive_number_children",
    "reproductive_number_pregnancies",
    "smoking_status",
    "weight",
}


@pytest.fixture(scope="module")
def tier_2_dictionary():
    return transform_layout_to_data_dictionary(*load_schemas(layout_path=TIER_2_LAYOUT_PATH), get_tier_2_mixins)


def test_tier_2_sections_and_fields_match_the_portal(tier_2_dictionary):
    assert [(c["name"], [a["name"] for a in c["attributes"]]) for c in tier_2_dictionary["classes"]] == [
        ("donor", _TIER_2_DONOR_FIELDS),
        ("sample", _TIER_2_SAMPLE_FIELDS),
    ]


def test_tier_2_fields_are_tier_2_and_scoped_as_the_portal_scopes_them(tier_2_dictionary):
    for attribute in (a for c in tier_2_dictionary["classes"] for a in c["attributes"]):
        expected = (
            ["genetic-diversity", "musculoskeletal"]
            if attribute["name"] in _TIER_2_GENETIC_DIVERSITY_FIELDS
            else ["musculoskeletal"]
        )
        assert attribute["annotations"] == {"tier": "Tier 2", "bioNetworks": expected}, attribute["name"]


def test_tier_2_number_fields_are_decimal(tier_2_dictionary):
    ranges = {a["name"]: a["range"] for c in tier_2_dictionary["classes"] for a in c["attributes"]}
    decimal = {"bmi", "alcohol_units", "smoking_pack_years", "time_to_laboratory"}
    assert {name for name, value in ranges.items() if value == "decimal"} == decimal


def test_generate_tier_2_dictionary_writes_json(tier_2_dictionary, tmp_path):
    output = tmp_path / "out.json"
    generate_tier_2_dictionary(output)
    assert json.loads(output.read_text()) == tier_2_dictionary


def _layout(tmp_path, sections, slots=""):
    """Write a dictionary layout with a minimal header, the given section classes and slots, and return its path."""
    layout = (
        textwrap.dedent(
            """
        id: https://example.org/layout
        name: test_dictionary
        title: Test Dictionary
        prefixes:
          linkml: https://w3id.org/linkml/
          cxg: https://example.org/cxg
        annotations:
          cxg: CELLxGENE Schema
        imports:
          - linkml:types
        classes:
        """
        )
        + textwrap.indent(textwrap.dedent(sections), "  ")
        + textwrap.dedent(slots)
    )
    path = tmp_path / "layout.yaml"
    path.write_text(layout)
    return path


# Lists Dataset's slots in an order of their own, leaves out unlisted_slot, and adds a section of structure rows
_MAPPING_SECTIONS = """
DatasetSection:
  title: Dataset
  description: The dataset section.
  mixins:
    - Dataset
  slots:
    - sheet_optional
    - title
    - bare
DonorSection:
  title: Donor
  mixins:
    - Donor
  slots:
    - donor_id
StructureSection:
  title: Structure
  slots:
    - structure_row
"""

_STRUCTURE_SLOTS = """
slots:
  structure_row:
    alias: "X; raw.X"
    annotations:
      displayRange: numpy.ndarray
      tier: Tier 1
"""


@pytest.fixture(scope="module")
def mapping_layout(tmp_path_factory):
    return _layout(tmp_path_factory.mktemp("layout"), _MAPPING_SECTIONS, _STRUCTURE_SLOTS)


@pytest.fixture(scope="module")
def mapping_tier_1(mapping_schema_path, mapping_layout):
    return transform_layout_to_data_dictionary(
        *load_schemas(mapping_schema_path, mapping_layout), get_bionetwork_subclasses
    )


def test_only_sections_are_emitted_in_layout_order(mapping_tier_1):
    assert [(c["name"], c["title"], c["description"]) for c in mapping_tier_1["classes"]] == [
        ("dataset", "Dataset", "The dataset section."),
        ("donor", "Donor", ""),
        ("structure", "Structure", ""),
    ]


def test_fields_follow_the_layout_order(mapping_tier_1):
    assert list(_attributes(mapping_tier_1, "Dataset")) == ["sheet_optional", "title", "bare"]


def test_mixin_supplies_slot_usage(mapping_tier_1):
    assert _attributes(mapping_tier_1, "Donor")["donor_id"]["required"] is True


def test_section_field_matches_the_full_export(mapping_tier_1, mapping_dictionary):
    assert _attributes(mapping_tier_1, "Dataset")["title"] == _attributes(mapping_dictionary, "Dataset")["title"]


def test_alias_names_the_field_and_display_range_overrides_the_range(mapping_tier_1):
    row = _attributes(mapping_tier_1, "Structure")["X; raw.X"]
    assert row["range"] == "numpy.ndarray"
    assert row["annotations"] == {"tier": "Tier 1", "bioNetworks": _ALL_NETWORKS}


def test_core_header_uses_the_given_cxg_reference(mapping_dictionary):
    assert mapping_dictionary["prefixes"] == {"cxg": _CXG}


def test_header_comes_from_the_layout(mapping_tier_1):
    assert {k: v for k, v in mapping_tier_1.items() if k != "classes"} == {
        "name": "test_dictionary",
        "title": "Test Dictionary",
        "description": "",
        "prefixes": {"cxg": _CXG},
        "annotations": {"cxg": "CELLxGENE Schema"},
    }


@pytest.mark.parametrize(
    ("sections", "slots", "match"),
    [
        ("Dataset2:\n  mixins: [Dataset]\n  slots: [title]\n", "", "'Dataset2' must end in 'Section'"),
        ("BothSection:\n  mixins: [Dataset, Donor]\n  slots: [title]\n", "", "mixes in 2 classes"),
        ("DatasetSection:\n  mixins: [Dataset]\n  slots: [donor_id]\n", "", "lists 'donor_id', which is not a slot"),
        ("LooseSection:\n  slots: [title]\n", "", "lists 'title', which is not a slot"),
        ("TitleSection:\n  slots: [title]\n", "slots:\n  title: {}\n", "redefines schema elements: title"),
    ],
    ids=["no-suffix", "two-mixins", "other-class-slot", "no-mixin", "collision"],
)
def test_bad_layouts_are_refused(tmp_path, mapping_schema_path, sections, slots, match):
    with pytest.raises(ValueError, match=match):
        transform_layout_to_data_dictionary(
            *load_schemas(mapping_schema_path, _layout(tmp_path, sections, slots)), get_bionetwork_subclasses
        )


def test_generate_tier_1_dictionary_writes_json(mapping_schema_path, mapping_layout, mapping_tier_1, tmp_path):
    output = tmp_path / "out.json"
    generate_tier_1_dictionary(output, mapping_schema_path, mapping_layout)
    assert json.loads(output.read_text()) == mapping_tier_1
