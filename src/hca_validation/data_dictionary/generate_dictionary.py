#!/usr/bin/env python3
"""generate_dictionary.py - Generate a data dictionary JSON from LinkML schema files.

This script uses the expand_schema functionality to create a flattened JSON representation
of the HCA validation schema, which can be used as a data dictionary.

By default, the dictionary is saved to the 'data_dictionaries' directory in the project root.
"""

import sys
import os
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from linkml_runtime import SchemaView
import jsonasobj2

def transform_schema_to_data_dictionary(schemaview: SchemaView) -> Dict[str, Any]:
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
        "prefixes": {
            "cxg": "https://github.com/chanzuckerberg/single-cell-curation/blob/main/schema/5.2.0/schema.md"
        },
        "annotations": {
            "cxg": "CELLxGENE"
        }
    }
    
    # Class name mapping to ensure lowercase names in output
    class_name_mapping = {
        "Dataset": "dataset",
        "Donor": "donor",
        "Sample": "sample",
        "Cell": "cell"
    }

    # Get set of names of all enums in the schema
    schema_enum_names = set(schemaview.all_enums())

    # Process each class in the schema
    for class_name, class_info in schemaview.all_classes().items():
        # Skip abstract classes or other non-relevant classes
        if class_info.abstract or class_name not in class_name_mapping:
            continue
            
        # Create the class entry with title-cased name for title
        class_entry = {
            "title": class_name.title(),  # Ensure title case
            "description": class_info.description or "",
            "name": class_name_mapping.get(class_name, class_name.lower()),  # Use lowercase name
            "attributes": []
        }
        
        # Get all slots for this class, sorting values from the returned set to retain consistent order
        all_slots = sorted(schemaview.class_induced_slots(class_name), key=lambda slot: slot.name)

        # Process each slot for this class
        for slot_info in all_slots:
            # Create the attribute entry with the exact structure requested
            attribute = {
                "name": slot_info.name,
                "title": slot_info.title if slot_info.title is not None else slot_info.name,  # Use title from schema if available
                "description": slot_info.description or "",
                "range": slot_info.range if slot_info.range is not None else "string",
                "required": slot_info.required if slot_info.required is not None else False,
                "multivalued": slot_info.multivalued if slot_info.multivalued is not None else False
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
                for pv_name in (enum_info.permissible_values or {}):
                    values_list.append(pv_name)
                if values_list:
                    attribute["values"] = "; ".join(values_list)
            
            # Add the attribute to the class
            class_entry["attributes"].append(attribute)
        
        # Add the class to the output
        output["classes"].append(class_entry)
    
    return output

def generate_dictionary(schema_path=None, output_path=None):
    """
    Generate a data dictionary JSON from the specified schema file.
    
    Args:
        schema_path: Path to the schema file (default: core.yaml in the schema directory)
        output_path: Path to write the output JSON (default: standard path in data_dictionaries directory)
    """
    # Get paths
    current_dir = Path(__file__).parent
    project_root = current_dir.parent.parent.parent
    
    # Default to core.yaml if no schema path is provided
    if schema_path is None:
        # Get the path to the schema directory
        schema_dir = current_dir.parent / "schema"
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
    with open(output_path, "w", encoding="utf-8") as fh:
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
