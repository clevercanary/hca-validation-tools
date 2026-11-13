#!/usr/bin/env python3
"""generate_dictionary.py - Generate data dictionary JSON files from LinkML schema files.

Two dictionaries are generated: the full export of every slot under its schema class, which the HCA Atlas Tracker
reads, and the HCA Data Portal's Tier 1 dictionary, laid out by `dictionary.yaml`.

`make generate-data-dictionary` writes both to the 'data_dictionaries' directory in the project root.
"""

import json
from pathlib import Path
from typing import Any

import jsonasobj2
from hca_metadata_schema import CORE_SCHEMA_PATH
from linkml_runtime import SchemaView
from linkml_runtime.dumpers import json_dumper
from linkml_runtime.linkml_model import SchemaDefinition
from linkml_runtime.loaders import yaml_loader

from hca_validation.schema_utils import (
    ENTRY_SHEET_REQUIRED,
    get_bionetwork_keys,
    get_bionetwork_subclasses,
    get_class_entity_type,
)

# The portal's header, sections and AnnData structure rows (#760)
LAYOUT_PATH = Path(__file__).with_name("dictionary.yaml")

_SECTION_SUFFIX = "Section"

# Overrides the computed range, for structure rows whose range is not a LinkML type
_DISPLAY_RANGE = "displayRange"


def transform_schema_to_data_dictionary(schemaview: SchemaView, cxg_reference: str) -> dict[str, Any]:
    """
    Transform the LinkML schema into the requested data dictionary format.

    Args:
        schemaview: The core schema, with its imports merged
        cxg_reference: The CELLxGENE schema URL the header's `cxg` prefix expands to

    Returns:
        A dictionary in the requested format for the data dictionary
    """
    # Initialize the output dictionary with the basic structure
    output = {
        "name": "tier_1",
        "title": "HCA Tier 1 Metadata",
        "classes": [],
        "prefixes": {"cxg": cxg_reference},
        "annotations": {"cxg": "CELLxGENE"},
    }

    # Names of the classes to include in output
    included_classes = {"Dataset", "Donor", "Sample", "Cell"}

    # Get set of names of all enums in the schema
    schema_enum_names = set(schemaview.all_enums())

    all_networks = get_bionetwork_keys(schemaview)

    # Process each class in the schema
    for class_name, class_info in schemaview.all_classes().items():
        # Skip abstract classes or other non-relevant classes
        if class_info.abstract or class_name not in included_classes:
            continue

        # Create the class entry with title-cased name for title
        class_entry = {
            "title": class_name.title(),  # Ensure title case
            "description": class_info.description or "",
            "name": get_class_entity_type(class_name),  # Use lowercase entity type
            "attributes": [],
        }

        # Slots every network uses get the full network list
        attributes = []
        for slot_info in schemaview.class_induced_slots(class_name):
            attribute = slot_to_attribute(schemaview, slot_info, schema_enum_names)
            attribute.setdefault("annotations", {})["bioNetworks"] = list(all_networks)
            attributes.append(attribute)

        # Slots only bionetwork subclasses add are folded in, scoped to those networks
        attributes += fold_bionetwork_slots(schemaview, class_name, schema_enum_names).values()

        # Sort by name to retain consistent order
        class_entry["attributes"] = sorted(attributes, key=lambda attribute: attribute["name"])

        # Add the class to the output
        output["classes"].append(class_entry)

    return output


def transform_layout_to_data_dictionary(schemaview: SchemaView, layout: SchemaDefinition) -> dict[str, Any]:
    """The Tier 1 dictionary: `layout`'s header, then each of its classes as a section, in file order.

    `schemaview` must have `layout` merged into it, as `load_schemas` returns them. `prefixes` holds the layout's
    prefixes other than `linkml`.

    Raises:
        ValueError: As `section_entry` and `fold_bionetwork_slots` do
    """
    schema_enum_names = set(schemaview.all_enums())
    all_networks = get_bionetwork_keys(schemaview)
    layout_slots = set(layout.slots)
    return {
        "name": layout.name,
        "title": layout.title,
        "description": layout.description or "",
        "classes": [
            section_entry(schemaview, section_name, layout_slots, schema_enum_names, all_networks)
            for section_name in layout.classes
        ],
        "prefixes": {tag: prefix.prefix_reference for tag, prefix in layout.prefixes.items() if tag != "linkml"},
        "annotations": {tag: annotation.value for tag, annotation in jsonasobj2.items(layout.annotations)},
    }


def section_entry(
    schemaview: SchemaView,
    section_name: str,
    layout_slots: set[str],
    schema_enum_names: set[str],
    all_networks: list[str],
) -> dict[str, Any]:
    """One class entry: a section's listed slots, in order.

    Raises:
        ValueError: If the section's name does not end in `Section`, it has more than one mixin, or it lists a slot
            that is neither its core class's (the mixin's, bionetwork subclasses' included) nor defined in the layout,
            or as `slot_to_attribute` does
    """
    if not section_name.endswith(_SECTION_SUFFIX):
        raise ValueError(f"Data dictionary class {section_name!r} must end in {_SECTION_SUFFIX!r}")
    section = schemaview.get_class(section_name)
    if len(section.mixins) > 1:
        raise ValueError(f"{section_name} mixes in {len(section.mixins)} classes; a section takes at most one")

    allowed, folded = set(layout_slots), {}
    # A mixin, not is_a: an is_a child would count as a bionetwork subclass of the core class
    for core_class in section.mixins:
        folded = fold_bionetwork_slots(schemaview, core_class, schema_enum_names)
        allowed |= {slot.name for slot in schemaview.class_induced_slots(core_class)} | set(folded)

    attributes = []
    for slot_name in section.slots:
        if slot_name not in allowed:
            raise ValueError(f"{section_name} lists {slot_name!r}, which is not a slot of its class or the layout's")
        if slot_name in folded:
            attribute = folded[slot_name]
        else:
            slot_info = schemaview.induced_slot(slot_name, section_name)
            attribute = slot_to_attribute(schemaview, slot_info, schema_enum_names)
            attribute.setdefault("annotations", {})["bioNetworks"] = list(all_networks)
        attributes.append(attribute)
    name = section_name.removesuffix(_SECTION_SUFFIX)
    return {
        "title": section.title,
        "description": section.description or "",
        "name": name[0].lower() + name[1:],
        "attributes": attributes,
    }


def fold_bionetwork_slots(
    schemaview: SchemaView, base_class: str, schema_enum_names: set[str]
) -> dict[str, dict[str, Any]]:
    """
    Map each slot that bionetwork subclasses add to `base_class` to its attribute, with
    `bioNetworks` set to the sorted union of the networks that add it.

    Raises ValueError if a subclass changes a base slot, or two subclasses define the same
    added slot differently: the data dictionary can show only one definition per slot. Also
    raises it as `slot_to_attribute` does.
    """
    base_definitions = {
        slot_info.name: slot_definition(slot_info) for slot_info in schemaview.class_induced_slots(base_class)
    }
    folded: dict[str, tuple[dict[str, Any], dict[str, Any], set[str]]] = {}

    for subclass_name, network in get_bionetwork_subclasses(schemaview, base_class).items():
        for slot_info in schemaview.class_induced_slots(subclass_name):
            definition = slot_definition(slot_info)
            if slot_info.name in base_definitions:
                if definition != base_definitions[slot_info.name]:
                    raise ValueError(f"{subclass_name} changes {base_class}'s {slot_info.name!r}")
            elif slot_info.name in folded:
                existing_definition, _, networks = folded[slot_info.name]
                if definition != existing_definition:
                    raise ValueError(f"Bionetwork subclasses of {base_class} define {slot_info.name!r} differently")
                networks.add(network)
            else:
                attribute = slot_to_attribute(schemaview, slot_info, schema_enum_names)
                folded[slot_info.name] = (definition, attribute, {network})

    for _, attribute, networks in folded.values():
        attribute.setdefault("annotations", {})["bioNetworks"] = sorted(networks)
    return {name: attribute for name, (_, attribute, _) in folded.items()}


# Fields that record where an induced slot came from rather than what it allows
_SLOT_PROVENANCE = {"owner", "domain_of", "from_schema", "is_usage_slot", "usage_slot_name"}


def slot_definition(slot_info) -> dict[str, Any]:
    """An induced slot minus provenance and `entrySheetRequired` (#850); unlike `slot_to_attribute`, keeps `pattern`."""
    definition = {key: value for key, value in json_dumper.to_dict(slot_info).items() if key not in _SLOT_PROVENANCE}
    annotations = definition.get("annotations", {})
    definition["annotations"] = {key: value for key, value in annotations.items() if key != ENTRY_SHEET_REQUIRED}
    return definition


def requirement_level(slot_info) -> bool | str:
    """The portal's three requirement levels: `required` wins over LinkML's `recommended` metaslot."""
    if slot_info.required:
        return True
    if slot_info.recommended:
        return "strongly recommended"
    return False


def display_range(schemaview: SchemaView, slot_info, schema_enum_names: set[str]) -> str:
    """The portal's range (#762): enums and classes are `string`, a type its built-in, `any_of` its first member."""
    name = (slot_info.any_of[0].range if slot_info.any_of else slot_info.range) or "string"
    if name in schema_enum_names or schemaview.get_class(name) is not None:
        return "string"
    return schemaview.type_ancestors(name)[-1]


def slot_to_attribute(schemaview: SchemaView, slot_info, schema_enum_names: set[str]) -> dict[str, Any]:
    """Convert an induced slot into a data dictionary attribute.

    Raises:
        ValueError: If one of the slot's examples has no value
    """
    # Create the attribute entry with the exact structure requested
    attribute = {
        "name": slot_info.alias or slot_info.name,
        # Use title from schema if available
        "title": slot_info.title if slot_info.title is not None else slot_info.name,
        "description": (slot_info.description or "").rstrip(),
        "range": display_range(schemaview, slot_info, schema_enum_names),
        "required": requirement_level(slot_info),
        "multivalued": slot_info.multivalued if slot_info.multivalued is not None else False,
    }

    if slot_info.examples:
        if any(example.value is None for example in slot_info.examples):
            raise ValueError(f"'{slot_info.name}' has an example with no value")
        attribute["examples"] = [example.value for example in slot_info.examples]

    # Add annotations if available - format as requested
    if slot_info.annotations:
        formatted_annotations = {}
        for annot_name, annot_info in jsonasobj2.items(slot_info.annotations):
            if annot_name == _DISPLAY_RANGE:
                attribute["range"] = annot_info.value
            elif annot_name != ENTRY_SHEET_REQUIRED:  # #850: the dictionary reports `required` alone
                formatted_annotations[annot_name] = annot_info.value
        attribute["annotations"] = formatted_annotations

    # Add rationale if available in comments - as a string, not an array
    if slot_info.comments:
        attribute["rationale"] = "\n".join(slot_info.comments).rstrip()

    # Add values information if available in notes - as a string, not an array
    notes = "\n".join(slot_info.notes).rstrip() if slot_info.notes else None
    if notes:
        attribute["values"] = notes

    # If this is an enum, append its permissible values after any notes rather than replacing them (#762)
    if slot_info.range in schema_enum_names:
        permissible_values = list(schemaview.induced_enum(slot_info.range).permissible_values or {})
        if permissible_values:
            listed = "; ".join(permissible_values)
            attribute["values"] = f"{notes}\n\n{listed}" if notes else listed

    return attribute


def load_layout(layout_path=LAYOUT_PATH) -> SchemaDefinition:
    return yaml_loader.load(str(layout_path), SchemaDefinition)


def load_schemas(schema_path=CORE_SCHEMA_PATH, layout_path=LAYOUT_PATH) -> tuple[SchemaView, SchemaDefinition]:
    """The schema with the layout merged into it, and the layout.

    Raises:
        ValueError: If a layout class or slot has the name of a schema one, which the merge would silently keep
    """
    layout = load_layout(layout_path)
    schemaview = SchemaView(str(schema_path), merge_imports=True)
    collisions = (set(layout.classes) & set(schemaview.all_classes())) | (
        set(layout.slots) & set(schemaview.all_slots())
    )
    if collisions:
        raise ValueError(f"The layout redefines schema elements: {', '.join(sorted(collisions))}")
    schemaview.merge_schema(layout)
    return schemaview, layout


def _write(data_dict: dict[str, Any], output_path) -> None:
    with Path(output_path).open("w", encoding="utf-8") as fh:
        json.dump(data_dict, fh, indent=2)
    print(f"Data dictionary written to {output_path}")


def generate_dictionary(output_path, schema_path=CORE_SCHEMA_PATH, layout_path=LAYOUT_PATH):
    """Generate the full data dictionary JSON from the schema, with the layout's CELLxGENE schema URL."""
    cxg_reference = load_layout(layout_path).prefixes["cxg"].prefix_reference
    schemaview = SchemaView(str(schema_path), merge_imports=True)
    _write(transform_schema_to_data_dictionary(schemaview, cxg_reference), output_path)


def generate_tier_1_dictionary(output_path, schema_path=CORE_SCHEMA_PATH, layout_path=LAYOUT_PATH):
    """Generate the HCA Data Portal's Tier 1 data dictionary JSON from the schema and the layout."""
    _write(transform_layout_to_data_dictionary(*load_schemas(schema_path, layout_path)), output_path)
