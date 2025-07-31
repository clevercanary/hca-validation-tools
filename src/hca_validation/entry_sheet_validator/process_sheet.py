import dataclasses
from typing import List, Optional

from .validate_sheet import SheetValidationResult, validate_google_sheet
from .find_fixes import add_fixes_to_errors
from .common import default_entity_types

def process_google_sheet(
    sheet_id: str,
    *,
    entity_types: List[str] = default_entity_types,
    bionetwork: Optional[str] = None,
) -> SheetValidationResult:
    """
    Process a Google Sheet by:
    - Validating it according to the HCA schema
    - Identifying fixes where possible for any resulting validation errors

    Args:
        sheet_id: The ID of the Google Sheet (required)
        entity_types: List of entity types to validate. Determines which worksheets are read and which schema is used for each.
        bionetwork: Optional string identifying the biological network context.
        
    Returns:
        SheetValidationResult object
    """

    # Get validation result
    validation_result = validate_google_sheet(sheet_id, entity_types=entity_types, bionetwork=bionetwork)

    # Return with available fixes added to errors
    return dataclasses.replace(validation_result, errors=add_fixes_to_errors(validation_result.errors, bionetwork))
