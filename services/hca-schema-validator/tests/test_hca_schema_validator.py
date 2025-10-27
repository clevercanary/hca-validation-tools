import logging
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from hca_schema_validator.main import validator_logger_name, run_validator

@pytest.mark.parametrize("test_case", [
  {
    "name": "valid_no_messages",
    "description": "Test fully-successful validation",
    "file_path": "test.h5ad",
    "logs": [
      (logging.INFO, "Info foo")
    ],
    "is_valid": True,
    "error": None,
    "expected_output": {
      "valid": True,
      "errors": [],
      "warnings": []
    }
  },
  {
    "name": "valid_with_warnings",
    "description": "Test successful validation with warnings",
    "file_path": "test.h5ad",
    "logs": [
      (logging.INFO, "Info foo"),
      (logging.WARNING, "Warning foo"),
      (logging.WARNING, "Warning bar"),
      (logging.DEBUG, "Debug foo")
    ],
    "is_valid": True,
    "error": None,
    "expected_output": {
      "valid": True,
      "errors": [],
      "warnings": ["Warning foo", "Warning bar"]
    }
  },
  {
    "name": "invalid",
    "description": "Test validation with errors and warnings",
    "file_path": "test.h5ad",
    "logs": [
      (logging.ERROR, "Error foo"),
      (logging.WARNING, "Warning foo"),
      (logging.ERROR, "Error bar"),
      (logging.ERROR, "Error baz")
    ],
    "is_valid": False,
    "error": None,
    "expected_output": {
      "valid": False,
      "errors": ["Error foo", "Error bar", "Error baz"],
      "warnings": ["Warning foo"]
    }
  },
  {
    "name": "error",
    "description": "Test validation with error in validation process",
    "file_path": "test.h5ad",
    "logs": [
      (logging.WARNING, "Warning foo"),
    ],
    "is_valid": None,
    "error": Exception("Error in validation"),
    "expected_output": {
      "valid": False,
      "errors": ["Encountered an unexpected error while calling CELLxGENE validator: Error in validation"],
      "warnings": []
    }
  }
], ids=lambda x: x["name"])
@patch("cellxgene_validator.main.validate")
def test_cellxgene_validator_cases(mock_validate, test_case):
  def do_mock_validate(_, **__):
    logger = logging.getLogger(validator_logger_name)
    for level, message in test_case["logs"]:
      logger.log(level, message)
    return (test_case["is_valid"], None, None)

  if test_case["error"]:
    mock_validate.side_effect = test_case["error"]
  else:
    mock_validate.side_effect = do_mock_validate

  result = run_validator(test_case["file_path"])

  mock_validate.assert_called_once_with(test_case["file_path"], ignore_labels=True)
  assert result == test_case["expected_output"]
