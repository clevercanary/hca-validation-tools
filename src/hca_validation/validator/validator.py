"""
HCA Validation Tools - Main Validator Module

This module provides the main validation functionality for HCA data.
"""
from typing import Dict, Any, Optional, Union, TextIO, BinaryIO, IO
import os

from linkml.validator import Validator
from linkml.validator.plugins import PydanticValidationPlugin


# Module-level cache for validators
_validators = {}


def _create_validator(schema_type: str):
    """
    Create a validator for the specified schema type.
    
    Args:
        schema_type: Type of schema to validate against ('dataset', 'donor', 'sample', 'cell')
        
    Returns:
        A LinkML validator configured with the appropriate Pydantic plugin
    """
    # Validate schema type
    supported_types = ['dataset', 'donor', 'sample', 'cell']
    if schema_type not in supported_types:
        raise ValueError(f"Unsupported schema type: {schema_type}. "
                         f"Supported types are: {', '.join(supported_types)}")
    
    # Get the schema path
    module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schema_path = os.path.join(module_dir, 'schema', f"{schema_type}.yaml")
    
    # Create and return the validator
    return Validator(
        schema=schema_path,
        validation_plugins=[PydanticValidationPlugin(closed=False)]
    )


def validate(data: Dict[str, Any], schema_type: str = "dataset") -> Any:
    """
    Validate HCA data against a schema.
    
    Args:
        data: The data to validate as a dictionary
        schema_type: Type of schema to validate against ('dataset', 'donor', 'sample', 'cell')
        
    Returns:
        The validation report from LinkML
    """
    # Get or create validator
    if schema_type not in _validators:
        _validators[schema_type] = _create_validator(schema_type)
    
    # Use validator
    validator = _validators[schema_type]
    return validator.validate(data, target_class=schema_type.capitalize())


def clear_cache():
    """
    Clear the validator cache.
    
    This can be useful in testing or when you want to force recreation of validators.
    """
    global _validators
    _validators = {}
