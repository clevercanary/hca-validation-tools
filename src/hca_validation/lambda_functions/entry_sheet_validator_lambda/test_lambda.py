#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Test script for the HCA Entry Sheet Validator Lambda function.

This script allows you to test the Lambda function locally with different Google Sheet IDs.
It can load service account credentials from a file or from the .env file.
"""

import json
import sys
import os
import argparse
from pathlib import Path
from dotenv import load_dotenv
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
    parser.add_argument('--creds-file', type=str,
                        help='Path to service account credentials JSON file')
    parser.add_argument('--env-file', type=str,
                        help='Path to .env file with GOOGLE_SERVICE_ACCOUNT variable')
    args = parser.parse_args()
    
    # Load service account credentials if provided
    if args.creds_file:
        if os.path.exists(args.creds_file):
            print(f"Loading service account credentials from {args.creds_file}")
            with open(args.creds_file, "r") as f:
                credentials = f.read()
                os.environ["GOOGLE_SERVICE_ACCOUNT"] = credentials
        else:
            print(f"Warning: Credentials file not found at {args.creds_file}")
    
    # Load from .env file if provided
    elif args.env_file:
        if os.path.exists(args.env_file):
            print(f"Loading environment variables from {args.env_file}")
            load_dotenv(args.env_file)
        else:
            print(f"Warning: .env file not found at {args.env_file}")
    
    # Try to load from default .env file location
    else:
        # Look for .env file in project root
        project_root = Path(__file__).parent.parent.parent.parent.parent
        env_file = project_root / ".env"
        if env_file.exists():
            print(f"Loading environment variables from {env_file}")
            load_dotenv(env_file)
    
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
        sheet_title = body.get('sheet_title', 'Unknown')
    else:
        # Direct Lambda invocation format
        is_valid = result.get('valid', False)
        errors = result.get('errors', [])
        sheet_title = result.get('sheet_title', 'Unknown')
    
    print(f"\nSheet title: {sheet_title}")
    if is_valid:
        print("\n✅ Sheet is valid! No errors found.")
    else:
        print(f"\n❌ Sheet has {len(errors)} validation errors.")

if __name__ == "__main__":
    main()
