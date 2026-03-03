import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from dataset_validator.main import ValidationToolReport, ValidationMessage, TRUNCATED_MESSAGES_MESSAGE

@pytest.mark.parametrize("test_case", [
    {
        "name": "none_truncated",
        "description": "Test length-limited JSON with no truncation needed",
        "message_length": 100,
        "message_counts": {
          "cap": {
            "errors": 50,
            "warnings": 20
          },
          "cellxgene": {
            "errors": 80,
            "warnings": 30
          }
        },
        "expected_min_length": 0,
        "expected_max_length": 20000,
        "expected_truncated_count": 0
    },
    {
        "name": "one_truncated",
        "description": "Test JSON with one warning list requiring truncation",
        "message_length": 100,
        "message_counts": {
          "cap": {
            "errors": 5,
            "warnings": 2500
          },
          "cellxgene": {
            "errors": 10,
            "warnings": 20
          }
        },
        "expected_min_length": 249800,
        "expected_max_length": 250000,
        "expected_truncated_count": 1
    },
    {
        "name": "multiple_truncated",
        "description": "Test JSON with multiple message lists requiring truncation",
        "message_length": 100,
        "message_counts": {
          "cap": {
            "errors": 3500,
            "warnings": 10
          },
          "cellxgene": {
            "errors": 5,
            "warnings": 3000
          }
        },
        "expected_min_length": 249800,
        "expected_max_length": 250000,
        "expected_truncated_count": 4
    },
    {
        "name": "errors_prioritized_over_warnings",
        "description": "Small warnings truncated before large errors, proving priority over length",
        "message_length": 100,
        "message_counts": {
          "cap": {
            "errors": 1200,
            "warnings": 50
          },
          "cellxgene": {
            "errors": 1200,
            "warnings": 50
          }
        },
        "expected_min_length": 249800,
        "expected_max_length": 250000,
        "expected_truncated_count": 2,
        "expect_errors_preserved": True
    },
    {
        "name": "hca_errors_prioritized_over_cellxgene_errors",
        "description": "Small cellxgene errors truncated before large cap/hcaSchema errors, proving tool priority over length",
        "message_length": 100,
        "message_counts": {
          "cap": {
            "errors": 1200,
            "warnings": 5
          },
          "cellxgene": {
            "errors": 50,
            "warnings": 5
          },
          "hcaSchema": {
            "errors": 1200,
            "warnings": 5
          }
        },
        "expected_min_length": 249800,
        "expected_max_length": 250000,
        "expect_tool_errors_preserved": ["hcaSchema", "cap"]
    },
], ids=lambda x: x["name"])
def test_length_limited_json_scenarios(test_case):
  timestamp = "2025-10-18T04:42:04.963Z"
  list_message = "x" * test_case["message_length"]
  message = ValidationMessage(
    file_id="test-file-id",
    status="success",
    timestamp=timestamp,
    bucket="test-bucket",
    key="test-key",
    batch_job_id="test-job-id",
    tool_reports={
      tool_key: ValidationToolReport(
        valid=False,
        errors=[list_message] * tool_counts["errors"],
        warnings=[list_message] * tool_counts["warnings"],
        started_at=timestamp,
        finished_at=timestamp
      )
      for tool_key, tool_counts in test_case["message_counts"].items()
    }
  )
  message_json = message.to_length_limited_json()
  assert test_case["expected_min_length"] <= len(message_json)
  assert len(message_json) <= test_case["expected_max_length"]
  if "expected_truncated_count" in test_case:
    assert message_json.count(f'"{TRUNCATED_MESSAGES_MESSAGE}"') == test_case["expected_truncated_count"]
  parsed = json.loads(message_json)
  if test_case.get("expect_errors_preserved"):
    for tool_report in parsed["tool_reports"].values():
      assert TRUNCATED_MESSAGES_MESSAGE not in tool_report["errors"], "Errors should not be truncated when warnings can be truncated instead"
  if test_case.get("expect_tool_errors_preserved"):
    for tool_key in test_case["expect_tool_errors_preserved"]:
      assert TRUNCATED_MESSAGES_MESSAGE not in parsed["tool_reports"][tool_key]["errors"], f"{tool_key} errors should not be truncated"
