"""HCA Validator - extends cellxgene Validator with HCA-specific rules."""

import re
from pathlib import Path

import pandas as pd
import yaml

from hca_schema_validator._vendored.cellxgene_schema.validate import Validator
from hca_schema_validator._vendored.cellxgene_schema.utils import getattr_anndata
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
    
    def __init__(self, ignore_labels=True):
        """
        Initialize HCA validator.

        Args:
            ignore_labels: If True, skip label validation
        """
        super().__init__(ignore_labels=ignore_labels)
        # Initialize all validator state so the exception handler in
        # validate_adata() works even if reset() hasn't been called yet.
        self.reset()
    
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

    def _deep_check(self):
        """
        The base class skips raw validation when *any* errors exist, but raw
        validation only depends on assay_ontology_term_id. We retry it here
        so raw-layer errors are reported in the same pass.
        """
        super()._deep_check()

        # Match by substring to avoid brittle coupling to exact upstream wording
        raw_skip_warnings = [
            w for w in self.warnings
            if "Validation of raw layer was not performed" in w
        ]
        if (
            raw_skip_warnings
            and "raw" in self.schema_def
            and "assay_ontology_term_id" in self.adata.obs.columns
        ):
            for w in raw_skip_warnings:
                self.warnings.remove(w)
            self._validate_raw()

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

    def _validate_dataframe(self, df_name):
        """
        Extends base dataframe validation with requirement_level support.

        Columns with requirement_level: strongly_recommended are removed from
        the schema before the base class runs (so it won't error on missing),
        then validated separately with warnings instead of errors.
        """
        df_definition = self.schema_def["components"].get(df_name, {})
        if "columns" not in df_definition:
            return super()._validate_dataframe(df_name)

        # Extract strongly_recommended columns before base class sees them
        sr_columns = {}
        for col_name in list(df_definition["columns"]):
            col_def = df_definition["columns"][col_name]
            if col_def.get("requirement_level") == "strongly_recommended":
                sr_columns[col_name] = col_def
                del df_definition["columns"][col_name]

        # Base class validates only must columns
        try:
            super()._validate_dataframe(df_name)
        finally:
            # Restore schema def even if super() raises
            df_definition["columns"].update(sr_columns)

        # Validate strongly_recommended columns ourselves
        df = getattr_anndata(self.adata, df_name)
        if df is not None:
            for col_name, col_def in sr_columns.items():
                self._validate_strongly_recommended(df, df_name, col_name, col_def)

    def _validate_strongly_recommended(self, df, df_name, col_name, col_def):
        """Validate a strongly_recommended column: warn on missing/NaN, error on blocklist."""
        if col_name not in df.columns:
            self.warnings.append(
                f"Column '{col_name}' in dataframe '{df_name}' is strongly "
                f"recommended but missing."
            )
            return

        column = df[col_name]

        # NaN check — warn with count
        null_mask = column.isnull()
        if null_mask.any():
            nan_count = int(null_mask.sum())
            total = len(column)
            pct = (nan_count * 100 // total) if total > 0 else 0
            self.warnings.append(
                f"Column '{col_name}' is strongly recommended. "
                f"{nan_count}/{total} ({pct}%) values are NaN."
            )

        # Separator check — reject values containing list separators
        separators = {",", ";", "|"}
        bad_sep_values = [
            str(v) for v in column.dropna().unique()
            if any(sep in str(v) for sep in separators)
        ]
        if bad_sep_values:
            shown = bad_sep_values[:3]
            self.errors.append(
                f"Column '{col_name}' in dataframe '{df_name}' contains "
                f"values with list separators (e.g., {shown}). Each value "
                f"must be a single identifier, not a delimited list."
            )

        # Blocklist check — error on invalid values (case-insensitive)
        if "blocklist" in col_def:
            blocklist = {v.lower() for v in col_def["blocklist"]}
            bad_values = [
                str(v) for v in column.dropna().unique()
                if str(v).strip().lower() in blocklist
            ]
            if bad_values:
                self.errors.append(
                    f"Column '{col_name}' in dataframe '{df_name}' contains "
                    f"invalid values {bad_values}. Placeholder values are not "
                    f"allowed. Leave the value missing (NaN/None) if not known."
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
            description = column_def.get("pattern_description")
            for value in column.drop_duplicates():
                if pd.isna(value):
                    continue
                if not compiled_pattern.fullmatch(str(value)):
                    if description:
                        self.errors.append(
                            f"Column '{column_name}' in dataframe '{df_name}' contains a value "
                            f"'{value}' which is not valid. Expected {description}."
                        )
                    else:
                        self.errors.append(
                            f"Column '{column_name}' in dataframe '{df_name}' contains a value "
                            f"'{value}' that does not match the required pattern '{column_def['pattern']}'."
                        )
