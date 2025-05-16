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

from .expand_schema import expand

def transform_schema_to_data_dictionary(schema_dict: Dict[str, Any]) -> Dict[str, Any]:
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
    
    # Process each class in the schema
    for class_name, class_info in schema_dict.get("classes", {}).items():
        # Skip abstract classes or other non-relevant classes
        if class_info.get("abstract", False) or class_name not in class_name_mapping:
            continue
            
        # Create the class entry with title-cased name for title
        class_entry = {
            "title": class_name.title(),  # Ensure title case
            "description": class_info.get("description", ""),
            "name": class_name_mapping.get(class_name, class_name.lower()),  # Use lowercase name
            "attributes": []
        }
        
        # Get all slots for this class
        all_slots = []
        
        # Add slots directly defined in the class
        if "slots" in class_info:
            all_slots.extend(class_info["slots"])
            
        # Add slots from mixins/parents
        if "is_a" in class_info:
            parent_class = class_info["is_a"]
            if parent_class in schema_dict.get("classes", {}):
                parent_slots = schema_dict["classes"][parent_class].get("slots", [])
                all_slots.extend(parent_slots)
        
        # Process each slot for this class
        for slot_name in all_slots:
            if slot_name in schema_dict.get("slots", {}):
                slot_info = schema_dict["slots"][slot_name]
                
                # Create the attribute entry with the exact structure requested
                attribute = {
                    "name": slot_name,
                    "title": slot_info.get("title", slot_name),  # Use title from schema if available
                    "description": slot_info.get("description", ""),
                    "range": slot_info.get("range", "string"),
                    "required": slot_info.get("required", False),
                    "multivalued": slot_info.get("multivalued", False)
                }
                
                # Add examples if available
                if "examples" in slot_info and len(slot_info["examples"]) > 0:
                    # Get the first example value
                    example = slot_info["examples"][0]
                    if isinstance(example, dict) and "value" in example:
                        attribute["example"] = example["value"]
                    else:
                        attribute["example"] = str(example)
                
                # Add annotations if available - format as requested
                if "annotations" in slot_info:
                    formatted_annotations = {}
                    for annot_name, annot_info in slot_info["annotations"].items():
                        if isinstance(annot_info, dict) and "value" in annot_info:
                            formatted_annotations[annot_name] = annot_info["value"]
                        else:
                            formatted_annotations[annot_name] = annot_info
                    attribute["annotations"] = formatted_annotations
                
                # Add rationale if available in comments - as a string, not an array
                if "comments" in slot_info:
                    if isinstance(slot_info["comments"], list):
                        attribute["rationale"] = "\n".join(slot_info["comments"])
                    else:
                        attribute["rationale"] = slot_info["comments"]
                
                # Add values information if available in notes - as a string, not an array
                if "notes" in slot_info:
                    if isinstance(slot_info["notes"], list):
                        attribute["values"] = "\n".join(slot_info["notes"])
                    else:
                        attribute["values"] = slot_info["notes"]
                
                # If this is an enum, add the values
                if "range" in slot_info and slot_info["range"] in schema_dict.get("enums", {}):
                    enum_info = schema_dict["enums"][slot_info["range"]]
                    values_list = []
                    for pv_name, pv_info in enum_info.get("permissible_values", {}).items():
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
    
    # Expand the schema
    schema_dict = expand(schema_path)
    
    # Transform the schema into the requested format
    data_dict = transform_schema_to_data_dictionary(schema_dict)
    
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
