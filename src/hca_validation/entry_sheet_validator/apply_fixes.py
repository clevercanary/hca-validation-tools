from typing import List
import gspread

from hca_validation.entry_sheet_validator.validate_sheet import SheetErrorInfo, SheetValidationResult


def get_fix_value_range(a1: str, value: str):
  """
  Create a value range dict to be passed to gspread in order to set the specified cell to the given raw value
  
  Args:
    a1:
      The A1 notation of the cell to set the value of
    value:
      The value to be written to the cell
    
  Returns:
    dict:
      A value range dictionary without a specified worksheet
  """
  return {
    "range": a1,
    "values": [[value]]
  }


def get_fix_value_ranges_by_entity_type(errors: List[SheetErrorInfo], entity_types: List[str]):
  """
  Create value range dicts to be passed to gspread in order to fix the given errors, organized by entity type
  
  Args:
    errors:
      List of validation errors that may have fixes specified
    entity_types:
      List of entity types that the errors may apply to
    
  Returns:
    dict:
      Dictionary mapping entity types to lists of value range dicts.
  """
  cells_with_fixes = set()
  value_ranges = {entity_type: [] for entity_type in entity_types}

  for error in errors:
    if error.input_fix is not None and error.entity_type is not None and error.cell is not None and (error.entity_type, error.cell) not in cells_with_fixes:
      value_ranges[error.entity_type].append(get_fix_value_range(error.cell, error.input_fix))
      cells_with_fixes.add((error.entity_type, error.cell))
  
  return value_ranges


def apply_fixes(validation_result: SheetValidationResult, entity_types: List[str], worksheets: List[gspread.Worksheet]) -> bool:
  """
  Apply available fixes from the given validation result to the given gspread worksheets
  
  Args:
    validation_result:
      SheetValidationResult containing validation errors that may have fixes specified
    entity_types:
      List of entity types being processed
    worksheets:
      List of gspread worksheets, corresponding element-wise to entity_types
    
  Returns:
    bool:
      True if any fixes were applied to any worksheet, False if no fixes were applied
  """
  worksheets_by_entity_type = dict(zip(entity_types, worksheets))

  value_ranges_by_entity_type = get_fix_value_ranges_by_entity_type(validation_result.errors, entity_types)

  made_fixes = False

  for entity_type, value_ranges in value_ranges_by_entity_type.items():
    if not value_ranges:
      continue
    worksheet = worksheets_by_entity_type[entity_type]
    worksheet.batch_update(value_ranges)
    made_fixes = True
  
  return made_fixes
