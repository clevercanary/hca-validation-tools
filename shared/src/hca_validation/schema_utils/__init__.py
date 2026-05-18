"""
HCA Validation Tools - Schema Utils Module

This module provides utilities for interacting with the HCA schema.
"""

from .schema_utils import (
    load_schemaview,
    get_entity_class_name,
    get_class_entity_type,
    get_class_identifier_name,
    get_class_foreign_keys,
    get_slot_anndata_location,
    is_deprecated_slot,
    coverage_classes,
    iter_coverage_slots,
)
