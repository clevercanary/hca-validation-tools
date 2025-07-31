import copy
import dataclasses
from typing import List, Optional
from linkml_runtime import SchemaView
from linkml_runtime.linkml_model.meta import ClassDefinition

from hca_validation.schema_utils import load_schemaview, get_entity_class_name
from .validate_sheet import SheetErrorInfo


# Spreadsheet values to identify possible fixes for
# Mapping tuple of entity type, slot, and input value to corrected value
sheet_value_fix_map = {
    ("donor", "manner_of_death", "not_applicable"): "not applicable",
    ("sample", "sample_source", "surgical_donor"): "surgical donor",
    ("sample", "sample_source", "postmortem_donor"): "postmortem donor",
    ("sample", "sample_source", "living_organ_donor"): "living organ donor",
    ("sample", "sample_collection_method", "surgical_resection"): "surgical resection",
    ("sample", "sample_collection_method", "blood_draw"): "blood draw",
    ("sample", "sample_collection_method", "body_fluid"): "body fluid",
}


def get_fixed_value(entity_type: str, entity_induced_class: ClassDefinition, slot_name: str, value: str) -> Optional[str]:
    # We only need to check `attributes`, since an induced class has nothing in `slots`
    if slot_name not in entity_induced_class.attributes:
        return None
    return sheet_value_fix_map.get((entity_type, slot_name, value))


def add_fix_to_error_if_available(error: SheetErrorInfo, bionetwork: Optional[str], schemaview: SchemaView) -> SheetErrorInfo:
    # If the error doesn't have the required values, return it unchanged
    # Require string input value to avoid values that consist of the entire input row
    if error.entity_type is None or error.column is None or not isinstance(error.input, str):
        return error
    
    entity_induced_class = schemaview.induced_class(get_entity_class_name(error.entity_type, bionetwork))
    input_fix = get_fixed_value(error.entity_type, entity_induced_class, error.column, error.input)

    return dataclasses.replace(error, input_fix=input_fix)


def add_fixes_to_errors(errors: List[SheetErrorInfo], bionetwork: Optional[str]) -> List[SheetErrorInfo]:
    """
    Identify fixes for the given errors where possible, and return copies of the error objects with fixed values specified.

    Args:
        errors: List of error info objects
        bionetwork: Bionetwork associated with the data the errors come from
    
    Returns:
        List of errors with fixes added where possible
    """

    schemaview = load_schemaview()

    return [add_fix_to_error_if_available(error, bionetwork, schemaview) for error in errors]
