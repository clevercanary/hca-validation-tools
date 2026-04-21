import json
import sys

from hca_schema_validator import HCAValidator

from ._log_capture import ListHandler, run_with_captured_logs

__all__ = ["ListHandler", "run_validator", "validator_logger_name"]

validator_logger_name = "hca_schema_validator._vendored.cellxgene_schema.validate"


def _reorder_feature_id_warnings_last(warnings):
  other, feature_id = [], []
  for w in warnings:
    (feature_id if "Feature ID '" in w else other).append(w)
  return other + feature_id


def run_validator(file_path):
  return run_with_captured_logs(
    file_path=file_path,
    logger_name=validator_logger_name,
    validate=lambda p: HCAValidator(ignore_labels=True).validate_adata(p),
    unexpected_error_prefix="Encountered an unexpected error while calling HCA schema validator",
    postprocess_warnings=_reorder_feature_id_warnings_last,
  )


if __name__ == "__main__":
  if len(sys.argv) < 2:
    raise Exception("Missing command line argument for file path")

  print(json.dumps(run_validator(sys.argv[1])))
