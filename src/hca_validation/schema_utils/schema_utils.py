import os
from typing import Optional
from linkml_runtime import SchemaView
from linkml_runtime.linkml_model.meta import ClassDefinition

# Map schema types and bionetworks to their corresponding class names
schema_classes = {
    "dataset": {
      "DEFAULT": "Dataset",
      "adipose": "AdiposeDataset",
      "gut": "GutDataset"
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


def get_class_identifier_name(schemaview: SchemaView, class_name: str) -> str:
    for slot in schemaview.class_induced_slots(class_name):
        if slot.identifier:
            return slot.name
    raise ValueError(f"No identifier slot found for class {class_name}")
