"""
HCA Validation Tools - Main Validator Module

This module provides the main validation functionality for HCA data using Pydantic models.
"""
from typing import Dict, Any, Optional
from linkml_runtime import SchemaView
from pydantic import ValidationError
import pandas as pd
from pydantic_core import InitErrorDetails, PydanticCustomError

import hca_validation.schema.generated.core as schema



# Map schema types and bionetworks to their corresponding class names
schema_classes = {
    "dataset": {
      "DEFAULT": "Dataset",
      "gut": "GutDataset"
    },
    "donor": {
      "DEFAULT": "Donor"
    },
    "sample": {
      "DEFAULT": "Sample",
      "gut": "GutSample"
    },
    "cell": {
      "DEFAULT": "Cell"
    }
}


def get_entity_class_name(schema_type: str, bionetwork: Optional[str] = None) -> str:
    # Validate schema type
    if schema_type not in schema_classes:
        raise ValueError(f"Unsupported schema type: {schema_type}. "
                       f"Supported types are: {', '.join(schema_classes.keys())}")
    
    type_classes = schema_classes[schema_type]
    return type_classes.get(bionetwork, type_classes["DEFAULT"])


def validate(data: Dict[str, Any], *, class_name: str) -> Optional[ValidationError]:
    """
    Validate HCA data against a schema using Pydantic models.
    
    Args:
        data: The data to validate as a dictionary
        schema_type: Type of schema to validate against ('dataset', 'donor', 'sample', 'cell')
        
    Returns:
        Returns a Pydantic ValidationError if validation fails, or None if validation succeeds
        
    Raises:
        ValueError: If an unsupported schema type is provided
    """
    
    try:
        # Validate using the appropriate Pydantic model
        model = getattr(schema, class_name)
        model.model_validate(data)
        return None
    except ValidationError as e:
        # Return validation error
        return e


def get_class_identifier_name(schemaview: SchemaView, class_name: str) -> str:
    for slot in schemaview.class_induced_slots(class_name):
        if slot.identifier:
            return slot.name
    raise ValueError(f"No identifier slot found for class {class_name}")


def validate_id_uniqueness(data: pd.DataFrame, schemaview: SchemaView, class_name: str) -> Optional[ValidationError]:
    """
    Validate that no entities in the given data have duplicate IDs.

    Args:
        data: A dataframe containing the entities to validate
        schemaview: The schemaview to use to determine the identifier slot
        class_name: The schema class name of the entities being validated
    
    Returns:
        A Pydantic ValidationError if any duplicate IDs appear, or None otherwise
    """

    id_name = get_class_identifier_name(schemaview, class_name)

    if id_name not in data:
        return None
    
    # Get IDs that are not missing and appear multiple times
    duplicate_ids = data[id_name][data[id_name].notna() & data[id_name].duplicated(keep=False)]

    if len(duplicate_ids) == 0:
        return None
    
    def get_row_error_details(index, id) -> InitErrorDetails:
        ctx = {
            "row_index": index,
            "row_id": id
        }
        return {
            "type": PydanticCustomError("duplicate_id", "Duplicate identifier {row_id}", ctx),
            "loc": (id_name,),
            "input": id,
            "ctx": ctx
        }

    return ValidationError.from_exception_data(
        title="Duplicate identifiers",
        line_errors=[
            get_row_error_details(index, value)
            for index, value in duplicate_ids.items()
        ]
    )
