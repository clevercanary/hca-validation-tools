#!/usr/bin/env python
# -*- coding: utf-8 -*-

from enum import Enum
import re
import pandas as pd
import sys
import time
import os
import json
from pathlib import Path
from typing import Any, Mapping, Optional, List, Union, Callable
from dataclasses import dataclass
from pydantic import ValidationError
from linkml_runtime import SchemaView

from .common import default_entity_types

# Import dotenv for loading environment variables
from dotenv import load_dotenv

# Import libraries for Google API access
import gspread
from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession
from google.auth.credentials import Credentials
import requests.adapters
import urllib3
import requests

@dataclass
class ApiInstances:
    """Container for instances of APIs used in the validation process."""
    gspread: gspread.Client
    drive: Any

@dataclass
class WorksheetInfo:
    """Container for Google Sheets worksheet data and metadata."""
    data: pd.DataFrame
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
class SpreadsheetMetadata:
    """Container for Google Sheet metadata"""
    spreadsheet_title: str
    last_updated_date: str
    last_updated_by: str
    last_updated_email: Optional[str]
    can_edit: bool

@dataclass
class SpreadsheetInfo:
    """Container for Google Sheet data and metadata."""
    spreadsheet_metadata: SpreadsheetMetadata
    worksheets: List[WorksheetInfo]

@dataclass
class SheetReadError(Exception):
    """Exception raised when reading a Google Sheet fails."""
    error_code: str
    error_message: Optional[str] = None
    spreadsheet_metadata: Optional[SpreadsheetMetadata] = None
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
    input_fix: Optional[str] = None

@dataclass
class SheetValidationResult:
    """Container for general info on the outcome of a Google Sheet validation."""
    successful: bool
    spreadsheet_metadata: Optional[SpreadsheetMetadata]
    error_code: Optional[str]
    summary: Mapping[str, int | None]
    errors: List[SheetErrorInfo]

# Custom sentinel value used to detect missing parameters
class MissingSentinel(Enum):
    MISSING = 0

MISSING = MissingSentinel.MISSING

# Possible bionetworks that a sheet may be associated with
allowed_bionetwork_names = [
  "adipose",
  "breast",
  "development",
  "eye",
  "genetic-diversity",
  "gut",
  "heart",
  "immune",
  "kidney",
  "liver",
  "lung",
  "musculoskeletal",
  "nervous-system",
  "oral",
  "organoid",
  "pancreas",
  "reproduction",
  "skin",
]

# Mapping of supported entity types to information about how they're represented in spreadsheets
sheet_structure_by_entity_type = {
    "dataset": {
        "sheet_index": 0,
        "primary_key_field": "dataset_id"
    },
    "donor": {
        "sheet_index": 1,
        "primary_key_field": "donor_id"
    },
    "sample": {
        "sheet_index": 2,
        "primary_key_field": "sample_id"
    }
}

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

def create_requests_session(credentials: Credentials) -> requests.Session:
    """
    Create a requests session with retry behavior configured
    """
    session = AuthorizedSession(gspread.utils.convert_credentials(credentials))
    retry_cfg = urllib3.Retry(
        total=4,
        status_forcelist=(429, 500, 502, 503, 504),
        backoff_factor=10,
        backoff_jitter=5,
        respect_retry_after_header=True
    )
    session.mount("https://", requests.adapters.HTTPAdapter(max_retries=retry_cfg))
    return session

def init_apis() -> ApiInstances:
    import os
    import json
    import traceback
    import gspread
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError as GoogleHttpError
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
        raise SheetReadError(error_code='auth_missing')
    
    # Log the length and first few characters of the credentials to verify they're present
    logger.info(f"Service account credentials found: Length={len(service_account_json)} chars")
    
    # Check if the credentials contain unresolved secret references
    # Check for CloudFormation resolve syntax
    if service_account_json.startswith('{{resolve:'):
        logger.error(f"Service account credentials were not resolved from Secrets Manager (CloudFormation syntax): {service_account_json[:50]}...")
        logger.error("Check that the Lambda function has the correct permissions to access the secret and that the secret exists.")
        raise SheetReadError(error_code='auth_unresolved')
    
    # Check for AWS shorthand syntax
    if service_account_json.startswith('aws:secretsmanager:'):
        logger.error(f"Service account credentials were not resolved from Secrets Manager (AWS shorthand syntax): {service_account_json[:50]}...")
        logger.error("Check that the Lambda function has the correct permissions to access the secret and that the secret exists.")
        raise SheetReadError(error_code='auth_unresolved')
    
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
            raise SheetReadError(error_code='auth_invalid_format')
        
        logger.info(f"Creating credentials object for service account: {credentials_dict.get('client_email')}")
        
        # Create credentials object
        try:
            credentials = service_account.Credentials.from_service_account_info(
                credentials_dict,
                scopes=[
                    'https://www.googleapis.com/auth/spreadsheets',
                    'https://www.googleapis.com/auth/drive.metadata.readonly'
                ]
            )
            logger.info("Successfully created credentials object")
        except Exception as cred_error:
            logger.error(f"Error creating Google credentials object: {cred_error}")
            raise SheetReadError(error_code='auth_error')
        
        # Authenticate with gspread
        logger.info("Authorizing with gspread...")
        try:
            gc = gspread.authorize(credentials, session=create_requests_session(credentials))
            logger.info("Successfully authorized with gspread")
        except Exception as auth_error:
            logger.error(f"Error authorizing with Google Sheets API: {auth_error}")
            raise SheetReadError(error_code='auth_error')
        
        # Authenticate with Drive API
        logger.info("Authorizing with Drive API...")
        try:
            drive = build("drive", "v3", credentials=credentials)
            logger.info("Successfully authorized with Drive API")
        except Exception as auth_error:
            logger.error(f"Error authorizing with Google Drive API: {auth_error}")
            raise SheetReadError(error_code='auth_error')
        
        return ApiInstances(gspread=gc, drive=drive)
    
    except json.JSONDecodeError as json_error:
        logger.error(f"Invalid JSON format in service account credentials: {json_error}")
        raise SheetReadError(error_code='auth_invalid_format')
    except gspread.exceptions.APIError as e:
        logger.error(f"Google Sheets API error: {e}")
        raise SheetReadError(
            error_code='api_error',
            error_message=f"Received error {e.code} from Google Sheets API: {e.error['message']}"
        )
    except GoogleHttpError as e:
        logger.error(f"Google API error: {e}")
        raise SheetReadError(
            error_code="api_error",
            error_message=f"Received error {e.status_code} from Google API: {e.reason}"
        )
    except requests.exceptions.RetryError as e:
        logger.error(f"Reached maximum configured API retries: {e}")
        raise SheetReadError(error_code="max_api_retries")
    except SheetReadError as e:
        raise e
    except Exception as e:
        logger.error(f"Unexpected error initializing APIs with service account: {e}")
        logger.error(f"Exception type: {type(e).__name__}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise SheetReadError(error_code='api_error')

def read_worksheets(
    sheet_id: str,
    spreadsheet_metadata: SpreadsheetMetadata,
    spreadsheet: gspread.Spreadsheet,
    sheet_indices: List[int]
) -> tuple[List[WorksheetInfo], List[gspread.Worksheet]]:
    import logging
    logger = logging.getLogger(__name__)
    
    # Get list of worksheets

    all_worksheets = spreadsheet.worksheets()
    worksheets: List[gspread.Worksheet] = []

    logger.info(f"Attempting to get worksheets of spreadsheet {sheet_id} at indices: {', '.join(str(i) for i in sheet_indices)}")
    for sheet_index in sheet_indices:
        if not sheet_index < len(all_worksheets):
            logger.error(f"Error accessing Google Sheet with service account: Worksheet index {sheet_index} not found in sheet {sheet_id}")
            raise SheetReadError(error_code='worksheet_not_found', spreadsheet_metadata=spreadsheet_metadata)
        worksheets.append(all_worksheets[sheet_index])
    
    logger.info(f"Successfully retrieved worksheets")

    # Get data from worksheets
    
    logger.info("Retrieving worksheets data...")

    api_result = spreadsheet.values_batch_get([gspread.utils.absolute_range_name(worksheet.title) for worksheet in worksheets])

    worksheets_info = []

    for sheet_index, worksheet, value_range in zip(sheet_indices, worksheets, api_result["valueRanges"]):
        data = gspread.utils.fill_gaps(value_range.get("values", [[]]))
         # Convert to DataFrame
        if len(data) >= 2:
            logger.info(f"Successfully retrieved data from worksheet index {sheet_index}: {len(data)} rows, {len(data[0]) if data[0] else 0} columns")
            source_columns = data[0]
            source_rows_start_index = 1
            df = pd.DataFrame(data[source_rows_start_index:], columns=source_columns)  # First row as header
            worksheets_info.append(
                WorksheetInfo(
                    data=df,
                    worksheet_id=worksheet.id,
                    source_columns=source_columns,
                    source_rows_start_index=source_rows_start_index
                )
            )
        else:
            logger.warning(f"Sheet {sheet_id} (index {sheet_index}) appears to be empty")
            raise SheetReadError(error_code="sheet_data_empty", spreadsheet_metadata=spreadsheet_metadata, worksheet_id=worksheet.id)
    
    return worksheets_info, worksheets

def read_sheet_with_service_account(sheet_id: str, entity_types: List[str] = ["dataset"], apis: Optional[ApiInstances] = None) -> tuple[SpreadsheetInfo, List[gspread.Worksheet]]:
    """
    Read data from a Google Sheet using a service account for authentication.
    
    Args:
        sheet_id (str): The ID of the Google Sheet to read.
        sheet_indices (List[int], optional): The indices of the worksheets to read. Defaults to [0].
        
    Returns:
        info: SpreadsheetInfo object containing list of WorksheetInfo corresponding to
            the list of sheet indices
        worksheets: List of gspread worksheets
    
    Raises:
        SheetReadError containing error code and, if available, sheet title and worksheet ID
    """
    import traceback
    import gspread
    from googleapiclient.errors import HttpError as GoogleHttpError
    import logging
    
    # Configure logging
    logger = logging.getLogger(__name__)
    
    # Get sheet indices
    sheet_indices = [sheet_structure_by_entity_type[t]["sheet_index"] for t in entity_types]

    # If not provided, initialize APIs
    if apis is None:
        apis = init_apis()

    # Set up a variable to hold spreadsheet metadata so that it can be referenced if an unexpected type of error occurs after metadata is obtained
    spreadsheet_metadata = None

    try:
        try:
            # Open the spreadsheet and get the worksheets
            logger.info(f"Attempting to open spreadsheet with ID: {sheet_id}")
            spreadsheet = apis.gspread.open_by_key(sheet_id)
            
            # Get the spreadsheet title
            sheet_title = spreadsheet.title
            logger.info(f"Successfully opened spreadsheet: '{sheet_title}'")

            # Get the spreadsheet metadata from Drive
            logger.info(f"Attempting to get metadata for spreadsheet with ID: {sheet_id}")
            file_metadata = apis.drive.files().get(fileId=sheet_id, fields="modifiedTime, lastModifyingUser(displayName, emailAddress), capabilities(canModifyContent)").execute()
            last_updated_date = file_metadata["modifiedTime"]
            last_modifying_user = file_metadata.get("lastModifyingUser", {})
            last_updated_by = last_modifying_user.get("displayName", "unknown")
            last_updated_email = last_modifying_user.get("emailAddress") or None
            can_edit = file_metadata["capabilities"]["canModifyContent"]
            logger.info(f"Successfully got metadata from Drive API")
        
            spreadsheet_metadata = SpreadsheetMetadata(
                spreadsheet_title=sheet_title,
                last_updated_date=last_updated_date,
                last_updated_by=last_updated_by,
                last_updated_email=last_updated_email,
                can_edit=can_edit
            )

            # Get all worksheets
            sheets_info, gspread_worksheets = read_worksheets(sheet_id, spreadsheet_metadata, spreadsheet, sheet_indices)
            
            return SpreadsheetInfo(spreadsheet_metadata, sheets_info), gspread_worksheets
        
        except gspread.exceptions.SpreadsheetNotFound:
            logger.error(f"Sheet {sheet_id} not found. Check if the sheet ID is correct.")
            logger.error(f"Error accessing Google Sheet with service account: Sheet {sheet_id} not found or not accessible with provided credentials")
            raise SheetReadError(error_code='sheet_not_found', spreadsheet_metadata=spreadsheet_metadata)
        except PermissionError as e:
            logger.error(f"Permission denied accessing sheet {sheet_id}: {e}")
            logger.error(f"Make sure the service account has access to the sheet.")
            raise SheetReadError(error_code='permission_denied', spreadsheet_metadata=spreadsheet_metadata)
        except gspread.exceptions.APIError as e:
            logger.error(f"Google Sheets API error: {e}")
            raise SheetReadError(
                error_code='api_error',
                error_message=f"Received error {e.code} from Google Sheets API: {e.error['message']}",
                spreadsheet_metadata=spreadsheet_metadata
            )
        except GoogleHttpError as e:
            logger.error(f"Google API error: {e}")
            raise SheetReadError(
                error_code="api_error",
                error_message=f"Received error {e.status_code} from Google API: {e.reason}",
                spreadsheet_metadata=spreadsheet_metadata
            )
        except requests.exceptions.RetryError as e:
            logger.error(f"Reached maximum configured API retries: {e}")
            raise SheetReadError(error_code="max_api_retries", spreadsheet_metadata=spreadsheet_metadata)
            
    except SheetReadError as e:
        raise e
    except Exception as e:
        logger.error(f"Unexpected error accessing Google Sheet with service account: {e}")
        logger.error(f"Exception type: {type(e).__name__}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise SheetReadError(error_code='api_error', spreadsheet_metadata=spreadsheet_metadata)

def normalize_dataframe_values(df: pd.DataFrame, schemaview: SchemaView, class_name: str) -> pd.DataFrame:
    """
    Normalize a dataframe by dropping columns with empty names and casting types according to the given schema class.
    """

    class_slots_by_name = {
        slot.name: slot for slot in schemaview.class_induced_slots(class_name)
    }

    # An integer should consist of an optional negative sign, followed by either a nonzero number of non-seperated digits,
    # or 1-3 digits followed by a nonzero number of comma-separated three-digit groups
    int_re = re.compile(r"^-?(?:\d+|\d{1,3}(?:,\d{3})+)$")
    
    def parse_int(value):
        if int_re.fullmatch(value) is None:
            return value
        return int(value.replace(",", ""))

    def parse_list(value, parse_item):
        return [parse_item(item.strip()) for item in value.split(";")] if value.strip() else []

    def map_column(name):
        # Get slot info from schema if available
        slot = class_slots_by_name.get(name)
        
        # Determine how to parse a non-empty value in this column
        parse_value = parse_int if slot is not None and slot.range == "integer" else lambda v: v
        if slot is not None and slot.multivalued:
            parse_item = parse_value
            parse_value = lambda v: parse_list(v, parse_item)

        # Map over the column, converting whitespace-only value to None and parsing other values where applicable
        # Use the Series constructor with a list comprehension to ensure that values are put directly into an object series and can't be cast by Pandas
        return pd.Series([None if value.strip() == "" else parse_value(value) for value in df[name]], dtype="object", index=df.index)

    return pd.DataFrame({
        name: map_column(name)
        for name in df.columns
        if name and name.strip() != ""
    })

def make_summary_without_entities(error_count: int, entity_types: List[str] = default_entity_types) -> dict[str, int | None]:
    return {
        **{f"{entity_type}_count": None for entity_type in entity_types},
        "error_count": error_count
    }

def make_validation_result_for_whole_sheet_error(
    *,
    sheet_id: str,
    entity_types: List[str],
    error_code: str,
    error_message: Optional[str] = None,
    spreadsheet_metadata: Optional[SpreadsheetMetadata] = None,
    worksheet_id: Optional[int] = None,
    entity_type: Optional[str] = None
) -> SheetValidationResult:
    error_msg = error_message or f"Error processing sheet {sheet_id} (Error: {error_code})"
    error_info = SheetErrorInfo(
        entity_type=entity_type,
        worksheet_id=worksheet_id,
        message=error_msg
    )
    return SheetValidationResult(
        successful=False,
        spreadsheet_metadata=spreadsheet_metadata,
        error_code=error_code,
        summary=make_summary_without_entities(1, entity_types),
        errors=[error_info]
    )

def make_read_error_validation_result(sheet_id: str, entity_types: List[str], read_error: SheetReadError) -> SheetValidationResult:
    import logging
    logger = logging.getLogger()

    error_msg = (
        read_error.error_message
        or f"Could not access or read data from sheet {sheet_id} (Error: {read_error.error_code})"
    )
    logger.warning(f"Sheet access failed with error code: {read_error.error_code}")
    
    logger.warning(f"{error_msg}")
    return make_validation_result_for_whole_sheet_error(
        sheet_id=sheet_id,
        entity_types=entity_types,
        error_code=read_error.error_code,
        error_message=error_msg,
        spreadsheet_metadata=read_error.spreadsheet_metadata,
        worksheet_id=read_error.worksheet_id
    )

def handle_validation_error(
        validation_error: ValidationError,
        *,
        validation_summary: dict[str, int],
        validation_errors_list: List[SheetErrorInfo],
        entity_type: str,
        sheet_info: WorksheetInfo,
        row_index: int | MissingSentinel = MISSING,
        row_id: Optional[Any] | MissingSentinel = MISSING
):
    for error in validation_error.errors():
        # Update error count
        validation_summary["error_count"] += 1
        
        # Use row index from error if possible
        error_row_index = error.get("ctx", {}).get("row_index", row_index)
        if error_row_index is MISSING: raise ValueError(f"No row index provided for {entity_type} error {error}")
        # Use row ID from error if possible
        error_row_id = error.get("ctx", {}).get("row_id", row_id)
        if error_row_id is MISSING: raise ValueError(f"No row ID provided for {entity_type} error {error}")
        # Get field name if available
        error_column_name = None if len(error["loc"]) == 0 else error["loc"][0]
        # Get A1 if possible
        try:
            error_a1 = sheet_info.get_a1(error_row_index, error_column_name)
        except ValueError:
            error_a1 = None
        # Save error info to provided list
        validation_errors_list.append(
            SheetErrorInfo(
                entity_type=entity_type,
                worksheet_id=sheet_info.worksheet_id,
                message=error["msg"],
                row=error_row_index,
                column=error_column_name,
                cell=error_a1,
                primary_key=error_row_id,
                input=error["input"],
                # Leave empty to be potentially populated after the sheet has been fully processed by the validator
                input_fix=None
            )
        )

def validate_google_sheet(
    sheet_id: str,
    *,
    entity_types: List[str] = default_entity_types,
    bionetwork: Optional[str] = None,
    sheet_read_result: Optional[SpreadsheetInfo] = None,
    apis: Optional[ApiInstances] = None,
) -> SheetValidationResult:
    """
    Validate data from a Google Sheet starting at row 6 until the first empty row.
    Uses service account credentials from environment variables to access the sheet.
    
    Args:
        sheet_id: The ID of the Google Sheet (required)
        entity_types: List of entity types to validate. Determines which worksheets are read and which schema is used for each.
        bionetwork: Optional string identifying the biological network context.
        
    Returns:
        SheetValidationResult: Object with fields:
        - successful: boolean indicating if validation passed
        - spreadsheet_metadata: object containing title and last update information, or None
        - error_code: string indicating the type of error or None if successful
        - summary: dict containing entity counts (set to None if unavailable) and error count
    """
    # --- Parameter validation -------------------------------------------------
    if not sheet_id:
        raise ValueError("sheet_id is required for validate_google_sheet()")
    if bionetwork is not None and bionetwork not in allowed_bionetwork_names:
        raise ValueError(f"'{bionetwork}' is not a valid bionetwork")

    from hca_validation.validator import validate, validate_id_uniqueness
    from hca_validation.schema_utils import load_schemaview, get_entity_class_name
    import logging
    logger = logging.getLogger()

    invalid_entity_types = [t for t in entity_types if t not in sheet_structure_by_entity_type]
    if invalid_entity_types:
        raise ValueError(f"Invalid entity types: {', '.join(invalid_entity_types)}")

    # Load schema for use in interpreting and validating input values
    schemaview = load_schemaview()
    
    if sheet_read_result is None:
        logger.info(f"Reading sheet: {sheet_id}")
        try:
            # Read the sheet with service account credentials
            sheet_read_result = read_sheet_with_service_account(
                sheet_id,
                entity_types,
                apis
            )[0]
        except SheetReadError as read_error:
            return make_read_error_validation_result(sheet_id, entity_types, read_error)
    
    # Mapping from entity type to dataframe of rows to validate, with normalized values, and an index containing the original 1-based indices of the rows
    rows_to_validate_by_entity_type = {}

    for entity_type, sheet_info in zip(entity_types, sheet_read_result.worksheets):
        df = sheet_info.data

        # Skip the first column if it has no slot name
        if len(df.columns) > 1 and df.columns[0].strip() == "":
            df = df.iloc[:, 1:]
        
        # Print information about the sheet structure
        logger.info(f"Sheet has {len(df)} {entity_type} rows total")
        
        # Find rows with actual data to validate
        row_indices = []
        
        # Debug: Print the first few rows to understand the structure
        logger.debug("Sheet structure:")
        for i in range(min(10, len(df))):
            if i < len(df):
                first_col = df.iloc[i, 0] if not pd.isna(df.iloc[i, 0]) else "<empty>"
                logger.debug(f"Row {i+1} (index {i}): {first_col}")
        
        # Process from row 6 until the first empty row
        start_row_index = 4  # Row 6 (1-based including header) is index 4 (0-based excluding header)
        current_row_index = start_row_index
        
        logger.info(f"Processing {entity_type} data rows starting from row 6 (index {start_row_index})...")
        
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
            row_indices.append(current_row_index)
            
            # Move to the next row
            current_row_index += 1
        
        if not row_indices:
            error_msg = f"No data found to validate starting from {entity_type} row 6."
            logger.warning(error_msg)
            return make_validation_result_for_whole_sheet_error(
                sheet_id=sheet_id,
                entity_types=entity_types,
                error_code="no_data",
                error_message=error_msg,
                spreadsheet_metadata=sheet_read_result.spreadsheet_metadata,
                worksheet_id=sheet_info.worksheet_id,
                entity_type=entity_type
            )
        
        logger.info(f"Found {len(row_indices)} {entity_type} rows to validate.")

        # Set the dataframe index to 1-based indices
        df = df.reset_index(drop=True)
        df.index += 1

        # Get the subset of rows that should be validated
        source_rows_to_validate = df.iloc[row_indices]

        # Save the dataframe with normalized values
        rows_to_validate_by_entity_type[entity_type] = normalize_dataframe_values(
            source_rows_to_validate,
            schemaview,
            get_entity_class_name(entity_type, bionetwork)
        )
    
    # Set up validation summary with entity counts and initial error count
    validation_summary = {
        **{f"{entity_type}_count": len(rows_df) for entity_type, rows_df in rows_to_validate_by_entity_type.items()},
        "error_count": 0
    }

    # Initialize list of validation errors
    validation_errors = []

    all_valid = True

    for entity_type, sheet_info in zip(entity_types, sheet_read_result.worksheets):
        # Determine schema class name to use for validation
        class_name = get_entity_class_name(entity_type, bionetwork)
        # Get normalized dataframe of rows to validate
        rows_to_validate = rows_to_validate_by_entity_type[entity_type]
        all_valid_in_worksheet = True
        # Validate uniqueness and report results
        uniqueness_validation_error = validate_id_uniqueness(rows_to_validate, schemaview, class_name)
        if uniqueness_validation_error:
            all_valid_in_worksheet = False
            handle_validation_error(
                uniqueness_validation_error,
                validation_summary=validation_summary,
                validation_errors_list=validation_errors,
                entity_type=entity_type,
                sheet_info=sheet_info
            )
        # Validate each row
        for row_index, row in rows_to_validate.iterrows():
            # Convert row to dictionary
            row_dict = row.to_dict()
            
            primary_key_field = sheet_structure_by_entity_type[entity_type]["primary_key_field"]
            row_primary_key = f"{primary_key_field}:{row_dict[primary_key_field]}" if primary_key_field in row_dict else None

            # Validate the data
            try:
                validation_error = validate(row_dict, class_name=class_name)
                # Report results
                if validation_error:
                    all_valid_in_worksheet = False
                    handle_validation_error(
                        validation_error,
                        validation_summary=validation_summary,
                        validation_errors_list=validation_errors,
                        entity_type=entity_type,
                        sheet_info=sheet_info,
                        row_index=row_index,
                        row_id=row_primary_key
                    )
            except Exception as e:
                all_valid_in_worksheet = False
                # Update error count
                validation_summary["error_count"] += 1
                # Store error info
                validation_errors.append(
                    SheetErrorInfo(
                        entity_type=entity_type,
                        worksheet_id=sheet_info.worksheet_id,
                        message=str(e),
                        row=row_index,
                        primary_key=row_primary_key
                    )
                )

        if all_valid_in_worksheet:
            logger.info(f"All {len(rows_to_validate)} {entity_type} rows are valid!")
        else:
            all_valid = False
            logger.warning(f"Validation found errors in some of the {len(rows_to_validate)} {entity_type} rows.")
            logger.warning("Please check the schema requirements and update the data accordingly.")
            logger.info(f"Schema location: {os.path.join(os.path.dirname(__file__), f'../../schema/{entity_type}.yaml')}")
    
    # Summary
    if all_valid:
        logger.info(f"All rows for the {len(entity_types)} specified entity types are valid!")
        return SheetValidationResult(
            successful=True,
            spreadsheet_metadata=sheet_read_result.spreadsheet_metadata,
            error_code=None,
            summary=validation_summary,
            errors=validation_errors
        )
    else:
        logger.warning(f"Validation found errors in some of the {len(entity_types)} entity types.")
        return SheetValidationResult(
            successful=False,
            spreadsheet_metadata=sheet_read_result.spreadsheet_metadata,
            error_code='validation_error',
            summary=validation_summary,
            errors=validation_errors
        )


if __name__ == "__main__":
    # Expect a sheet_id argument when run as a script
    if len(sys.argv) < 2:
        print("Usage: python -m hca_validation.entry_sheet_validator.validate_sheet SHEET_ID", file=sys.stderr)
        sys.exit(1)

    sheet_id = sys.argv[1]
    validate_google_sheet(sheet_id)
