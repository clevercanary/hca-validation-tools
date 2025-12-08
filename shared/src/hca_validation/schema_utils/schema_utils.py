import os
from typing import List, Optional
from linkml_runtime import SchemaView
from linkml_runtime.linkml_model.meta import ClassDefinition

# Map entity types and bionetworks to their corresponding class names
schema_classes = {
    "dataset": {
      "DEFAULT": "Dataset",
      "adipose": "AdiposeDataset",
      "gut": "GutDataset",
      "musculoskeletal": "MusculoskeletalDataset",
    },
    "donor": {
      "DEFAULT": "Donor"
    },
    "sample": {
      "DEFAULT": "Sample",
      "adipose": "AdiposeSample",
      "gut": "GutSample"
    },
    "cell": {
      "DEFAULT": "Cell"
    }
}

# Derive mapping from class name to entity type
entity_types_by_class = dict((class_name, entity_type) for entity_type, network_mapping in schema_classes.items() for _, class_name in network_mapping.items())


def load_schemaview():
    # Get the schema path
    module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schema_path = os.path.join(module_dir, "schema/core.yaml")
    # Create a schemaview
    return SchemaView(schema_path)


def get_entity_class_name(schema_type: str, bionetwork: Optional[str] = None) -> str:
    # Validate schema type
    if schema_type not in schema_classes:
        raise ValueError(f"Unsupported schema type: {schema_type}. "
                       f"Supported types are: {', '.join(schema_classes.keys())}")
    
    type_classes = schema_classes[schema_type]
    return type_classes.get(bionetwork, type_classes["DEFAULT"])


def get_class_entity_type(class_name: str) -> str:
    if class_name not in entity_types_by_class:
        raise ValueError(f"Unknown schema class: {class_name}")
    return entity_types_by_class[class_name]


def get_class_identifier_name(schemaview: SchemaView, class_name: str) -> str:
    for slot in schemaview.class_induced_slots(class_name):
        if slot.identifier:
            return slot.name
    raise ValueError(f"No identifier slot found for class {class_name}")


def get_class_foreign_keys(schemaview: SchemaView, class_name: str):
    """
    Get list of (slot name, slot range) tuples for slots of the given class that hold references to other classes.

    Args:
      schemaview: Schemaview to get class and slot info from
      class_name: Name of class to get slots for
    
    Returns:
      List of (slot name, slot range) tuples
    """
    foreign_keys = []
    classes = schemaview.all_classes()
    for slot in schemaview.class_induced_slots(class_name):
        if slot.inlined is False and slot.range in classes:
            foreign_keys.append((slot.name, slot.range))
    return foreign_keys
