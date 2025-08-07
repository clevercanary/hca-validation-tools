#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Test script for the HCA entry sheet validator module.

This script tests the functionality of the entry sheet validator, including:
1. Reading Google Sheets with service account authentication
2. Handling error conditions (sheet not found, access denied, etc.)
3. Validating sheet content
"""
import os
import json
from typing import List
import pytest
from unittest.mock import DEFAULT, patch, MagicMock, call
import pandas as pd
from google.oauth2.service_account import Credentials
import gspread
from gspread.exceptions import SpreadsheetNotFound, WorksheetNotFound, APIError

from hca_validation.entry_sheet_validator.validate_sheet import (
    ApiInstances,
    SheetReadError,
    SheetErrorInfo,
    SheetValidationResult,
    SpreadsheetInfo,
    SpreadsheetMetadata,
    WorksheetInfo,
    read_sheet_with_service_account,
    validate_google_sheet
)
from hca_validation.entry_sheet_validator.process_sheet import process_google_sheet

# Test sheet IDs
PUBLIC_SHEET_ID = "1oPFb6qb0Y2HeoQqjSGRe_TlsZPRLwq-HUlVF0iqtVlY"  # This is a public sheet
PRIVATE_SHEET_ID = "1Gp2yocEq9OWECfDgCVbExIgzYfM7s6nJV5ftyn-SMXQ"  # This is a private sheet
NONEXISTENT_SHEET_ID = "1aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"  # This sheet doesn't exist

# Sample data for mocking
SAMPLE_SHEET_DATA = pd.DataFrame({
    'column1': ['', '', '', '', 'value1', 'value2'],
    'column2': ['', '', '', '', 'value3', 'value4']
})
SAMPLE_SHEET_DATA_WITH_CASTS = pd.DataFrame({
    'contact_email': ['', '', '', '', "foo@example.com", '   ', 'bar@example.com'],
    'study_pi': ['', '', '', '', 'Foo', 'Bar; Baz', '']
})
SAMPLE_SHEET_DATA_WITH_INTEGERS = pd.DataFrame({
    'cell_number_loaded': ['', '', '', '', '1', '-23', '456', '', '7890', '1,234', '-56,789', '123,456', '78,901,234', '56,78', '9,012345'],
    # Required to prevent the empty value above from being treated as the end of the data
    'sample_id': ['', '', '', '', 'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k']
})
SAMPLE_SHEET_DATA_WITH_VALID_AND_MISSING_INTEGERS = pd.DataFrame({
    'cell_number_loaded': ['', '', '', '', '1', '-23', '', '7890'],
    # Required to prevent the empty value above from being treated as the end of the data
    'sample_id': ['', '', '', '', 'a', 'b', 'c', 'd']
})
SAMPLE_SHEET_DATA_WITH_DUPLICATE_IDS = pd.DataFrame({
    'dataset_id': ['', '', '', '', 'foo', 'bar', 'foo', '', '', 'baz', 'baz', 'baz'],
    # This column is required to prevent the empty IDs from being treated as the end of the data
    'description': ['', '', '', '', 'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']
})
SAMPLE_SHEET_DATA_WITH_FIXES = pd.DataFrame({
    'manner_of_death': ['', '', '', '', '1', 'unknown', 'not_applicable', '4', 'not applicable', 'not a manner of death', 'not_applicable'],
})

# Data to be compared with derived values
SAMPLE_SHEET_DATA_WITH_CASTS_EXPECTED_NORMALIZATION = [
    {"contact_email": "foo@example.com", "study_pi": ["Foo"]},
    {"contact_email": None, "study_pi": ["Bar", "Baz"]},
    {"contact_email": "bar@example.com", "study_pi": None},
]
SAMPLE_SHEET_DATA_WITH_INTEGERS_EXPECTED_NORMALIZATION = [
    {"sample_id": "a", "cell_number_loaded": 1},
    {"sample_id": "b", "cell_number_loaded": -23},
    {"sample_id": "c", "cell_number_loaded": 456},
    {"sample_id": "d", "cell_number_loaded": None},
    {"sample_id": "e", "cell_number_loaded": 7890},
    {"sample_id": "f", "cell_number_loaded": 1234},
    {"sample_id": "g", "cell_number_loaded": -56789},
    {"sample_id": "h", "cell_number_loaded": 123456},
    {"sample_id": "i", "cell_number_loaded": 78901234},
    {"sample_id": "j", "cell_number_loaded": "56,78"},
    {"sample_id": "k", "cell_number_loaded": "9,012345"},
]
SAMPLE_SHEET_DATA_WITH_VALID_AND_MISSING_INTEGERS_EXPECTED_NORMALIZATION = [
    {"sample_id": "a", "cell_number_loaded": 1},
    {"sample_id": "b", "cell_number_loaded": -23},
    {"sample_id": "c", "cell_number_loaded": None},
    {"sample_id": "d", "cell_number_loaded": 7890},
]
SAMPLE_SHEET_DATA_WITH_FIXES_EXPECTED_VALUE_RANGES = [
    {"range": "A8", "values": [["not applicable"]]},
    {"range": "A12", "values": [["not applicable"]]},
]


def _create_mock_spreadsheet_info(
    sheet_data=None,
    sheet_editable=False,
    datasets_sheet_data=None,
    donors_sheet_data=None,
    samples_sheet_data=None,
):
    """Helper function to create a SpreadsheetInfo object from test data."""

    if datasets_sheet_data is None:
        datasets_sheet_data = SAMPLE_SHEET_DATA if sheet_data is None else sheet_data
    if samples_sheet_data is not None and donors_sheet_data is None:
        donors_sheet_data = SAMPLE_SHEET_DATA
    
    worksheets = [
        WorksheetInfo(
            data=datasets_sheet_data,
            worksheet_id=123,
            source_columns=list(datasets_sheet_data.columns),
            source_rows_start_index=1
        )
    ]
    if donors_sheet_data is not None:
        worksheets.append(
            WorksheetInfo(
                data=donors_sheet_data,
                worksheet_id=456,
                source_columns=list(donors_sheet_data.columns),
                source_rows_start_index=1
            )
        )
    if samples_sheet_data is not None:
        worksheets.append(
            WorksheetInfo(
                data=samples_sheet_data,
                worksheet_id=789,
                source_columns=list(samples_sheet_data.columns),
                source_rows_start_index=1
            )
        )
    
    return SpreadsheetInfo(
        spreadsheet_metadata=SpreadsheetMetadata(
            spreadsheet_title="Test Sheet Title",
            last_updated_date="2025-06-06T22:43:57.554Z",
            last_updated_by="foo",
            last_updated_email="foo@example.com",
            can_edit=sheet_editable
        ),
        worksheets=worksheets
    )

def _test_validation_with_mock_sheets_response(
    validation_function,
    mock_read_service_account,
    *,
    bionetwork=None,
    sheet_data=None,
    datasets_sheet_data=None,
    donors_sheet_data=None,
    samples_sheet_data=None,
    expect_read_call=True,
    expected_apis_parameter=None,
    additional_arguments={}
) -> SheetValidationResult:
    """Helper function for testing validation with service account access, for a validation function with a call signature like validate_google_sheet."""

    # Mock successful service account read
    mock_spreadsheet_info = _create_mock_spreadsheet_info(
        sheet_data=sheet_data,
        datasets_sheet_data=datasets_sheet_data,
        donors_sheet_data=donors_sheet_data,
        samples_sheet_data=samples_sheet_data
    )
    mock_read_service_account.return_value = (
        mock_spreadsheet_info,
        [MagicMock() for _ in mock_spreadsheet_info.worksheets]
    )

    # Run validation
    validation_result = validation_function(PUBLIC_SHEET_ID, bionetwork=bionetwork, **additional_arguments)

    if expect_read_call:
        # If expected, verify service account method was used
        mock_read_service_account.assert_called_once_with(PUBLIC_SHEET_ID, ["dataset", "donor", "sample"], expected_apis_parameter)
    else:
        # Otherwise, verify sheet data was not read
        mock_read_service_account.assert_not_called()
    
    # Verify metadata is returned
    assert validation_result.spreadsheet_metadata
    assert validation_result.spreadsheet_metadata.spreadsheet_title == "Test Sheet Title"
    assert validation_result.spreadsheet_metadata.last_updated_date == "2025-06-06T22:43:57.554Z"
    assert validation_result.spreadsheet_metadata.last_updated_by == "foo"
    assert validation_result.spreadsheet_metadata.last_updated_email == "foo@example.com"
    # The mock data is in the format necessary to be parsed, but does not contain actual dataset fields, so we expect the 'validation_error' code
    assert validation_result.error_code == 'validation_error'
    
    return validation_result


class TestReadSheetWithServiceAccount:
    """Tests for the read_sheet_with_service_account function."""

    @pytest.fixture
    def mock_env_with_credentials(self):
        """Fixture to mock environment with service account credentials."""
        original_env = os.environ.copy()
        os.environ['GOOGLE_SERVICE_ACCOUNT'] = json.dumps({
            "type": "service_account",
            "project_id": "test-project",
            "private_key_id": "test-key-id",
            "private_key": "-----BEGIN PRIVATE KEY-----\nMOCK_PRIVATE_KEY_FOR_TESTING_ONLY\n-----END PRIVATE KEY-----\n",
            "client_email": "test@test-project.iam.gserviceaccount.com",
            "client_id": "123456789",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/test%40test-project.iam.gserviceaccount.com"
        })
        yield
        os.environ.clear()
        os.environ.update(original_env)

    def _mock_api_outputs(self, mock_client, mock_drive):
        """Helper function to set up mocks of values returned by the APIs."""

        # Mock the gspread client
        mock_sheet = MagicMock()
        mock_worksheet = MagicMock()

        # Mock the Drive API
        mock_get = MagicMock()
        mock_files = MagicMock()
        
        # Mock spreadsheet.values_batch_get
        mock_data = {
            "valueRanges": [{
                "values": [
                    ['header1', 'header2'],  # Headers
                    ['value1', 'value3'],    # Row 1
                    ['value2', 'value4']     # Row 2
                ]
            }]
        }
        mock_sheet.values_batch_get.return_value = mock_data
        mock_worksheet.id = 123
        mock_worksheet.title = "Test Worksheet"
        mock_sheet.worksheets.return_value = [mock_worksheet]
        mock_client.open_by_key.return_value = mock_sheet

        # Mock the sheet title
        mock_sheet.title = "Test Sheet Title"

        # Mock the Drive API response
        mock_get.execute.return_value = {
            "modifiedTime": "2025-06-06T22:43:57.554Z",
            "lastModifyingUser": {
                "displayName": "foo"
            },
            "capabilities": {
                "canModifyContent": True
            }
        }
        mock_files.get.return_value = mock_get
        mock_drive.files.return_value = mock_files

        return mock_sheet

    @patch('googleapiclient.discovery.build')
    @patch('hca_validation.entry_sheet_validator.validate_sheet.create_requests_session')
    @patch('gspread.authorize')
    @patch('google.oauth2.service_account.Credentials.from_service_account_info')
    def test_with_service_account_credentials(self, mock_credentials, mock_authorize, mock_create_requests_session, mock_build, mock_env_with_credentials):
        """Test reading a sheet with service account credentials."""
        # Mock the gspread client
        mock_client = MagicMock()
        mock_authorize.return_value = mock_client

        # Mock the Drive API
        mock_drive = MagicMock()
        mock_build.return_value = mock_drive

        mock_sheet = self._mock_api_outputs(mock_client, mock_drive)

        # Test the function
        sheet_read_result = read_sheet_with_service_account(PUBLIC_SHEET_ID)[0]
        assert isinstance(sheet_read_result, SpreadsheetInfo)
        assert sheet_read_result.spreadsheet_metadata.spreadsheet_title == "Test Sheet Title"
        assert sheet_read_result.spreadsheet_metadata.can_edit is True
        sheet_info = sheet_read_result.worksheets[0]
        assert sheet_info.data is not None
        assert isinstance(sheet_info.data, pd.DataFrame)
        assert not sheet_info.data.empty
        assert sheet_info.worksheet_id == 123
        assert sheet_info.source_columns == ["header1", "header2"]
        assert sheet_info.source_rows_start_index == 1
        
        # Verify the mocks were called correctly
        mock_credentials.assert_called_once()
        mock_authorize.assert_called_once()
        mock_client.open_by_key.assert_called_once_with(PUBLIC_SHEET_ID)
        mock_sheet.worksheets.assert_called_once()
        mock_build.assert_called_once()
        # Expect values_batch_get to have been called with a range consisting of the quoted worksheet title
        mock_sheet.values_batch_get.assert_called_once_with(["'Test Worksheet'"])

    @patch('googleapiclient.discovery.build')
    @patch('hca_validation.entry_sheet_validator.validate_sheet.create_requests_session')
    @patch('gspread.authorize')
    @patch('google.oauth2.service_account.Credentials.from_service_account_info')
    def test_pre_initialize_apis(self, mock_credentials, mock_authorize, mock_create_requests_session, mock_build, mock_env_with_credentials):
        """Test reading a sheet with pre-initialized APIs."""

        # Mock pre-initialized APIs
        mock_existing_client = MagicMock()
        mock_existing_drive = MagicMock()
        existing_apis = ApiInstances(gspread=mock_existing_client, drive=mock_existing_drive)

        self._mock_api_outputs(mock_existing_client, mock_existing_drive)

        # Test the function, passing in the API instances
        read_sheet_with_service_account(PUBLIC_SHEET_ID, apis=existing_apis)

        # Verify the provided API instances were used
        mock_existing_client.open_by_key.assert_called_once()
        mock_existing_drive.files.assert_called_once()

        # Verify new API instances were not created
        mock_authorize.assert_not_called()
        mock_build.assert_not_called()

    def test_without_service_account_credentials(self):
        """Test reading a sheet without service account credentials."""
        # Ensure no credentials are set
        if 'GOOGLE_SERVICE_ACCOUNT' in os.environ:
            del os.environ['GOOGLE_SERVICE_ACCOUNT']

        # The function should raise a read error containing only 'auth_missing' code when no credentials are available
        with pytest.raises(SheetReadError) as error_info:
            read_sheet_with_service_account(PUBLIC_SHEET_ID)
        assert error_info.value.error_code == 'auth_missing'
        assert error_info.value.spreadsheet_metadata is None
        assert error_info.value.worksheet_id is None
        
    def test_with_unresolved_credentials(self):
        """Test reading a sheet with unresolved credentials from Secrets Manager."""
        # Set credentials to a string that looks like an unresolved secret reference
        original_env = os.environ.copy()
        os.environ['GOOGLE_SERVICE_ACCOUNT'] = 'aws:secretsmanager:dev/hca-atlas-tracker/google-service-account'
        
        try:
            # The function should return read error containing only 'auth_unresolved' code when credentials weren't resolved
            with pytest.raises(SheetReadError) as error_info:
                read_sheet_with_service_account(PUBLIC_SHEET_ID)
            assert error_info.value.error_code == 'auth_unresolved'
            assert error_info.value.spreadsheet_metadata is None
            assert error_info.value.worksheet_id is None
        finally:
            # Restore original environment
            os.environ.clear()
            os.environ.update(original_env)
            
    def test_with_invalid_format_credentials(self):
        """Test reading a sheet with invalid format credentials."""
        # Set credentials to a valid JSON but missing required fields
        original_env = os.environ.copy()
        os.environ['GOOGLE_SERVICE_ACCOUNT'] = json.dumps({
            "type": "service_account",
            "project_id": "test-project"
            # Missing required fields: private_key, client_email, token_uri
        })
        
        try:
            # The function should return read error containing only 'auth_invalid_format' code when credentials are missing required fields
            with pytest.raises(SheetReadError) as error_info:
                read_sheet_with_service_account(PUBLIC_SHEET_ID)
            assert error_info.value.error_code == 'auth_invalid_format'
            assert error_info.value.spreadsheet_metadata is None
            assert error_info.value.worksheet_id is None
        finally:
            # Restore original environment
            os.environ.clear()
            os.environ.update(original_env)

    @patch('hca_validation.entry_sheet_validator.validate_sheet.create_requests_session')
    @patch('gspread.authorize')
    @patch('google.oauth2.service_account.Credentials.from_service_account_info')
    def test_sheet_not_found(self, mock_credentials, mock_authorize, mock_create_requests_session, mock_env_with_credentials):
        """Test handling of sheet not found error."""
        # Mock the gspread client to raise SpreadsheetNotFound
        mock_client = MagicMock()
        mock_client.open_by_key.side_effect = SpreadsheetNotFound("Sheet not found")
        mock_authorize.return_value = mock_client

        # The function should return read error containing only 'sheet_not_found' code when the sheet is not found
        with pytest.raises(SheetReadError) as error_info:
            read_sheet_with_service_account(NONEXISTENT_SHEET_ID)
        assert error_info.value.error_code == 'sheet_not_found'
        assert error_info.value.spreadsheet_metadata is None
        assert error_info.value.worksheet_id is None
        
        # Verify the mocks were called correctly
        mock_client.open_by_key.assert_called_once_with(NONEXISTENT_SHEET_ID)

    @patch('googleapiclient.discovery.build')
    @patch('hca_validation.entry_sheet_validator.validate_sheet.create_requests_session')
    @patch('gspread.authorize')
    @patch('google.oauth2.service_account.Credentials.from_service_account_info')
    def test_worksheet_not_found(self, mock_credentials, mock_authorize, mock_create_requests_session, mock_build, mock_env_with_credentials):
        """Test handling of missing worksheet."""
        # Mock the gspread client
        mock_client = MagicMock()
        mock_sheet = MagicMock()
        mock_sheet.worksheets.return_value = []
        mock_client.open_by_key.return_value = mock_sheet
        mock_authorize.return_value = mock_client

        # The function should return read error containing 'worksheet_not_found' code and spreadsheet metadata when the worksheet is not found
        with pytest.raises(SheetReadError) as error_info:
            read_sheet_with_service_account(PUBLIC_SHEET_ID)
        assert error_info.value.error_code == 'worksheet_not_found'
        assert error_info.value.spreadsheet_metadata is not None
        assert error_info.value.worksheet_id is None
        
        # Verify the mocks were called correctly
        mock_client.open_by_key.assert_called_once_with(PUBLIC_SHEET_ID)
        mock_sheet.worksheets.assert_called_once()

    @patch('hca_validation.entry_sheet_validator.validate_sheet.create_requests_session')
    @patch('gspread.authorize')
    @patch('google.oauth2.service_account.Credentials.from_service_account_info')
    def test_api_error(self, mock_credentials, mock_authorize, mock_create_requests_session, mock_env_with_credentials):
        """Test handling of API error."""
        # Mock the gspread client
        mock_client = MagicMock()
        # Use a generic Exception instead of APIError since it's difficult to mock correctly
        mock_client.open_by_key.side_effect = Exception("API error occurred")
        mock_authorize.return_value = mock_client

        # The function should return read error containing only 'api_error' code when an API error occurs
        with pytest.raises(SheetReadError) as error_info:
            read_sheet_with_service_account(PUBLIC_SHEET_ID)
        assert error_info.value.error_code == 'api_error'
        assert error_info.value.spreadsheet_metadata is None
        assert error_info.value.worksheet_id is None
        
        # Verify the mocks were called correctly
        mock_client.open_by_key.assert_called_once_with(PUBLIC_SHEET_ID)

    @patch('googleapiclient.discovery.build')
    @patch('hca_validation.entry_sheet_validator.validate_sheet.create_requests_session')
    @patch('gspread.authorize')
    @patch('google.oauth2.service_account.Credentials.from_service_account_info')
    def test_generic_exception_with_metadata(self, mock_credentials, mock_authorize, mock_create_requests_session, mock_build, mock_env_with_credentials):
        """Test handling of generic exception after spreadsheet metadata is obtained."""
        # Mock the gspread client
        mock_client = MagicMock()
        mock_sheet = MagicMock()
        mock_sheet.worksheets.side_effect = Exception("Exception")
        mock_client.open_by_key.return_value = mock_sheet
        mock_authorize.return_value = mock_client

        # The function should return read error containing 'api_error' code and spreadsheet metadata
        with pytest.raises(SheetReadError) as error_info:
            read_sheet_with_service_account(PUBLIC_SHEET_ID)
        assert error_info.value.error_code == 'api_error'
        assert error_info.value.spreadsheet_metadata is not None
        assert error_info.value.worksheet_id is None
        
        # Verify the mocks were called correctly
        mock_client.open_by_key.assert_called_once_with(PUBLIC_SHEET_ID)
        mock_sheet.worksheets.assert_called_once()


class TestValidateGoogleSheet:
    """Tests for the validate_google_sheet function."""

    @patch('hca_validation.entry_sheet_validator.validate_sheet.read_sheet_with_service_account')
    def test_service_account_access(self, mock_read_service_account):
        """Test validation with service account access."""
        _test_validation_with_mock_sheets_response(validate_google_sheet, mock_read_service_account)

    @patch('hca_validation.entry_sheet_validator.validate_sheet.read_sheet_with_service_account')
    def test_service_account_access_with_bionetwork(self, mock_read_service_account):
        """Test validation using network-specific model."""
        result = _test_validation_with_mock_sheets_response(validate_google_sheet, mock_read_service_account, bionetwork="gut")
        # We expect there to be an error referencing `doublet_detection`, a field required by the Gut Network model but not by the default model
        assert any(error.column == "doublet_detection" for error in result.errors)

    @patch('hca_validation.validator.validate')
    @patch('hca_validation.entry_sheet_validator.validate_sheet.read_sheet_with_service_account')
    def test_row_normalization_before_validation(self, mock_read_service_account, mock_validate):
        """Test normalization of rows passed to the validation function."""
        # Store dicts that the validation function is called with
        validated_dicts = []
        def save_data(data, class_name):
            validated_dicts.append(data)
            return DEFAULT
        mock_validate.side_effect = save_data
        # Validate the mock sheet
        _test_validation_with_mock_sheets_response(validate_google_sheet, mock_read_service_account, sheet_data=SAMPLE_SHEET_DATA_WITH_CASTS)
        # Confirm that values were converted as expected
        assert validated_dicts == SAMPLE_SHEET_DATA_WITH_CASTS_EXPECTED_NORMALIZATION

    @patch('hca_validation.validator.validate')
    @patch('hca_validation.entry_sheet_validator.validate_sheet.read_sheet_with_service_account')
    def test_int_normalization_before_validation(self, mock_read_service_account, mock_validate):
        """Test normalization of integer fields passed to the validation function."""
        # Store dicts that the validation function is called with
        validated_dicts = []
        def save_data(data, class_name):
            if class_name.endswith("Sample"): validated_dicts.append(data)
            return DEFAULT
        mock_validate.side_effect = save_data
        # Validate the mock sheet
        _test_validation_with_mock_sheets_response(validate_google_sheet, mock_read_service_account, samples_sheet_data=SAMPLE_SHEET_DATA_WITH_INTEGERS)
        # Confirm that values were converted as expected
        assert validated_dicts == SAMPLE_SHEET_DATA_WITH_INTEGERS_EXPECTED_NORMALIZATION

    @patch('hca_validation.validator.validate')
    @patch('hca_validation.entry_sheet_validator.validate_sheet.read_sheet_with_service_account')
    def test_valid_and_missing_int_normalization_before_validation(self, mock_read_service_account, mock_validate):
        """Test normalization of integer fields passed to the validation function, with only valid and missing integers."""
        # Store dicts that the validation function is called with
        validated_dicts = []
        def save_data(data, class_name):
            if class_name.endswith("Sample"): validated_dicts.append(data)
            return DEFAULT
        mock_validate.side_effect = save_data
        # Validate the mock sheet
        _test_validation_with_mock_sheets_response(validate_google_sheet, mock_read_service_account, samples_sheet_data=SAMPLE_SHEET_DATA_WITH_VALID_AND_MISSING_INTEGERS)
        # Confirm that values were converted as expected
        assert validated_dicts == SAMPLE_SHEET_DATA_WITH_VALID_AND_MISSING_INTEGERS_EXPECTED_NORMALIZATION

    @patch('hca_validation.validator.validate')
    @patch('hca_validation.entry_sheet_validator.validate_sheet.read_sheet_with_service_account')
    def test_class_name(self, mock_read_service_account, mock_validate):
        """Test that the correct class name is passed to the validation function."""
        # Store class name that the validation function was last called with
        last_class_name_info = {}
        def save_class_name(data, class_name):
            last_class_name_info["value"] = class_name
            return DEFAULT
        mock_validate.side_effect = save_class_name
        # Validate the mock sheet with default dataset model
        _test_validation_with_mock_sheets_response(validate_google_sheet, mock_read_service_account)
        # Confirm that correct class was used
        assert last_class_name_info["value"] == "Dataset"
        mock_read_service_account.reset_mock()
        # Validate the mock sheet with Gut Network dataset model
        _test_validation_with_mock_sheets_response(validate_google_sheet, mock_read_service_account, bionetwork="gut")
        # Confirm that correct class was used
        assert last_class_name_info["value"] == "GutDataset"

    @patch('hca_validation.entry_sheet_validator.validate_sheet.read_sheet_with_service_account')
    def test_duplicate_ids(self, mock_read_service_account):
        """Test validation of duplicate IDs."""
        result = _test_validation_with_mock_sheets_response(validate_google_sheet, mock_read_service_account, sheet_data=SAMPLE_SHEET_DATA_WITH_DUPLICATE_IDS)
        # Based on the mock data, expect five duplicate ID errors, for IDs "foo" and "baz" but not "bar" (which is not duplicated) or None (which is not an ID)
        duplicate_id_errors = [error for error in result.errors if error.message.startswith("Duplicate identifier ")]
        assert len(duplicate_id_errors) == 5
        assert all(("foo" in error.message or "baz" in error.message) and not ("bar" in error.message or "None" in error.message) for error in duplicate_id_errors)

    @patch('hca_validation.entry_sheet_validator.validate_sheet.read_sheet_with_service_account')
    def test_available_fixes(self, mock_read_service_account):
        """Test that validate_google_sheet does not provide fixes on its own."""
        result = _test_validation_with_mock_sheets_response(validate_google_sheet, mock_read_service_account, donors_sheet_data=SAMPLE_SHEET_DATA_WITH_FIXES)
        assert all(error.input_fix is None for error in result.errors)

    @patch('hca_validation.entry_sheet_validator.validate_sheet.read_sheet_with_service_account')
    def test_pre_initialized_apis(self, mock_read_service_account):
        """Test that pre-initialized APIs get passed to read_sheet_with_service_account."""
        mock_apis = MagicMock()
        _test_validation_with_mock_sheets_response(
            validate_google_sheet,
            mock_read_service_account,
            additional_arguments={"apis": mock_apis},
            expected_apis_parameter=mock_apis
        )

    @patch('hca_validation.entry_sheet_validator.validate_sheet.read_sheet_with_service_account')
    def test_pre_loaded_sheet_data(self, mock_read_service_account):
        """Test validation of pre-loaded sheet data."""
        mock_sheet_info = _create_mock_spreadsheet_info()
        _test_validation_with_mock_sheets_response(
            validate_google_sheet,
            mock_read_service_account,
            additional_arguments={"sheet_read_result": mock_sheet_info},
            expect_read_call=False
        )

    @patch('hca_validation.entry_sheet_validator.validate_sheet.read_sheet_with_service_account')
    def test_service_account_access_failure(self, mock_read_service_account):
        """Test validation when service account access fails."""
        # Mock service account read failure
        mock_read_service_account.side_effect = SheetReadError(error_code='auth_missing')

        # Run validation
        validation_result = validate_google_sheet(PUBLIC_SHEET_ID)

        # Verify service account method was used
        mock_read_service_account.assert_called_once_with(PUBLIC_SHEET_ID, ["dataset", "donor", "sample"], None)
        
        # Verify that an error was reported
        assert len(validation_result.errors) > 0
        assert any("access" in error.message.lower() for error in validation_result.errors)
        
        # Verify result, metadata, error code, and summary
        assert validation_result.successful is False
        assert validation_result.spreadsheet_metadata is None
        assert validation_result.error_code == 'auth_missing'
        assert validation_result.summary  == {"dataset_count": None, "donor_count": None, "sample_count": None, "error_count": 1}

    def test_invalid_bionetwork(self):
        """Test validation when `bionetwork` parameter has an invalid value."""

        # Run validation
        with pytest.raises(ValueError, match="'not-a-bionetwork' is not a valid bionetwork"):
            validate_google_sheet(PUBLIC_SHEET_ID, bionetwork="not-a-bionetwork")


class TestProcessGoogleSheet:
    """Tests for the process_google_sheet function."""

    @patch('hca_validation.entry_sheet_validator.process_sheet.init_apis')
    @patch('hca_validation.entry_sheet_validator.process_sheet.read_sheet_with_service_account')
    def test_available_fixes(self, mock_read_service_account, mock_init_apis):
        """Test that available fixes are present in error info for non-editable spreadsheet."""
        mock_apis = MagicMock()
        mock_init_apis.return_value = mock_apis
        result = _test_validation_with_mock_sheets_response(
            process_google_sheet,
            mock_read_service_account,
            donors_sheet_data=SAMPLE_SHEET_DATA_WITH_FIXES,
            expected_apis_parameter=mock_apis
        )
        # Based on the mock data, expect three errors in the manner_of_death column, with appropriate input values and fixed values (or lack thereof)
        mod_errors = [error for error in result.errors if error.column == "manner_of_death"]
        assert len(mod_errors) == 3
        assert mod_errors[0].input == "not_applicable"
        assert mod_errors[0].input_fix == "not applicable"
        assert mod_errors[1].input == "not a manner of death"
        assert mod_errors[1].input_fix is None
        assert mod_errors[2].input == "not_applicable"
        assert mod_errors[2].input_fix == "not applicable"

    @patch('hca_validation.entry_sheet_validator.process_sheet.init_apis')
    @patch('hca_validation.entry_sheet_validator.validate_sheet.read_sheet_with_service_account')
    @patch('hca_validation.entry_sheet_validator.process_sheet.read_sheet_with_service_account')
    def test_application_of_fixes(self, mock_read_service_account_a, mock_read_service_account_b, mock_init_apis):
        """Test validation and updating of editable spreadsheet with fixes available."""
        mock_apis = MagicMock()
        mock_init_apis.return_value = mock_apis
        mock_datasets_worksheet = MagicMock()
        mock_donors_worksheet = MagicMock()
        mock_read_result = (
            _create_mock_spreadsheet_info(donors_sheet_data=SAMPLE_SHEET_DATA_WITH_FIXES, sheet_editable=True),
            [mock_datasets_worksheet, mock_donors_worksheet]
        )
        mock_read_service_account_a.return_value = mock_read_result
        mock_read_service_account_b.return_value = mock_read_result
        process_google_sheet(PUBLIC_SHEET_ID)
        # Verify that batch_update was called only for the donors worksheet, and with the values expected for the mock data
        mock_datasets_worksheet.batch_update.assert_not_called()
        mock_donors_worksheet.batch_update.assert_called_once_with(SAMPLE_SHEET_DATA_WITH_FIXES_EXPECTED_VALUE_RANGES)
        # Verify that spreadsheet was read twice
        mock_read_service_account_a.assert_called_once_with(PUBLIC_SHEET_ID, ["dataset", "donor", "sample"], mock_apis)
        mock_read_service_account_b.assert_called_once_with(PUBLIC_SHEET_ID, ["dataset", "donor", "sample"], mock_apis)

    @patch('hca_validation.entry_sheet_validator.process_sheet.init_apis')
    @patch('hca_validation.entry_sheet_validator.validate_sheet.read_sheet_with_service_account')
    @patch('hca_validation.entry_sheet_validator.process_sheet.read_sheet_with_service_account')
    def test_sheet_without_fixes(self, mock_read_service_account_a, mock_read_service_account_b, mock_init_apis):
        """Test processing of editable spreadsheet without fixes."""
        mock_apis = MagicMock()
        mock_init_apis.return_value = mock_apis
        mock_datasets_worksheet = MagicMock()
        mock_read_result = (
            _create_mock_spreadsheet_info(sheet_editable=True),
            [mock_datasets_worksheet]
        )
        mock_read_service_account_a.return_value = mock_read_result
        mock_read_service_account_b.return_value = mock_read_result
        process_google_sheet(PUBLIC_SHEET_ID)
        # Verify that batch_update wasn't called
        mock_datasets_worksheet.batch_update.assert_not_called()
        # Verify that spreadsheet was only read once
        mock_read_service_account_a.assert_called_once_with(PUBLIC_SHEET_ID, ["dataset", "donor", "sample"], mock_apis)
        mock_read_service_account_b.assert_not_called()
    
    @patch('hca_validation.entry_sheet_validator.process_sheet.init_apis')
    @patch('hca_validation.entry_sheet_validator.process_sheet.read_sheet_with_service_account')
    def test_early_read_error(self, mock_read_service_account, mock_init_apis):
        """Test that a validation result object is properly returned when the initial read call raises a SheetReadError."""
        
        # Mock APIs
        mock_apis = MagicMock()
        mock_init_apis.return_value = mock_apis

        # Mock read failure
        mock_read_service_account.side_effect = SheetReadError(error_code='sheet_not_found')

        # Run processing pipeline
        validation_result = process_google_sheet(PUBLIC_SHEET_ID)

        # Verify read function was called
        mock_read_service_account.assert_called_once_with(PUBLIC_SHEET_ID, ["dataset", "donor", "sample"], mock_apis)
        
        # Verify that an error was reported
        assert len(validation_result.errors) > 0
        assert any("access" in error.message.lower() for error in validation_result.errors)
        
        # Verify result, metadata, error code, and summary
        assert validation_result.successful is False
        assert validation_result.spreadsheet_metadata is None
        assert validation_result.error_code == 'sheet_not_found'
        assert validation_result.summary  == {"dataset_count": None, "donor_count": None, "sample_count": None, "error_count": 1}

    @patch('hca_validation.entry_sheet_validator.process_sheet.init_apis')
    @patch('hca_validation.entry_sheet_validator.validate_sheet.read_sheet_with_service_account')
    @patch('hca_validation.entry_sheet_validator.process_sheet.read_sheet_with_service_account')
    def test_google_error_while_applying_fixes(self, mock_read_service_account_a, mock_read_service_account_b, mock_init_apis):
        """Test that a validation result object is properly returned when an API error occurs while applying fixes."""

        mock_apis = MagicMock()
        mock_init_apis.return_value = mock_apis
        mock_datasets_worksheet = MagicMock()
        mock_donors_worksheet = MagicMock()
        mock_update_response = MagicMock()
        mock_read_service_account_a.return_value = (
            _create_mock_spreadsheet_info(donors_sheet_data=SAMPLE_SHEET_DATA_WITH_FIXES, sheet_editable=True),
            [mock_datasets_worksheet, mock_donors_worksheet]
        )
        mock_update_response.json.return_value = {
            "error": {
                "code": 500,
                "message": "Test error",
                "status": "internal_server_error"
            }
        }
        mock_donors_worksheet.batch_update.side_effect = gspread.exceptions.APIError(mock_update_response)

        validation_result = process_google_sheet(PUBLIC_SHEET_ID)

        # Verify that spreadsheet only ended up being read once
        mock_read_service_account_a.assert_called_once_with(PUBLIC_SHEET_ID, ["dataset", "donor", "sample"], mock_apis)
        mock_read_service_account_b.assert_not_called()

        # Verify that an error was reported
        assert len(validation_result.errors) > 0
        assert any("Test error" in error.message for error in validation_result.errors)

        # Verify result, metadata, error code, and summary
        assert validation_result.successful is False
        assert validation_result.spreadsheet_metadata is not None
        assert validation_result.spreadsheet_metadata.spreadsheet_title == "Test Sheet Title"
        assert validation_result.error_code == 'api_error'
        assert validation_result.summary  == {"dataset_count": None, "donor_count": None, "sample_count": None, "error_count": 1}


# Integration tests that use actual Google Sheets
# These tests are marked as integration so they can be skipped with pytest -m "not integration"
@pytest.mark.integration
class TestIntegration:
    """Integration tests using actual Google Sheets."""

    def test_read_actual_sheet_with_service_account(self):
        """Test reading an actual sheet with service account credentials."""
        # Load credentials from .env file if not already in environment
        if not os.environ.get('GOOGLE_SERVICE_ACCOUNT'):
            from dotenv import load_dotenv
            from pathlib import Path
            
            dotenv_path = Path(os.path.dirname(os.path.dirname(__file__))) / '.env'
            if dotenv_path.exists():
                load_dotenv(dotenv_path=dotenv_path)
        
        # Skip test if credentials are still not available
        if not os.environ.get('GOOGLE_SERVICE_ACCOUNT'):
            pytest.skip("No service account credentials available for integration test")
            
        sheet_read_result = read_sheet_with_service_account(PUBLIC_SHEET_ID)[0]
        assert isinstance(sheet_read_result, SpreadsheetInfo)
        assert isinstance(sheet_read_result.spreadsheet_metadata.spreadsheet_title, str)
        assert isinstance(sheet_read_result.spreadsheet_metadata.last_updated_date, str)
        assert isinstance(sheet_read_result.spreadsheet_metadata.last_updated_by, str)
        sheet_info = sheet_read_result.worksheets[0]
        assert sheet_info.data is not None
        assert isinstance(sheet_info.data, pd.DataFrame)
        assert not sheet_info.data.empty
        assert isinstance(sheet_info.worksheet_id, int)
        assert isinstance(sheet_info.source_columns, list)
        assert len(sheet_info.source_columns) > 0
        assert sheet_info.source_rows_start_index == 1

    def test_validate_actual_sheet_with_service_account(self):
        """Test validating an actual sheet with service account credentials."""
        # Load credentials from .env file if not already in environment
        if not os.environ.get('GOOGLE_SERVICE_ACCOUNT'):
            from dotenv import load_dotenv
            from pathlib import Path
            
            dotenv_path = Path(os.path.dirname(os.path.dirname(__file__))) / '.env'
            if dotenv_path.exists():
                load_dotenv(dotenv_path=dotenv_path)
        
        # Skip test if credentials are still not available
        if not os.environ.get('GOOGLE_SERVICE_ACCOUNT'):
            pytest.skip("No service account credentials available for integration test")
        
        # Run validation
        validation_result = validate_google_sheet(PUBLIC_SHEET_ID)
        
        # Verify that the metadata was returned
        assert validation_result.spreadsheet_metadata is not None
        assert isinstance(validation_result.spreadsheet_metadata.spreadsheet_title, str)
        assert isinstance(validation_result.spreadsheet_metadata.last_updated_date, str)
        assert isinstance(validation_result.spreadsheet_metadata.last_updated_by, str)
        
        # We don't assert on the number of errors since the sheet content may change
        # Just verify that the function ran without exceptions
        
        # For public sheets, we should get the default title
        spreadsheet_title = validation_result.spreadsheet_metadata.spreadsheet_title
        assert spreadsheet_title == "Title unavailable (public access)" or isinstance(spreadsheet_title, str)
        
        # The actual function returns 'validation_error' if validation errors are found
        # or 'no_data' if no data is found to validate
        assert validation_result.error_code in ['validation_error', 'no_data']

        # Verify that a summary with the expected information was returned
        assert isinstance(validation_result.summary, dict)
        assert 'dataset_count' in validation_result.summary
        assert isinstance(validation_result.summary['dataset_count'], int)
        assert 'donor_count' in validation_result.summary
        assert isinstance(validation_result.summary['donor_count'], int)
        assert 'sample_count' in validation_result.summary
        assert isinstance(validation_result.summary['sample_count'], int)
        assert 'error_count' in validation_result.summary
        assert isinstance(validation_result.summary['error_count'], int)

    def test_read_private_sheet_with_credentials(self):
        """Test reading a private sheet with service account credentials."""
        # Try to load credentials from .env file if not in environment
        if not os.environ.get('GOOGLE_SERVICE_ACCOUNT'):
            # Check if .env file exists
            env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
            if os.path.exists(env_file):
                try:
                    # Load .env file
                    from dotenv import load_dotenv
                    load_dotenv(env_file)
                    print(f"Loaded credentials from {env_file}")
                except ImportError:
                    print("python-dotenv not installed, skipping .env loading")
        
        # Skip this test if no credentials are available after trying to load from .env
        if not os.environ.get('GOOGLE_SERVICE_ACCOUNT'):
            pytest.skip("Service account credentials not available")
            
        # This test only runs if GOOGLE_SERVICE_ACCOUNT is set
        sheet_read_result = read_sheet_with_service_account(PRIVATE_SHEET_ID)[0]
        assert isinstance(sheet_read_result, SpreadsheetInfo)
        assert sheet_read_result.spreadsheet_metadata is not None
        assert isinstance(sheet_read_result.spreadsheet_metadata.spreadsheet_title, str)
        assert len(sheet_read_result.spreadsheet_metadata.spreadsheet_title) > 0
        assert isinstance(sheet_read_result.spreadsheet_metadata.last_updated_date, str)
        assert isinstance(sheet_read_result.spreadsheet_metadata.last_updated_by, str)
        sheet_info = sheet_read_result.worksheets[0]
        assert sheet_info.data is not None
        assert isinstance(sheet_info.data, pd.DataFrame)
        assert not sheet_info.data.empty
        assert isinstance(sheet_info.worksheet_id, int)
        assert isinstance(sheet_info.source_columns, list)
        assert len(sheet_info.source_columns) > 0
        assert sheet_info.source_rows_start_index == 1


if __name__ == "__main__":
    pytest.main(["-v"])
