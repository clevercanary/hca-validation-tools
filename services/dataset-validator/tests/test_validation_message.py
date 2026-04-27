import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from dataset_validator.main import ValidationToolReport, ValidationMessage, TRUNCATED_MESSAGES_PREFIX

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
        "description": (
            "Small cellxgene errors truncated before large cap/hcaSchema errors, "
            "proving tool priority over length"
        ),
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
    {
        "name": "hca_cell_annotation_errors_preserved_longest",
        "description": (
            "hcaCellAnnotation errors should be preserved longest — "
            "truncated only after cellxgene, cap, and hcaSchema errors"
        ),
        "message_length": 100,
        "message_counts": {
          "cap": {
            "errors": 1200,
            "warnings": 5
          },
          "cellxgene": {
            "errors": 1200,
            "warnings": 5
          },
          "hcaSchema": {
            "errors": 1200,
            "warnings": 5
          },
          "hcaCellAnnotation": {
            "errors": 50,
            "warnings": 5
          }
        },
        "expected_min_length": 249800,
        "expected_max_length": 250000,
        "expect_tool_errors_preserved": ["hcaCellAnnotation"]
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
    assert message_json.count(TRUNCATED_MESSAGES_PREFIX) == test_case["expected_truncated_count"]
  parsed = json.loads(message_json)

  def _has_truncation_marker(items):
    return any(isinstance(s, str) and s.startswith(TRUNCATED_MESSAGES_PREFIX) for s in items)

  if test_case.get("expect_errors_preserved"):
    for tool_report in parsed["tool_reports"].values():
      assert not _has_truncation_marker(tool_report["errors"]), (
        "Errors should not be truncated when warnings can be truncated instead"
      )
  if test_case.get("expect_tool_errors_preserved"):
    for tool_key in test_case["expect_tool_errors_preserved"]:
      assert not _has_truncation_marker(parsed["tool_reports"][tool_key]["errors"]), (
        f"{tool_key} errors should not be truncated"
      )


def _build_message(tool_reports):
  ts = "2025-10-18T04:42:04.963Z"
  return ValidationMessage(
    file_id="test-file-id", status="success", timestamp=ts,
    bucket="test-bucket", key="test-key", batch_job_id="test-job-id",
    tool_reports={
      tool_key: ValidationToolReport(
        valid=not r["errors"], errors=r["errors"], warnings=r["warnings"],
        started_at=ts, finished_at=ts,
      )
      for tool_key, r in tool_reports.items()
    },
  )


def test_empty_lists_serialize_as_empty():
  """Empty error/warning lists keep their `[]` serialization rather than getting
  the truncation placeholder. Without this, the tracker UI inflates warningCount
  to 1 and shows a false PartiallyValidIcon for tools that had nothing to say.
  See #382."""
  large = "x" * 100
  message = _build_message({
    "cap": {"errors": [], "warnings": []},  # empty
    "cellxgene": {"errors": [], "warnings": []},  # empty
    "hcaSchema": {"errors": [], "warnings": [large] * 5000},  # overflows
    "hcaCellAnnotation": {"errors": [], "warnings": []},  # empty
  })
  parsed = json.loads(message.to_length_limited_json())
  for tool in ("cap", "cellxgene", "hcaCellAnnotation"):
    assert parsed["tool_reports"][tool]["errors"] == [], (
      f"{tool}.errors should be [] but got {parsed['tool_reports'][tool]['errors']}"
    )
    assert parsed["tool_reports"][tool]["warnings"] == [], (
      f"{tool}.warnings should be [] but got {parsed['tool_reports'][tool]['warnings']}"
    )


def test_placeholder_includes_counts():
  """Truncation placeholder embeds (retained of total shown) so curators see
  how many messages were dropped even when binary search retains a fraction."""
  large = "x" * 100
  message = _build_message({
    "cap": {"errors": [], "warnings": []},
    "cellxgene": {"errors": [], "warnings": []},
    "hcaSchema": {"errors": [], "warnings": [large] * 5000},
    "hcaCellAnnotation": {"errors": [], "warnings": []},
  })
  parsed = json.loads(message.to_length_limited_json())
  warnings = parsed["tool_reports"]["hcaSchema"]["warnings"]
  marker = warnings[-1]
  match = re.fullmatch(rf"{re.escape(TRUNCATED_MESSAGES_PREFIX)} \((\d+) of (\d+) shown\)", marker)
  assert match, f"placeholder should match count format, got: {marker!r}"
  retained, total = int(match.group(1)), int(match.group(2))
  assert total == 5000, f"original count should be preserved, got {total}"
  assert retained == len(warnings) - 1, f"retained count {retained} should match list length {len(warnings)-1}"


def test_collapsed_to_zero_still_reports_original_count():
  """When higher-priority lists fill the budget, the threshold list collapses to
  zero retained — the placeholder must still report the original count so the
  curator knows there's something hidden. Mirrors the Cohen scenario where
  hcaSchema warnings collapse because the budget is consumed by other tools.
  See #382."""
  big = "x" * 250
  message = _build_message({
    "cap": {"errors": [], "warnings": []},
    "cellxgene": {"errors": [], "warnings": []},
    "hcaSchema": {"errors": [], "warnings": [big] * 50},  # small but truncated first
    "hcaCellAnnotation": {"errors": [big] * 1100, "warnings": []},  # fills budget
  })
  parsed = json.loads(message.to_length_limited_json())
  warnings = parsed["tool_reports"]["hcaSchema"]["warnings"]
  assert len(warnings) == 1, f"expected collapse to placeholder only, got {len(warnings)} entries"
  assert warnings[0] == f"{TRUNCATED_MESSAGES_PREFIX} (0 of 50 shown)", (
    f"unexpected placeholder: {warnings[0]!r}"
  )
