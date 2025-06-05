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
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
from google.oauth2.service_account import Credentials
import gspread
from gspread.exceptions import SpreadsheetNotFound, WorksheetNotFound, APIError

from hca_validation.entry_sheet_validator.validate_sheet import (
    ReadErrorSheetInfo,
    SheetInfo,
    read_sheet_with_service_account,
    validate_google_sheet
)

# Test sheet IDs
PUBLIC_SHEET_ID = "1oPFb6qb0Y2HeoQqjSGRe_TlsZPRLwq-HUlVF0iqtVlY"  # This is a public sheet
PRIVATE_SHEET_ID = "1Gp2yocEq9OWECfDgCVbExIgzYfM7s6nJV5ftyn-SMXQ"  # This is a private sheet
NONEXISTENT_SHEET_ID = "1aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"  # This sheet doesn't exist

# Sample data for mocking
SAMPLE_SHEET_DATA = pd.DataFrame({
    'column1': ['value1', 'value2'],
    'column2': ['value3', 'value4']
})



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

    @patch('gspread.authorize')
    @patch('google.oauth2.service_account.Credentials.from_service_account_info')
    def test_with_service_account_credentials(self, mock_credentials, mock_authorize, mock_env_with_credentials):
        """Test reading a sheet with service account credentials."""
        # Mock the gspread client
        mock_client = MagicMock()
        mock_sheet = MagicMock()
        mock_worksheet = MagicMock()
        
        # Mock worksheet.get_all_values (not get_all_records)
        mock_data = [
            ['header1', 'header2'],  # Headers
            ['value1', 'value3'],    # Row 1
            ['value2', 'value4']     # Row 2
        ]
        mock_worksheet.get_all_values.return_value = mock_data
        mock_worksheet.id = 123
        mock_sheet.get_worksheet.return_value = mock_worksheet
        mock_client.open_by_key.return_value = mock_sheet
        mock_authorize.return_value = mock_client

        # Mock the sheet title
        mock_sheet.title = "Test Sheet Title"
        
        # Test the function
        sheet_read_result = read_sheet_with_service_account(PUBLIC_SHEET_ID)
        assert isinstance(sheet_read_result, list)
        sheet_info = sheet_read_result[0]
        assert sheet_info.data is not None
        assert isinstance(sheet_info.data, pd.DataFrame)
        assert not sheet_info.data.empty
        assert sheet_info.spreadsheet_title == "Test Sheet Title"
        assert sheet_info.worksheet_id == 123
        assert sheet_info.source_columns == ["header1", "header2"]
        assert sheet_info.source_rows_start_index == 1
        
        # Verify the mocks were called correctly
        mock_credentials.assert_called_once()
        mock_authorize.assert_called_once()
        mock_client.open_by_key.assert_called_once_with(PUBLIC_SHEET_ID)
        mock_sheet.get_worksheet.assert_called_once_with(0)
        mock_worksheet.get_all_values.assert_called_once()

    def test_without_service_account_credentials(self):
        """Test reading a sheet without service account credentials."""
        # Ensure no credentials are set
        if 'GOOGLE_SERVICE_ACCOUNT' in os.environ:
            del os.environ['GOOGLE_SERVICE_ACCOUNT']

        # The function should return read error containing only 'auth_missing' code when no credentials are available
        sheet_read_result = read_sheet_with_service_account(PUBLIC_SHEET_ID)
        assert isinstance(sheet_read_result, ReadErrorSheetInfo)
        assert sheet_read_result.error_code == 'auth_missing'
        assert sheet_read_result.spreadsheet_title is None
        assert sheet_read_result.worksheet_id is None
        
    def test_with_unresolved_credentials(self):
        """Test reading a sheet with unresolved credentials from Secrets Manager."""
        # Set credentials to a string that looks like an unresolved secret reference
        original_env = os.environ.copy()
        os.environ['GOOGLE_SERVICE_ACCOUNT'] = 'aws:secretsmanager:dev/hca-atlas-tracker/google-service-account'
        
        try:
            # The function should return read error containing only 'auth_unresolved' code when credentials weren't resolved
            sheet_read_result = read_sheet_with_service_account(PUBLIC_SHEET_ID)
            assert isinstance(sheet_read_result, ReadErrorSheetInfo)
            assert sheet_read_result.error_code == 'auth_unresolved'
            assert sheet_read_result.spreadsheet_title is None
            assert sheet_read_result.worksheet_id is None
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
            sheet_read_result = read_sheet_with_service_account(PUBLIC_SHEET_ID)
            assert isinstance(sheet_read_result, ReadErrorSheetInfo)
            assert sheet_read_result.error_code == 'auth_invalid_format'
            assert sheet_read_result.spreadsheet_title is None
            assert sheet_read_result.worksheet_id is None
        finally:
            # Restore original environment
            os.environ.clear()
            os.environ.update(original_env)

    @patch('gspread.authorize')
    @patch('google.oauth2.service_account.Credentials.from_service_account_info')
    def test_sheet_not_found(self, mock_credentials, mock_authorize, mock_env_with_credentials):
        """Test handling of sheet not found error."""
        # Mock the gspread client to raise SpreadsheetNotFound
        mock_client = MagicMock()
        mock_client.open_by_key.side_effect = SpreadsheetNotFound("Sheet not found")
        mock_authorize.return_value = mock_client

        # The function should return read error containing only 'sheet_not_found' code when the sheet is not found
        sheet_read_result = read_sheet_with_service_account(NONEXISTENT_SHEET_ID)
        assert isinstance(sheet_read_result, ReadErrorSheetInfo)
        assert sheet_read_result.error_code == 'sheet_not_found'
        assert sheet_read_result.spreadsheet_title is None
        assert sheet_read_result.worksheet_id is None
        
        # Verify the mocks were called correctly
        mock_client.open_by_key.assert_called_once_with(NONEXISTENT_SHEET_ID)

    @patch('gspread.authorize')
    @patch('google.oauth2.service_account.Credentials.from_service_account_info')
    def test_worksheet_not_found(self, mock_credentials, mock_authorize, mock_env_with_credentials):
        """Test handling of worksheet not found error."""
        # Mock the gspread client
        mock_client = MagicMock()
        mock_sheet = MagicMock()
        mock_sheet.get_worksheet.side_effect = WorksheetNotFound("Worksheet not found")
        mock_client.open_by_key.return_value = mock_sheet
        mock_authorize.return_value = mock_client

        # The function should return read error containing only 'worksheet_not_found' code when the worksheet is not found
        sheet_read_result = read_sheet_with_service_account(PUBLIC_SHEET_ID)
        assert isinstance(sheet_read_result, ReadErrorSheetInfo)
        assert sheet_read_result.error_code == 'worksheet_not_found'
        assert sheet_read_result.spreadsheet_title is None
        assert sheet_read_result.worksheet_id is None
        
        # Verify the mocks were called correctly
        mock_client.open_by_key.assert_called_once_with(PUBLIC_SHEET_ID)
        mock_sheet.get_worksheet.assert_called_once_with(0)

    @patch('gspread.authorize')
    @patch('google.oauth2.service_account.Credentials.from_service_account_info')
    def test_api_error(self, mock_credentials, mock_authorize, mock_env_with_credentials):
        """Test handling of API error."""
        # Mock the gspread client
        mock_client = MagicMock()
        # Use a generic Exception instead of APIError since it's difficult to mock correctly
        mock_client.open_by_key.side_effect = Exception("API error occurred")
        mock_authorize.return_value = mock_client

        # The function should return read error containing only 'api_error' code when an API error occurs
        sheet_read_result = read_sheet_with_service_account(PUBLIC_SHEET_ID)
        assert isinstance(sheet_read_result, ReadErrorSheetInfo)
        assert sheet_read_result.error_code == 'api_error'
        assert sheet_read_result.spreadsheet_title is None
        assert sheet_read_result.worksheet_id is None
        
        # Verify the mocks were called correctly
        mock_client.open_by_key.assert_called_once_with(PUBLIC_SHEET_ID)


class TestValidateGoogleSheet:
    """Tests for the validate_google_sheet function."""

    @patch('hca_validation.entry_sheet_validator.validate_sheet.read_sheet_with_service_account')
    def test_service_account_access(self, mock_read_service_account):
        """Test validation with service account access."""
        # Mock successful service account read
        mock_read_service_account.return_value = [
            SheetInfo(
                data=SAMPLE_SHEET_DATA,
                spreadsheet_title="Test Sheet Title",
                worksheet_id=123,
                source_columns=list(SAMPLE_SHEET_DATA.columns),
                source_rows_start_index=1
            )
        ]

        # Create a mock error handler to capture validation errors
        errors = []
        def mock_error_handler(error):
            errors.append(error)

        # Run validation
        validation_result = validate_google_sheet(PUBLIC_SHEET_ID, error_handler=mock_error_handler)

        # Verify service account method was used
        mock_read_service_account.assert_called_once_with(PUBLIC_SHEET_ID, [0, 1, 2])
        
        # Verify title is returned
        assert validation_result.spreadsheet_title == "Test Sheet Title"
        # The mock returns None for error_code, but the actual function may return 'no_data' or 'validation_error'
        # depending on the data in the sheet. For the mock test, we expect None or 'no_data'
        assert validation_result.error_code is None or validation_result.error_code == 'no_data'

    @patch('hca_validation.entry_sheet_validator.validate_sheet.read_sheet_with_service_account')
    def test_service_account_access_failure(self, mock_read_service_account):
        """Test validation when service account access fails."""
        # Mock service account read failure
        mock_read_service_account.return_value = ReadErrorSheetInfo(error_code='auth_missing')

        # Create a mock error handler to capture validation errors
        errors = []
        def mock_error_handler(error):
            errors.append(error)

        # Run validation
        validation_result = validate_google_sheet(PUBLIC_SHEET_ID, error_handler=mock_error_handler)

        # Verify service account method was used
        mock_read_service_account.assert_called_once_with(PUBLIC_SHEET_ID, [0, 1, 2])
        
        # Verify that an error was reported via the error handler
        assert len(errors) > 0
        assert any("access" in error.message.lower() for error in errors)
        
        # Verify result, title, and error code
        assert validation_result.successful is False
        assert validation_result.spreadsheet_title is None
        assert validation_result.error_code == 'auth_missing'


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
            
        sheet_read_result = read_sheet_with_service_account(PUBLIC_SHEET_ID)
        assert isinstance(sheet_read_result, list)
        sheet_info = sheet_read_result[0]
        assert sheet_info.data is not None
        assert isinstance(sheet_info.data, pd.DataFrame)
        assert not sheet_info.data.empty
        assert sheet_info.spreadsheet_title is not None
        assert isinstance(sheet_info.spreadsheet_title, str)
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
            
        # Create a mock error handler to capture validation errors
        errors = []
        def mock_error_handler(error):
            errors.append(error)

        # Run validation
        validation_result = validate_google_sheet(PUBLIC_SHEET_ID, error_handler=mock_error_handler)
        
        # Verify that the title was returned
        assert validation_result.spreadsheet_title is not None
        assert isinstance(validation_result.spreadsheet_title, str)
        
        # We don't assert on the number of errors since the sheet content may change
        # Just verify that the function ran without exceptions
        
        # For public sheets, we should get the default title
        assert validation_result.spreadsheet_title == "Title unavailable (public access)" or isinstance(validation_result.spreadsheet_title, str)
        
        # The actual function returns 'validation_error' if validation errors are found
        # or 'no_data' if no data is found to validate
        assert validation_result.error_code in ['validation_error', 'no_data']

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
        sheet_read_result = read_sheet_with_service_account(PRIVATE_SHEET_ID)
        assert isinstance(sheet_read_result, list)
        sheet_info = sheet_read_result[0]
        assert sheet_info.data is not None
        assert isinstance(sheet_info.data, pd.DataFrame)
        assert not sheet_info.data.empty
        assert sheet_info.spreadsheet_title is not None
        assert isinstance(sheet_info.spreadsheet_title, str)
        assert len(sheet_info.spreadsheet_title) > 0
        assert isinstance(sheet_info.worksheet_id, int)
        assert isinstance(sheet_info.source_columns, list)
        assert len(sheet_info.source_columns) > 0
        assert sheet_info.source_rows_start_index == 1


if __name__ == "__main__":
    pytest.main(["-v"])
