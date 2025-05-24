#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Test script for the HCA Entry Sheet Validator Lambda function.

This script allows you to test the Lambda function locally with different Google Sheet IDs.
"""

import json
import sys
import argparse
from hca_validation.lambda_functions.entry_sheet_validator_lambda.handler import handler

def main():
    """Run the Lambda function with a test event."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Test the HCA Entry Sheet Validator Lambda function')
    parser.add_argument('--sheet-id', type=str, 
                        default='1oPFb6qb0Y2HeoQqjSGRe_TlsZPRLwq-HUlVF0iqtVlY',
                        help='Google Sheet ID to validate')
    parser.add_argument('--sheet-index', type=int, default=0,
                        help='Sheet index (0-based)')
    args = parser.parse_args()
    
    # Create a test event
    test_event = {
        'sheet_id': args.sheet_id,
        'sheet_index': args.sheet_index
    }
    
    print(f"Testing Lambda function with sheet ID: {args.sheet_id}, index: {args.sheet_index}")
    
    # Call the Lambda function
    result = handler(test_event, None)
    
    # Print the result
    print("\nResult:")
    print(json.dumps(result, indent=2))
    
    # Print a summary
    if 'body' in result:
        # API Gateway response format
        body = json.loads(result['body'])
        is_valid = body.get('valid', False)
        errors = body.get('errors', [])
    else:
        # Direct Lambda invocation format
        is_valid = result.get('valid', False)
        errors = result.get('errors', [])
    
    if is_valid:
        print("\n✅ Sheet is valid! No errors found.")
    else:
        print(f"\n❌ Sheet has {len(errors)} validation errors.")

if __name__ == "__main__":
    main()
