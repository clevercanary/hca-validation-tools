#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
AWS Lambda function for validating Google Sheets using the HCA entry sheet validator.

This Lambda function accepts a Google Sheet ID, validates the sheet using the
HCA validation tools, and returns the validation results as JSON.
"""

import json
import traceback
import os
import psutil
import logging
from dataclasses import asdict
from typing import Dict, Any, List, Optional, Union, Tuple

# Import the entry sheet validator
from hca_validation.entry_sheet_validator.validate_sheet import SheetErrorInfo, SheetValidationResult, validate_google_sheet

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def extract_validation_errors(sheet_id: str) -> Tuple[SheetValidationResult, List[SheetErrorInfo], int]:
    """
    Extract validation errors from a Google Sheet.
    
    Args:
        sheet_id: The ID of the Google Sheet
        
    Returns:
        Tuple containing (SheetValidationResult, list of validation error objects, http_status_code)
        where http_status_code is the appropriate HTTP status code (200, 400, 401, 404, etc.)
    """
    # Create a list to store validation errors
    validation_errors: List[SheetErrorInfo] = []
    
    # Use a custom validation handler to capture errors
    def validation_handler(error_info: SheetErrorInfo):
        validation_errors.append(error_info)
    
    # Run the validation with our custom handler
    try:
        # Suppress print statements during validation by redirecting stdout
        import sys
        from io import StringIO
        original_stdout = sys.stdout
        sys.stdout = StringIO()
        
        # Call the validate_google_sheet function with our error handler
        # The function returns a SheetValidationResult object
        validation_result = validate_google_sheet(sheet_id, error_handler=validation_handler)
        error_code = validation_result.error_code
        
        # Restore stdout
        sys.stdout = original_stdout
        
        # Determine the appropriate HTTP status code based on the error code
        http_status_code = 200  # Default to success
        if error_code:
            if error_code == 'auth_missing' or error_code == 'auth_unresolved' or error_code == 'auth_invalid_format' or error_code == 'auth_error':
                http_status_code = 401  # Unauthorized
            elif error_code == 'sheet_not_found' or error_code == 'worksheet_not_found':
                http_status_code = 404  # Not Found
            elif error_code == 'permission_denied':
                http_status_code = 403  # Forbidden
            else:
                http_status_code = 400  # Bad Request
    except Exception as e:
        # If there's an error in the validation process itself
        error_msg = f"Error in validation process: {str(e)}"
        validation_errors.append(SheetErrorInfo(entity_type=None, worksheet_id=None, message=error_msg))
        return SheetValidationResult(successful=False, spreadsheet_metadata=None, error_code="internal_error", summary=None), validation_errors, 500
    
    return validation_result, validation_errors, http_status_code


def get_memory_usage():
    """Get current memory usage information"""
    # Get process memory info
    process = psutil.Process(os.getpid())
    memory_info = process.memory_info()
    memory_mb = memory_info.rss / (1024 * 1024)  # Convert to MB
    
    # Get Lambda memory limit if available
    memory_limit = int(os.environ.get('AWS_LAMBDA_FUNCTION_MEMORY_SIZE', 0))
    
    return {
        'memory_used_mb': round(memory_mb, 2),
        'memory_limit_mb': memory_limit,
        'memory_utilization_percent': round((memory_mb / memory_limit * 100), 2) if memory_limit else None
    }

def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda handler function for validating HCA entry sheets in Google Sheets format.
    
    Args:
        event: Lambda event object containing the sheet_id parameter
        context: Lambda context object
        
    Returns:
        Dictionary with validation results including any validation errors
    """
    # Log initial memory usage
    initial_memory = get_memory_usage()
    logger.info(f"Initial memory usage: {initial_memory}")
    logger.info(f"Event: {event}")
    
    try:
        # Check if this is an API Gateway request
        if 'body' in event:
            try:
                # Parse the body if it's a string (from API Gateway)
                if isinstance(event['body'], str):
                    body = json.loads(event['body'])
                else:
                    body = event['body']
                    
                sheet_id = body.get('sheet_id')
            except Exception as e:
                logger.error(f"Error parsing request body: {str(e)}")
                return {
                    'statusCode': 400,
                    'body': json.dumps({
                        'error': f"Invalid request body: {str(e)}"
                    }),
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    }
                }
        else:
            # Direct Lambda invocation
            sheet_id = event.get('sheet_id')
        
        if not sheet_id:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': 'Missing required parameter: sheet_id'
                }),
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                }
            }
        
        # Log memory usage before validation
        pre_validation_memory = get_memory_usage()
        logger.info(f"Memory usage before validation: {pre_validation_memory}")
        
        # Extract validation errors using the entry sheet validator
        validation_result, validation_errors, http_status_code = extract_validation_errors(sheet_id)
        spreadsheet_metadata = validation_result.spreadsheet_metadata
        
        # Log memory usage after validation
        post_validation_memory = get_memory_usage()
        logger.info(f"Memory usage after validation: {post_validation_memory}")
        logger.info(f"Validation completed with error_code: {validation_result.error_code}, http_status_code: {http_status_code}")
        
        # Prepare the response data
        response_data = {
            'sheet_id': sheet_id,
            'sheet_title': None if spreadsheet_metadata is None else spreadsheet_metadata.spreadsheet_title,
            'last_updated': None if spreadsheet_metadata is None else {
                "date": spreadsheet_metadata.last_updated_date,
                "by": spreadsheet_metadata.last_updated_by,
                "by_email": spreadsheet_metadata.last_updated_email
            },
            'errors': [asdict(e) for e in validation_errors],
            'valid': len(validation_errors) == 0,
            'error_code': validation_result.error_code,
            'summary': validation_result.summary,
            'memory_usage': {
                'initial': initial_memory,
                'pre_validation': pre_validation_memory,
                'post_validation': post_validation_memory
            }
        }
        
        # Check if this was called via API Gateway (event has 'httpMethod')
        if 'httpMethod' in event or 'requestContext' in event:
            return {
                'statusCode': http_status_code,
                'body': json.dumps(response_data),
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                }
            }
        else:
            # Direct Lambda invocation
            return response_data
    except Exception as e:
        # Log the error
        logger.error(f"Error: {str(e)}")
        logger.error(traceback.format_exc())
        
        # Prepare error response
        error_response = {
            'error': str(e),
            'traceback': traceback.format_exc()
        }
        
        # Check if this was called via API Gateway
        if 'httpMethod' in event or 'requestContext' in event:
            return {
                'statusCode': 500,
                'body': json.dumps(error_response),
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                }
            }
        else:
            # Direct Lambda invocation
            return error_response


# For local testing
if __name__ == "__main__":
    # Test with a sample event
    test_event = {
        'sheet_id': '1oPFb6qb0Y2HeoQqjSGRe_TlsZPRLwq-HUlVF0iqtVlY'
    }
    
    result = handler(test_event, None)
    print(json.dumps(result, indent=2))
