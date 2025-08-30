#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
AWS Lambda function for validating Google Sheets using the HCA entry sheet validator.

This Lambda function accepts a Google Sheet ID, validates the sheet using the
HCA validation tools, and returns the validation results as JSON.
"""

# Standard library imports
import json
import traceback
import os
import psutil
import logging
from http import HTTPStatus
from dataclasses import asdict
from typing import Dict, Any, List, Optional, Union, Tuple

# Third-party / local imports
from hca_validation.entry_sheet_validator.validate_sheet import (
    SheetErrorInfo,
    SheetValidationResult,
    make_summary_without_entities,
)
from hca_validation.entry_sheet_validator.process_sheet import process_google_sheet

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.ERROR)

# ---------------------------------------------------------------------------
# Error-code → HTTP status mapping
# ---------------------------------------------------------------------------
# Known validation error codes mapped to appropriate HTTP status responses.
# This avoids repetitive if/elif chains and simplifies future maintenance.
ERROR_TO_STATUS: dict[str, HTTPStatus] = {
    # Authentication / authorization errors
    "auth_missing": HTTPStatus.UNAUTHORIZED,
    "auth_unresolved": HTTPStatus.UNAUTHORIZED,
    "auth_invalid_format": HTTPStatus.UNAUTHORIZED,
    "auth_error": HTTPStatus.UNAUTHORIZED,

    # Permission issues
    "permission_denied": HTTPStatus.FORBIDDEN,

    # Resource not found
    "sheet_not_found": HTTPStatus.NOT_FOUND,
    "worksheet_not_found": HTTPStatus.NOT_FOUND,

    # Service unavailable
    "max_api_retries": HTTPStatus.SERVICE_UNAVAILABLE,
}


def extract_validation_errors(sheet_id: str, bionetwork: Optional[str] = None) -> Tuple[SheetValidationResult, int]:
    """
    Extract validation errors from a Google Sheet.
    
    Args:
        sheet_id: The ID of the Google Sheet
        bionetwork: Optional biological network identifier (currently unused by the validator)
        
    Returns:
        Tuple containing (SheetValidationResult, list of validation error objects, http_status_code)
        where http_status_code is the appropriate HTTP status code (200, 400, 401, 404, etc.)
    """
    
    # Run the validation with our custom handler
    try:
        # Call the process_google_sheet function to perform validation and check for fixes
        validation_result = process_google_sheet(
            sheet_id,
            bionetwork=bionetwork,
        )
        error_code = validation_result.error_code
        
        # Resolve HTTP status code using the mapping. Default logic:
        #   • No error_code   → 200 OK
        #   • Known error     → mapped status
        #   • Unknown error   → 400 Bad Request
        if error_code is None:
            http_status_code = HTTPStatus.OK.value
        else:
            http_status_code = ERROR_TO_STATUS.get(error_code, HTTPStatus.BAD_REQUEST).value
    except ValueError as ve:
        # Guard violations (e.g., missing required params) → 400 Bad Request
        error_msg = str(ve)
        error_info = SheetErrorInfo(entity_type=None, worksheet_id=None, message=error_msg)
        return (
            SheetValidationResult(
                successful=False,
                spreadsheet_metadata=None,
                error_code="bad_request",
                summary=make_summary_without_entities(1),
                errors=[error_info]
            ),
            HTTPStatus.BAD_REQUEST.value,
        )
    
    except Exception as e:
        # If there's an error in the validation process itself
        error_msg = f"Error in validation process: {str(e)}"
        error_info = SheetErrorInfo(entity_type=None, worksheet_id=None, message=error_msg)
        return (
            SheetValidationResult(
                successful=False,
                spreadsheet_metadata=None,
                error_code="internal_error",
                summary=make_summary_without_entities(1),
                errors=[error_info]
            ),
            500
        )
    
    return validation_result, http_status_code


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
                bionetwork = body.get('bionetwork')
            except Exception as e:
                logger.warning(f"Error parsing request body: {str(e)}")
                return {
                    'statusCode': HTTPStatus.BAD_REQUEST.value,
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
            bionetwork = event.get('bionetwork')
        
        if not sheet_id:
            return {
                'statusCode': HTTPStatus.BAD_REQUEST.value,
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
        validation_result, http_status_code = extract_validation_errors(sheet_id, bionetwork)
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
            'can_edit': None if spreadsheet_metadata is None else spreadsheet_metadata.can_edit,
            'errors': [asdict(e) for e in validation_result.errors],
            'valid': len(validation_result.errors) == 0,
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
