import dataclasses
from typing import List, Optional
import gspread

from .validate_sheet import SheetReadError, SheetValidationResult, init_apis, make_read_error_validation_result, make_validation_result_for_whole_sheet_error, read_sheet_with_service_account, validate_google_sheet
from .find_fixes import add_fixes_to_errors
from .apply_fixes import apply_fixes
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
    - If the spreadsheet is editable, applying the fixes and revalidating

    Args:
        sheet_id: The ID of the Google Sheet (required)
        entity_types: List of entity types to validate. Determines which worksheets are read and which schema is used for each.
        bionetwork: Optional string identifying the biological network context.
        
    Returns:
        SheetValidationResult object
    """

    import logging
    logger = logging.getLogger(__name__)

    # Initialize sheet_data variable so it can be referenced during exception handling
    sheet_data = None

    try:
        # Initialize APIs
        apis = init_apis()

        # Read spreadsheet
        sheet_data, gspread_worksheets = read_sheet_with_service_account(sheet_id, entity_types, apis)

        # Get validation result
        validation_result = validate_google_sheet(sheet_id, entity_types=entity_types, bionetwork=bionetwork, sheet_read_result=sheet_data)

        # Add available fixes to errors
        validation_result = dataclasses.replace(validation_result, errors=add_fixes_to_errors(validation_result.errors, bionetwork))

        # If the spreadsheet is editable, apply any available fixes
        if validation_result.spreadsheet_metadata is not None and validation_result.spreadsheet_metadata.can_edit:
            made_changes = apply_fixes(validation_result, entity_types, gspread_worksheets, sheet_id)

            # If the spreadsheet was updated, re-validate
            if made_changes:
                validation_result = validate_google_sheet(sheet_id, entity_types=entity_types, bionetwork=bionetwork, apis=apis)
                # Verify that fixes are no longer available, and log an error otherwise
                errors_with_fix_info = add_fixes_to_errors(validation_result.errors, bionetwork)
                if any(error.input_fix is not None for error in errors_with_fix_info):
                    logger.error(f"Sheet {sheet_id} still has fixes available after fixes were applied")
        
        # Return validation result
        return validation_result
    
    except gspread.exceptions.APIError as e:
        logger.error(f"Google Sheets API error: {e}")
        return make_validation_result_for_whole_sheet_error(
            sheet_id=sheet_id,
            entity_types=entity_types,
            error_code="api_error",
            error_message=f"Received error {e.code} from Google Sheets API: {e.error['message']}",
            spreadsheet_metadata=None if sheet_data is None else sheet_data.spreadsheet_metadata
        )
    except SheetReadError as read_error:
        return make_read_error_validation_result(sheet_id, entity_types, read_error)
