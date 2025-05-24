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
from typing import Dict, Any, List, Optional, Union

# Import the entry sheet validator
from hca_validation.entry_sheet_validator.validate_sheet import read_public_sheet, validate_google_sheet

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def extract_validation_errors(sheet_id: str, sheet_index: int = 0) -> List[Dict[str, Any]]:
    """
    Extract validation errors from a Google Sheet.
    
    Args:
        sheet_id: The ID of the Google Sheet
        sheet_index: The index of the sheet (0-based)
        
    Returns:
        List of validation error objects
    """
    # Create a list to store validation errors
    validation_errors = []
    
    # Use a custom validation handler to capture errors
    def validation_handler(row_index, error):
        validation_errors.append({
            "row": row_index,
            "message": error.message,
            "field": error.field if hasattr(error, 'field') else None,
            "value": error.value if hasattr(error, 'value') else None
        })
    
    # Run the validation with our custom handler
    try:
        # Suppress print statements during validation by redirecting stdout
        import sys
        from io import StringIO
        original_stdout = sys.stdout
        sys.stdout = StringIO()
        
        # Call the existing validate_google_sheet function with our error handler
        validate_google_sheet(sheet_id, sheet_index, error_handler=validation_handler)
        
        # Restore stdout
        sys.stdout = original_stdout
    except Exception as e:
        # If there's an error in the validation process itself
        validation_errors.append({
            "row": 0,
            "message": f"Error in validation process: {str(e)}",
            "field": None,
            "value": None
        })
    
    return validation_errors


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
                sheet_index = body.get('sheet_index', 0)
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
            sheet_index = event.get('sheet_index', 0)
        
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
        validation_errors = extract_validation_errors(sheet_id, sheet_index)
        
        # Log memory usage after validation
        post_validation_memory = get_memory_usage()
        logger.info(f"Memory usage after validation: {post_validation_memory}")
        
        # Prepare the response data
        response_data = {
            'sheet_id': sheet_id,
            'validation_errors': validation_errors,
            'memory_usage': {
                'initial': initial_memory,
                'pre_validation': pre_validation_memory,
                'post_validation': post_validation_memory
            }
        }
        
        # Check if this was called via API Gateway (event has 'httpMethod')
        if 'httpMethod' in event or 'requestContext' in event:
            return {
                'statusCode': 200,
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
