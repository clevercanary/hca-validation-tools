"""
HCA Validation Tools - Main Validator Module

This module provides the main validation functionality for HCA data using Pydantic models.
"""
from typing import Dict, Any, Optional
from pydantic import ValidationError

from hca_validation.schema.generated.core import Dataset, GutDataset, Donor, Sample, GutSample, Cell

# Map schema types and bionetworks to their corresponding Pydantic models
schema_models = {
    "dataset": {
      "DEFAULT": Dataset,
      "gut": GutDataset
    },
    "donor": {
      "DEFAULT": Donor
    },
    "sample": {
      "DEFAULT": Sample,
      "gut": GutSample
    },
    "cell": {
      "DEFAULT": Cell
    }
}


def validate(data: Dict[str, Any], schema_type: str, bionetwork: Optional[str] = None) -> Optional[ValidationError]:
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
    
    # Validate schema type
    if schema_type not in schema_models:
        raise ValueError(f"Unsupported schema type: {schema_type}. "
                       f"Supported types are: {', '.join(schema_models.keys())}")
    
    try:
        # Validate using the appropriate Pydantic model
        type_models = schema_models[schema_type]
        model = type_models.get(bionetwork, type_models["DEFAULT"])
        model.model_validate(data)
        return None
    except ValidationError as e:
        # Return validation error
        return e
