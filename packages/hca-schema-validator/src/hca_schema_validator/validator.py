"""HCA Validator - extends cellxgene Validator with HCA-specific rules."""

import re
from pathlib import Path

import pandas as pd
import yaml

from hca_schema_validator._vendored.cellxgene_schema.validate import Validator
from . import __schema_version__ as HCA_SCHEMA_VERSION

# Schema file constants
SCHEMA_DIR = "schema_definitions"
SCHEMA_FILENAME = "hca_schema_definition.yaml"


class HCAValidator(Validator):
    """
    HCA-specific validator extending cellxgene schema validation.
    
    Uses a custom schema definition that differs from CELLxGENE in key areas:
    - organism and organism_ontology_term_id are in obs (not uns)
    """
    
    def __init__(self, ignore_labels=False):
        """
        Initialize HCA validator.
        
        Args:
            ignore_labels: If True, skip label validation
        """
        super().__init__(ignore_labels=ignore_labels)
    
    def _set_schema_def(self):
        """
        Sets schema dictionary using HCA-specific schema definition.
        
        Overrides the base method to load HCA's custom schema instead of
        the default CELLxGENE schema.
        """
        if not self.schema_version:
            # Use HCA schema version
            self.schema_version = HCA_SCHEMA_VERSION
        
        if not self.schema_def:
            # Load HCA-specific schema
            schema_path = Path(__file__).parent / SCHEMA_DIR / SCHEMA_FILENAME
            
            with open(schema_path) as fp:
                self.schema_def = yaml.safe_load(fp)

    def _validate_list(self, list_name, current_list, element_type):
        """
        Extends base list validation with support for element_type: string.

        Validates that all elements are non-empty strings when element_type is "string".
        """
        super()._validate_list(list_name, current_list, element_type)
        if element_type == "string":
            for i in current_list:
                if not isinstance(i, str):
                    self.errors.append(
                        f"Value '{i}' in list '{list_name}' is not valid, it must be a string."
                    )
                elif len(i.strip()) == 0:
                    self.errors.append(
                        f"Value in list '{list_name}' must not be empty or whitespace-only."
                    )

    def _validate_column(self, column, column_name, df_name, column_def, default_error_message_suffix=None):
        """
        Extends base column validation with support for regex pattern matching.

        When a column_def contains a "pattern" key, validates that all non-NaN values
        match the specified regex pattern.
        """
        super()._validate_column(column, column_name, df_name, column_def, default_error_message_suffix)
        if "pattern" in column_def:
            compiled_pattern = re.compile(column_def["pattern"])
            for value in column.drop_duplicates():
                if pd.isna(value):
                    continue
                if not compiled_pattern.fullmatch(str(value)):
                    self.errors.append(
                        f"Column '{column_name}' in dataframe '{df_name}' contains a value "
                        f"'{value}' that does not match the required pattern '{column_def['pattern']}'."
                    )
