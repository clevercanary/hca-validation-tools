"""
HCA Validation Tools - Main Validator Module

This module provides the main validation functionality for HCA data using Pydantic models.
"""
from typing import Dict, Any, Optional
from pydantic import ValidationError

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
