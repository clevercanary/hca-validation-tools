#!/usr/bin/env python
# -*- coding: utf-8 -*-

import pandas as pd
import requests
import io
import sys
import time

def read_public_sheet(sheet_id, sheet_index=0):
    """
    Read data from a public Google Sheet using the CSV export URL.
    
    Args:
        sheet_id: The ID of the Google Sheet (from the URL)
        sheet_index: The index of the sheet (0-based)
        
    Returns:
        Pandas DataFrame with the sheet data
    """
    # Use the gviz/tq URL format which works well for public sheets
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&gid={sheet_index}"
    
    try:
        # Get the sheet data
        response = requests.get(url)
        response.raise_for_status()  # Raise exception for HTTP errors
        
        # Read CSV data into a DataFrame
        df = pd.read_csv(io.StringIO(response.text))
        return df
    except Exception as e:
        print(f"Error accessing Google Sheet: {e}")
        return pd.DataFrame()

def validate_google_sheet(sheet_id="1oPFb6qb0Y2HeoQqjSGRe_TlsZPRLwq-HUlVF0iqtVlY", sheet_index=0, error_handler=None):
    """
    Validate data from a Google Sheet starting at row 6 until the first empty row.
    
    Args:
        sheet_id: The ID of the Google Sheet
        sheet_index: The index of the sheet (0-based)
        error_handler: Optional callback function that takes (row_index, error) parameters
                      to handle validation errors externally
    """
    from hca_validation.validator import validate
    
    # Read the sheet
    print(f"Reading sheet: {sheet_id}")
    df = read_public_sheet(sheet_id, sheet_index)
    
    if df.empty:
        print("Could not read data from the sheet.")
        return
    
    # Skip the first column as it has no slot name
    if len(df.columns) > 1:
        df = df.iloc[:, 1:]
    
    # Print information about the sheet structure
    print(f"Sheet has {len(df)} rows total")
    
    # Find rows with actual data to validate
    rows_to_validate = []
    row_indices = []
    
    # Debug: Print the first few rows to understand the structure
    print("\nSheet structure:")
    for i in range(min(10, len(df))):
        if i < len(df):
            first_col = df.iloc[i, 0] if not pd.isna(df.iloc[i, 0]) else "<empty>"
            print(f"Row {i+1} (index {i}): {first_col}")
    
    # Process rows 4, 5, and then from row 6 until the first empty row
    # We'll include rows 4 and 5 as you mentioned they also contain data
    data_row_indices = [3, 4]  # Rows 4 and 5 (0-based indices 3 and 4)
    
    # First add rows 4 and 5
    for idx in data_row_indices:
        if idx < len(df):
            row = df.iloc[idx]
            # Skip completely empty rows
            if not row.isna().all() and not all(str(val).strip() == '' for val in row if not pd.isna(val)):
                print(f"Adding row {idx + 1} for validation")
                rows_to_validate.append(row)
                row_indices.append(idx)
    
    # Then process from row 6 until the first empty row
    start_row_index = 5  # Row 6 (1-based) is index 5 (0-based)
    current_row_index = start_row_index
    
    print(f"\nProcessing data rows starting from row 6 (index {start_row_index})...")
    
    while current_row_index < len(df):
        # Get the current row
        row = df.iloc[current_row_index]
        
        # Check if row is empty (all values are NaN or empty strings)
        is_empty = row.isna().all() or all(str(val).strip() == '' for val in row if not pd.isna(val))
        
        if is_empty:
            # Stop at the first empty row
            print(f"Found empty row at row {current_row_index + 1}, stopping")
            break
        
        # Add non-empty row for validation
        print(f"Adding row {current_row_index + 1} for validation")
        rows_to_validate.append(row)
        row_indices.append(current_row_index)
        
        # Move to the next row
        current_row_index += 1
    
    if not rows_to_validate:
        print("No data found to validate starting from row 6.")
        return
    
    print(f"Found {len(rows_to_validate)} rows to validate.")
    
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
                    print(f"Warning: Could not parse list value '{value}' for field '{key}': {e}")
                    row_dict[key] = value
            else:
                row_dict[key] = value
        
        # Validate the data
        print(f"\nValidating row {row_index}...")
        try:
            validation_result = validate(row_dict, schema_type="dataset")
            
            # Report results
            if validation_result.results:
                all_valid = False
                print(f"Row {row_index} has validation errors:")
                for error in validation_result.results:
                    print(f"  - {error.message}")
                    # Call error handler if provided
                    if error_handler:
                        error_handler(row_index, error)
            else:
                print(f"Row {row_index} is valid")
        except Exception as e:
            all_valid = False
            print(f"Error validating row {row_index}: {e}")
            # Call error handler for exceptions if provided
            if error_handler:
                error = type('ValidationError', (), {'message': str(e), 'field': None, 'value': None})
                error_handler(row_index, error)
    
    # Summary
    if all_valid:
        print(f"\nAll {len(rows_to_validate)} rows are valid!")
    else:
        print(f"\nValidation found errors in some of the {len(rows_to_validate)} rows.")
        print("Please check the schema requirements and update the data accordingly.")
        print("You can view the schema at: /Users/dave/projects/hca-validation-tools/src/hca_validation/schema/dataset.yaml")


if __name__ == "__main__":
    # Get sheet ID from command line if provided
    sheet_id = sys.argv[1] if len(sys.argv) > 1 else "1oPFb6qb0Y2HeoQqjSGRe_TlsZPRLwq-HUlVF0iqtVlY"
    validate_google_sheet(sheet_id)
