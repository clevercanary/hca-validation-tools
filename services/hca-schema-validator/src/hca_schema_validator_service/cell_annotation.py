import json
import sys

from hca_schema_validator import HCACellAnnotationValidator

try:
  from ._log_capture import run_with_captured_logs
except ImportError:  # direct script execution (e.g. `python cell_annotation.py <file>`)
  from _log_capture import run_with_captured_logs  # type: ignore[no-redef]

validator_logger_name = "hca_schema_validator.cell_annotation_validator"


def run_validator(file_path):
  return run_with_captured_logs(
    file_path=file_path,
    logger_name=validator_logger_name,
    validate=lambda p: HCACellAnnotationValidator().validate_adata(p),
    unexpected_error_prefix="Encountered an unexpected error while calling HCA cell annotation validator",
  )


if __name__ == "__main__":
  if len(sys.argv) < 2:
    raise Exception("Missing command line argument for file path")

  print(json.dumps(run_validator(sys.argv[1])))
