import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hca_schema_validator import __version__

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from hca_schema_validator_service.main import (
    parse_args,
    run_validator,
    validator_logger_name,
)


@pytest.mark.parametrize(
    "test_case",
    [
        {
            "name": "valid_no_messages",
            "description": "Test fully-successful validation",
            "file_path": "test.h5ad",
            "logs": [(logging.INFO, "Info foo")],
            "is_valid": True,
            "error": None,
            "expected_output": {"valid": True, "errors": [], "warnings": []},
        },
        {
            "name": "valid_with_warnings",
            "description": "Test successful validation with warnings",
            "file_path": "test.h5ad",
            "logs": [
                (logging.INFO, "Info foo"),
                (logging.WARNING, "Warning foo"),
                (logging.WARNING, "Warning bar"),
                (logging.DEBUG, "Debug foo"),
            ],
            "is_valid": True,
            "error": None,
            "expected_output": {"valid": True, "errors": [], "warnings": ["Warning foo", "Warning bar"]},
        },
        {
            "name": "invalid",
            "description": "Test validation with errors and warnings",
            "file_path": "test.h5ad",
            "logs": [
                (logging.ERROR, "Error foo"),
                (logging.WARNING, "Warning foo"),
                (logging.ERROR, "Error bar"),
                (logging.ERROR, "Error baz"),
            ],
            "is_valid": False,
            "error": None,
            "expected_output": {
                "valid": False,
                "errors": ["Error foo", "Error bar", "Error baz"],
                "warnings": ["Warning foo"],
            },
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
                "errors": ["Encountered an unexpected error while calling HCA schema validator: Error in validation"],
                "warnings": [],
            },
        },
    ],
    ids=lambda x: x["name"],
)
@pytest.mark.parametrize("object_kind", ["source", "integrated"])
@patch("hca_schema_validator_service.main.HCAValidator")
def test_hca_schema_validator_cases(mock_hca_validator, object_kind, test_case):
    def do_mock_validate(_, **__):
        logger = logging.getLogger(validator_logger_name)
        for level, message in test_case["logs"]:
            logger.log(level, message)
        return test_case["is_valid"]

    mock_validator_instance = MagicMock()
    mock_hca_validator.return_value = mock_validator_instance

    mock_validate_adata = MagicMock()
    mock_validator_instance.validate_adata = mock_validate_adata

    if test_case["error"]:
        mock_validate_adata.side_effect = test_case["error"]
    else:
        mock_validate_adata.side_effect = do_mock_validate

    result = run_validator(test_case["file_path"], object_kind)

    mock_hca_validator.assert_called_once_with(ignore_labels=True, object_kind=object_kind)
    mock_validate_adata.assert_called_once_with(test_case["file_path"])
    # Every response also names the validator release that ran (#802)
    assert result == {**test_case["expected_output"], "validator_version": __version__}


@pytest.mark.parametrize("object_kind", ["source", "integrated"])
def test_parse_args_accepts_path_and_kind(object_kind):
    assert parse_args(["test.h5ad", object_kind]) == ("test.h5ad", object_kind)


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["test.h5ad"],
        ["test.h5ad", "integrated-objects"],
        ["test.h5ad", "Source"],
        ["test.h5ad", "source", "extra"],
    ],
    ids=["no_args", "no_kind", "wrong_kind", "wrong_case", "extra_arg"],
)
def test_parse_args_rejects_anything_else(args, capsys):
    with pytest.raises(SystemExit) as exit_info:
        parse_args(args)

    assert exit_info.value.code == 2
    assert "usage: main.py [-h] file_path {source,integrated}" in capsys.readouterr().err
