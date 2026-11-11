import argparse
import json
import sys

from hca_schema_validator import OBJECT_KINDS, HCAValidator, ObjectKind

try:
    from ._log_capture import ListHandler, run_with_captured_logs
except ImportError:  # direct script execution (e.g. `python main.py <file> <object_kind>`)
    from _log_capture import ListHandler, run_with_captured_logs  # type: ignore[no-redef]

__all__ = ["ListHandler", "parse_args", "run_validator", "validator_logger_name"]

validator_logger_name = "hca_schema_validator._vendored.cellxgene_schema.validate"


def _reorder_feature_id_warnings_last(warnings):
    other, feature_id = [], []
    for w in warnings:
        (feature_id if "Feature ID '" in w else other).append(w)
    return other + feature_id


def run_validator(file_path, object_kind: ObjectKind):
    return run_with_captured_logs(
        file_path=file_path,
        logger_name=validator_logger_name,
        validate=lambda p: HCAValidator(ignore_labels=True, object_kind=object_kind).validate_adata(p),
        unexpected_error_prefix="Encountered an unexpected error while calling HCA schema validator",
        postprocess_warnings=_reorder_feature_id_warnings_last,
    )


def parse_args(args: list[str]) -> tuple[str, ObjectKind]:
    """Return the file path and object kind from the command-line arguments after the script name.

    Raises:
        SystemExit: with code 2 when ``args`` is not exactly a path and one of ``OBJECT_KINDS``,
            and with code 0 after printing help for ``-h``.
    """
    parser = argparse.ArgumentParser(prog="main.py")
    parser.add_argument("file_path")
    parser.add_argument("object_kind", choices=OBJECT_KINDS)
    parsed = parser.parse_args(args)
    return parsed.file_path, parsed.object_kind


if __name__ == "__main__":
    print(json.dumps(run_validator(*parse_args(sys.argv[1:]))))
