#!/usr/bin/env python
# -*- coding: utf-8 -*-

import pandas as pd
import sys
import time
import os
import json
from pathlib import Path
from typing import Any, Optional, List, Union
from dataclasses import dataclass
from pydantic_core import ErrorDetails

# Import dotenv for loading environment variables
from dotenv import load_dotenv

# Import gspread for Google Sheets API access
import gspread
from google.oauth2 import service_account

@dataclass
class SheetInfo:
    """Container for Google Sheet data and metadata."""
    data: pd.DataFrame
    spreadsheet_title: str
    worksheet_id: int
    source_columns: List[Any]
    source_rows_start_index: int

    def get_a1(self, row, column):
        """
        Get A1 notation given a 1-based row index and a column name
        """
        return gspread.utils.rowcol_to_a1(
            self.source_rows_start_index + row,
            self.source_columns.index(column) + 1
        )

@dataclass
class ReadErrorSheetInfo:
    """Container for info regarding a failed read of a Google Sheet."""
    error_code: str
    spreadsheet_title: Optional[str] = None
    worksheet_id: Optional[int] = None

@dataclass
class SheetErrorInfo:
    """Container for info regarding an error that occurred while reading and validating a Google Sheet."""
    entity_type: Optional[str]
    worksheet_id: Optional[int]
    message: str
    row: Optional[int] = None
    column: Optional[Any] = None
    cell: Optional[str] = None
    primary_key: Optional[str] = None
    input: Optional[Any] = None

# Load environment variables from .env file if it exists
dotenv_path = Path(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))) / '.env'
if dotenv_path.exists():
    load_dotenv(dotenv_path=dotenv_path)

def get_secret_from_extension(secret_name):
    """
    Retrieve a secret from the AWS Parameters and Secrets Lambda Extension.
    
    Args:
        secret_name (str): The name of the secret to retrieve.
        
    Returns:
        str: The secret value, or None if there was an error.
    """
    import os
    import requests
    import json
    import logging
    
    logger = logging.getLogger(__name__)
    
    # Constants for the Secrets Extension
    SECRETS_EXTENSION_PORT = 2773
    SECRETS_EXTENSION_ENDPOINT = f"http://localhost:{SECRETS_EXTENSION_PORT}/secretsmanager/get?secretId"
    
    # Check if we're running in a Lambda environment
    if 'AWS_LAMBDA_FUNCTION_NAME' not in os.environ:
        logger.info("Not running in Lambda environment, skipping extension")
        return None
    
    try:
        logger.info(f"Retrieving secret {secret_name} from extension...")
        headers = {"X-Aws-Parameters-Secrets-Token": os.environ.get("AWS_SESSION_TOKEN", "")}
        url = f"{SECRETS_EXTENSION_ENDPOINT}={secret_name}"
        
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        secret_data = response.json()
        logger.info(f"Successfully retrieved secret {secret_name}")
        return secret_data.get("SecretString")
    except Exception as e:
        logger.error(f"Error retrieving secret from extension: {e}")
        return None

def read_sheet_with_service_account(sheet_id, sheet_index=0) -> Union[SheetInfo, ReadErrorSheetInfo]:
    """
    Read data from a Google Sheet using a service account for authentication.
    
    Args:
        sheet_id (str): The ID of the Google Sheet to read.
        sheet_index (int, optional): The index of the worksheet to read. Defaults to 0.
        
    Returns:
        SheetInfo: A dataclass containing the sheet data, title, and any error code.
    """
    import os
    import json
    import traceback
    import pandas as pd
    import gspread
    from google.oauth2 import service_account
    import logging
    
    # Configure logging
    logger = logging.getLogger(__name__)
    
    # Get the environment (default to 'dev' if not specified)
    environment = os.environ.get("ENVIRONMENT", "dev")
    secret_name = f"{environment}/hca-atlas-tracker/google-service-account"
    
    # Try to get service account credentials from the AWS Parameters and Secrets Lambda Extension
    service_account_json_from_extension = get_secret_from_extension(secret_name)
    
    # If we got credentials from the extension, use those
    if service_account_json_from_extension:
        logger.info("Using service account credentials from AWS Parameters and Secrets Lambda Extension")
        service_account_json = service_account_json_from_extension
    else:
        # Fall back to environment variable
        logger.info("Falling back to environment variable for service account credentials")
        service_account_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT', None)
    
    if not service_account_json:
        error_msg = "No service account credentials found in GOOGLE_SERVICE_ACCOUNT environment variable or Secrets Extension"
        logger.error(error_msg)
        return ReadErrorSheetInfo(error_code='auth_missing')
    
    # Log the length and first few characters of the credentials to verify they're present
    logger.info(f"Service account credentials found: Length={len(service_account_json)} chars")
    
    # Check if the credentials contain unresolved secret references
    # Check for CloudFormation resolve syntax
    if service_account_json.startswith('{{resolve:'):
        logger.error(f"Service account credentials were not resolved from Secrets Manager (CloudFormation syntax): {service_account_json[:50]}...")
        logger.error("Check that the Lambda function has the correct permissions to access the secret and that the secret exists.")
        return ReadErrorSheetInfo(error_code='auth_unresolved')
    
    # Check for AWS shorthand syntax
    if service_account_json.startswith('aws:secretsmanager:'):
        logger.error(f"Service account credentials were not resolved from Secrets Manager (AWS shorthand syntax): {service_account_json[:50]}...")
        logger.error("Check that the Lambda function has the correct permissions to access the secret and that the secret exists.")
        return ReadErrorSheetInfo(error_code='auth_unresolved')
    
    try:
        # Parse the service account JSON
        logger.info("Attempting to parse service account JSON...")
        credentials_dict = json.loads(service_account_json)
        
        # Log some non-sensitive parts of the credentials to verify structure
        safe_keys = ['type', 'project_id', 'client_email', 'auth_uri', 'token_uri']
        cred_info = {k: credentials_dict.get(k) for k in safe_keys if k in credentials_dict}
        logger.info(f"Parsed credentials structure: {json.dumps(cred_info)}")
        
        # Verify the required fields are present
        required_fields = ['private_key', 'client_email', 'token_uri']
        missing_fields = [field for field in required_fields if field not in credentials_dict]
        if missing_fields:
            error_msg = f"Service account credentials missing required fields: {missing_fields}"
            logger.error(error_msg)
            logger.error(f"Error: {error_msg}. Check that the service account JSON has the correct format and contains all required fields.")
            return ReadErrorSheetInfo(error_code='auth_invalid_format')
        
        logger.info(f"Creating credentials object for service account: {credentials_dict.get('client_email')}")
        
        # Create credentials object
        try:
            credentials = service_account.Credentials.from_service_account_info(
                credentials_dict,
                scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
            )
            logger.info("Successfully created credentials object")
        except Exception as cred_error:
            logger.error(f"Error creating Google credentials object: {cred_error}")
            return ReadErrorSheetInfo(error_code='auth_error')
        
        # Authenticate with gspread
        logger.info("Authorizing with gspread...")
        try:
            gc = gspread.authorize(credentials)
            logger.info("Successfully authorized with gspread")
        except Exception as auth_error:
            logger.error(f"Error authorizing with Google Sheets API: {auth_error}")
            return ReadErrorSheetInfo(error_code='auth_error')
        
        try:
            # Open the spreadsheet and get the worksheet
            logger.info(f"Attempting to open spreadsheet with ID: {sheet_id}")
            spreadsheet = gc.open_by_key(sheet_id)
            
            # Get the spreadsheet title
            sheet_title = spreadsheet.title
            logger.info(f"Successfully opened spreadsheet: '{sheet_title}'")
            
            # Get the worksheet
            logger.info(f"Attempting to get worksheet at index {sheet_index}")
            worksheet = spreadsheet.get_worksheet(sheet_index)
            
            # Get the worksheet ID
            worksheet_id = worksheet.id
            logger.info(f"Successfully retrieved worksheet with ID: {worksheet_id}")
            
            # Get all values from the worksheet
            logger.info("Retrieving worksheet data...")
            data = worksheet.get_all_values()
            
            # Convert to DataFrame
            if len(data) >= 2:
                logger.info(f"Successfully retrieved data: {len(data)} rows, {len(data[0]) if data[0] else 0} columns")
                source_columns = data[0]
                source_rows_start_index = 1
                df = pd.DataFrame(data[source_rows_start_index:], columns=source_columns)  # First row as header
                return SheetInfo(
                    data=df,
                    spreadsheet_title=sheet_title,
                    worksheet_id=worksheet_id,
                    source_columns=source_columns,
                    source_rows_start_index=source_rows_start_index
                )
            else:
                logger.warning(f"Sheet {sheet_id} (index {sheet_index}) appears to be empty")
                return ReadErrorSheetInfo(error_code="sheet_data_empty", spreadsheet_title=sheet_title, worksheet_id=worksheet_id)
                
        except gspread.exceptions.SpreadsheetNotFound:
            logger.error(f"Sheet {sheet_id} not found. Check if the sheet ID is correct.")
            logger.error(f"Error accessing Google Sheet with service account: Sheet {sheet_id} not found or not accessible with provided credentials")
            return ReadErrorSheetInfo(error_code='sheet_not_found')
        except gspread.exceptions.WorksheetNotFound:
            logger.error(f"Worksheet index {sheet_index} not found in sheet {sheet_id}")
            logger.error(f"Error accessing Google Sheet with service account: Worksheet index {sheet_index} not found in sheet {sheet_id}")
            return ReadErrorSheetInfo(error_code='worksheet_not_found')
        except gspread.exceptions.APIError as e:
            if "PERMISSION_DENIED" in str(e):
                logger.error(f"Permission denied accessing sheet {sheet_id}: {e}")
                logger.error(f"Make sure the service account has access to the sheet.")
                return ReadErrorSheetInfo(error_code='permission_denied')
            else:
                logger.error(f"Google Sheets API error: {e}")
                return ReadErrorSheetInfo(error_code='api_error')
            
    except json.JSONDecodeError as json_error:
        logger.error(f"Invalid JSON format in service account credentials: {json_error}")
        return ReadErrorSheetInfo(error_code='auth_invalid_format')
    except Exception as e:
        logger.error(f"Unexpected error accessing Google Sheet with service account: {e}")
        logger.error(f"Exception type: {type(e).__name__}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return ReadErrorSheetInfo(error_code='api_error')

def validate_google_sheet(sheet_id="1oPFb6qb0Y2HeoQqjSGRe_TlsZPRLwq-HUlVF0iqtVlY", sheet_index=0, error_handler=None):
    """
    Validate data from a Google Sheet starting at row 6 until the first empty row.
    Uses service account credentials from environment variables to access the sheet.
    
    Args:
        sheet_id: The ID of the Google Sheet
        sheet_index: The index of the sheet (0-based)
        error_handler: Optional callback function that takes a SheetErrorInfo object
                      to handle validation errors externally
                      
    Returns:
        Tuple of (validation_success, sheet_title, error_code) where:
        - validation_success is a boolean indicating if validation passed
        - sheet_title is the title of the sheet or None
        - error_code is a string indicating the type of error or None if successful
    """
    from hca_validation.validator import validate
    import logging
    logger = logging.getLogger()

    # TODO derive entity type properly
    entity_type = "Dataset"
    
    logger.info(f"Reading sheet: {sheet_id}")
    
    # Read the sheet with service account credentials
    sheet_info = read_sheet_with_service_account(sheet_id, sheet_index)
    
    if isinstance(sheet_info, ReadErrorSheetInfo):
        error_msg = f"Could not access or read data from sheet {sheet_id} (Error: {sheet_info.error_code})"
        logger.error(f"Sheet access failed with error code: {sheet_info.error_code}")
        
        logger.error(f"{error_msg}")
        if error_handler:
            error_info = SheetErrorInfo(
                entity_type=entity_type,
                worksheet_id=sheet_info.worksheet_id,
                message=error_msg
            )
            error_handler(error_info)
        return False, sheet_info.spreadsheet_title, sheet_info.error_code
    
    df = sheet_info.data

    # Skip the first column as it has no slot name
    if len(df.columns) > 1:
        df = df.iloc[:, 1:]
    
    # Print information about the sheet structure
    logger.info(f"Sheet has {len(df)} rows total")
    
    # Find rows with actual data to validate
    rows_to_validate = []
    row_indices = []
    
    # Debug: Print the first few rows to understand the structure
    logger.debug("Sheet structure:")
    for i in range(min(10, len(df))):
        if i < len(df):
            first_col = df.iloc[i, 0] if not pd.isna(df.iloc[i, 0]) else "<empty>"
            logger.debug(f"Row {i+1} (index {i}): {first_col}")
    
    # Process rows 4, 5, and then from row 6 until the first empty row
    # We'll include rows 4 and 5 as you mentioned they also contain data
    data_row_indices = [3, 4]  # Rows 4 and 5 (0-based indices 3 and 4)
    
    # First add rows 4 and 5
    for idx in data_row_indices:
        if idx < len(df):
            row = df.iloc[idx]
            # Skip completely empty rows
            if not row.isna().all() and not all(str(val).strip() == '' for val in row if not pd.isna(val)):
                logger.debug(f"Adding row {idx + 1} for validation")
                rows_to_validate.append(row)
                row_indices.append(idx)
    
    # Then process from row 6 until the first empty row
    start_row_index = 5  # Row 6 (1-based) is index 5 (0-based)
    current_row_index = start_row_index
    
    logger.info(f"Processing data rows starting from row 6 (index {start_row_index})...")
    
    while current_row_index < len(df):
        # Get the current row
        row = df.iloc[current_row_index]
        
        # Check if row is empty (all values are NaN or empty strings)
        is_empty = row.isna().all() or all(str(val).strip() == '' for val in row if not pd.isna(val))
        
        if is_empty:
            # Stop at the first empty row
            logger.debug(f"Found empty row at row {current_row_index + 1}, stopping")
            break
        
        # Add non-empty row for validation
        logger.debug(f"Adding row {current_row_index + 1} for validation")
        rows_to_validate.append(row)
        row_indices.append(current_row_index)
        
        # Move to the next row
        current_row_index += 1
    
    if not rows_to_validate:
        logger.warning("No data found to validate starting from row 6.")
        return False, sheet_info.spreadsheet_title, 'no_data'
    
    logger.info(f"Found {len(rows_to_validate)} rows to validate.")
    
    # Validate each row
    all_valid = True
    for i, row in enumerate(rows_to_validate):
        # Get the actual row number in the spreadsheet (1-based)
        row_index = row_indices[i] + 1  # Convert from 0-based index to 1-based row number
        
        # Convert row to dictionary and clean up
        row_dict = {}
        for key, value in row.to_dict().items():
            # Skip empty values and columns with no name
            if pd.isna(value) or not key or key.strip() == '':
                continue
                
            # Convert string representations of lists
            if isinstance(value, str) and value.strip().startswith('[') and value.strip().endswith(']'):
                try:
                    row_dict[key] = json.loads(value)  # Safely parse JSON-formatted strings
                except json.JSONDecodeError as e:
                    logger.warning(f"Could not parse list value '{value}' for field '{key}': {e}")
                    row_dict[key] = value
            else:
                row_dict[key] = value
        
        # TODO generalize
        row_primary_key = f"dataset_id:{row_dict['dataset_id']}" if "dataset_id" in row_dict else None

        # Validate the data
        logger.info(f"Validating row {row_index}...")
        try:
            validation_error = validate(row_dict, schema_type="dataset")
            
            # Report results
            if validation_error:
                all_valid = False
                logger.warning(f"Row {row_index} has validation errors:")
                for error in validation_error.errors():
                    logger.warning(f"  - {error['msg']}")
                    # Call error handler if provided
                    if error_handler:
                        error_column_name = None if len(error["loc"]) == 0 else error["loc"][0]
                        try:
                            error_a1 = sheet_info.get_a1(row_index, error_column_name)
                        except ValueError:
                            error_a1 = None
                        error_info = SheetErrorInfo(
                            entity_type=entity_type,
                            worksheet_id=sheet_info.worksheet_id,
                            message=error["msg"],
                            row=row_index,
                            column=error_column_name,
                            cell=error_a1,
                            primary_key=row_primary_key,
                            input=error["input"]
                        )
                        error_handler(error_info)
            else:
                logger.info(f"Row {row_index} is valid")
        except Exception as e:
            all_valid = False
            logger.error(f"Error validating row {row_index}: {e}")
            # Call error handler for exceptions if provided
            if error_handler:
                error_info = SheetErrorInfo(
                    entity_type=entity_type,
                    worksheet_id=sheet_info.worksheet_id,
                    message=str(e),
                    row=row_index,
                    primary_key=row_primary_key
                )
                error_handler(error_info)
    
    # Summary
    if all_valid:
        logger.info(f"All {len(rows_to_validate)} rows are valid!")
        return True, sheet_info.spreadsheet_title, None
    else:
        logger.warning(f"Validation found errors in some of the {len(rows_to_validate)} rows.")
        logger.warning("Please check the schema requirements and update the data accordingly.")
        logger.info(f"Schema location: {os.path.join(os.path.dirname(__file__), '../../schema/dataset.yaml')}")
        return False, sheet_info.spreadsheet_title, 'validation_error'


if __name__ == "__main__":
    # Get sheet ID from command line if provided
    sheet_id = sys.argv[1] if len(sys.argv) > 1 else "1oPFb6qb0Y2HeoQqjSGRe_TlsZPRLwq-HUlVF0iqtVlY"
    validate_google_sheet(sheet_id)
