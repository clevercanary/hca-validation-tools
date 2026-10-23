#!/usr/bin/env python3
"""generate_dictionary.py - Generate a data dictionary JSON from LinkML schema files.

This script uses the expand_schema functionality to create a flattened JSON representation
of the HCA validation schema, which can be used as a data dictionary.

By default, the dictionary is saved to the 'data_dictionaries' directory in the project root.
"""

import json
import sys
from pathlib import Path
from typing import Any

import jsonasobj2
from linkml_runtime import SchemaView

from hca_validation.schema_utils import get_bionetwork_keys, get_bionetwork_subclasses, get_class_entity_type


def transform_schema_to_data_dictionary(schemaview: SchemaView) -> dict[str, Any]:
    """
    Transform the LinkML schema into the requested data dictionary format.

    Args:
        schema_dict: The expanded LinkML schema dictionary

    Returns:
        A dictionary in the requested format for the data dictionary
    """
    # Initialize the output dictionary with the basic structure
    output = {
        "name": "tier_1",
        "title": "HCA Tier 1 Metadata",
        "classes": [],
        "prefixes": {"cxg": "https://github.com/chanzuckerberg/single-cell-curation/blob/main/schema/5.2.0/schema.md"},
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
        attributes += fold_bionetwork_slots(schemaview, class_name, schema_enum_names)

        # Sort by name to retain consistent order
        class_entry["attributes"] = sorted(attributes, key=lambda attribute: attribute["name"])

        # Add the class to the output
        output["classes"].append(class_entry)

    return output


def fold_bionetwork_slots(schemaview: SchemaView, base_class: str, schema_enum_names: set[str]) -> list[dict[str, Any]]:
    """
    Return one attribute per slot that bionetwork subclasses add to `base_class`, with
    `bioNetworks` set to the sorted union of the networks that add it.

    Raises ValueError if a subclass changes a base slot, or two subclasses define the same
    added slot differently: the data dictionary can show only one definition per slot.
    """
    base_attributes = {
        slot_info.name: slot_to_attribute(schemaview, slot_info, schema_enum_names)
        for slot_info in schemaview.class_induced_slots(base_class)
    }
    folded: dict[str, tuple[dict[str, Any], set[str]]] = {}

    for subclass_name, network in get_bionetwork_subclasses(schemaview, base_class).items():
        for slot_info in schemaview.class_induced_slots(subclass_name):
            attribute = slot_to_attribute(schemaview, slot_info, schema_enum_names)
            if slot_info.name in base_attributes:
                if attribute != base_attributes[slot_info.name]:
                    raise ValueError(f"{subclass_name} changes {base_class}'s {slot_info.name!r}")
            elif slot_info.name in folded:
                existing_attribute, networks = folded[slot_info.name]
                if attribute != existing_attribute:
                    raise ValueError(f"Bionetwork subclasses of {base_class} define {slot_info.name!r} differently")
                networks.add(network)
            else:
                folded[slot_info.name] = (attribute, {network})

    for attribute, networks in folded.values():
        attribute.setdefault("annotations", {})["bioNetworks"] = sorted(networks)
    return [attribute for attribute, _ in folded.values()]


def slot_to_attribute(schemaview: SchemaView, slot_info, schema_enum_names: set[str]) -> dict[str, Any]:
    """Convert an induced slot into a data dictionary attribute."""
    # Create the attribute entry with the exact structure requested
    attribute = {
        "name": slot_info.name,
        # Use title from schema if available
        "title": slot_info.title if slot_info.title is not None else slot_info.name,
        "description": slot_info.description or "",
        "range": slot_info.range if slot_info.range is not None else "string",
        "required": slot_info.required if slot_info.required is not None else False,
        "multivalued": slot_info.multivalued if slot_info.multivalued is not None else False,
    }

    # Add examples if available
    if slot_info.examples:
        # Get the first example value
        example = slot_info.examples[0]
        attribute["example"] = example.value

    # Add annotations if available - format as requested
    if slot_info.annotations:
        formatted_annotations = {}
        for annot_name, annot_info in jsonasobj2.items(slot_info.annotations):
            formatted_annotations[annot_name] = annot_info.value
        attribute["annotations"] = formatted_annotations

    # Add rationale if available in comments - as a string, not an array
    if slot_info.comments:
        if isinstance(slot_info.comments, list):
            attribute["rationale"] = "\n".join(slot_info.comments)
        else:
            attribute["rationale"] = slot_info.comments

    # Add values information if available in notes - as a string, not an array
    if slot_info.notes:
        if isinstance(slot_info.notes, list):
            attribute["values"] = "\n".join(slot_info.notes)
        else:
            attribute["values"] = slot_info.notes

    # If this is an enum, add the values
    if slot_info.range in schema_enum_names:
        enum_info = schemaview.induced_enum(slot_info.range)
        values_list = []
        for pv_name in enum_info.permissible_values or {}:
            values_list.append(pv_name)
        if values_list:
            attribute["values"] = "; ".join(values_list)

    return attribute


def generate_dictionary(schema_path=None, output_path=None):
    """
    Generate a data dictionary JSON from the specified schema file.

    Args:
        schema_path: Path to the schema file (default: core.yaml in the schema directory)
        output_path: Path to write the output JSON (default: standard path in data_dictionaries directory)
    """
    # Get paths
    current_dir = Path(__file__).parent
    project_root = current_dir.parent.parent.parent.parent

    # Default to core.yaml if no schema path is provided
    if schema_path is None:
        # Get the path to the schema directory (in shared library)
        schema_dir = project_root / "shared" / "src" / "hca_validation" / "schema"
        schema_path = schema_dir / "core.yaml"

    # Load the schema
    schemaview = SchemaView(str(schema_path), merge_imports=True)

    # Transform the schema into the requested format
    data_dict = transform_schema_to_data_dictionary(schemaview)

    # If no output path is provided, use the standard path
    if output_path is None:
        # Create data_dictionaries directory if it doesn't exist
        data_dict_dir = project_root / "data_dictionaries"
        data_dict_dir.mkdir(exist_ok=True)

        # Use a standard filename based on the schema name
        schema_name = Path(schema_path).stem
        output_path = data_dict_dir / f"{schema_name}_data_dictionary.json"

    # Write to file
    with Path(output_path).open("w", encoding="utf-8") as fh:
        json.dump(data_dict, fh, indent=2)
    print(f"Data dictionary written to {output_path}")


def main():
    """Command-line entry point."""
    # Parse command line arguments
    if len(sys.argv) > 1:
        schema_path = sys.argv[1]
    else:
        # Default to core.yaml in the schema directory
        current_dir = Path(__file__).parent
        schema_dir = current_dir.parent / "schema"
        schema_path = schema_dir / "core.yaml"

    # If a specific output path is provided as an argument, use it
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    generate_dictionary(schema_path, output_path)


if __name__ == "__main__":
    main()
