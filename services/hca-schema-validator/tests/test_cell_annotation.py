import json
import logging
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hca_schema_validator import __version__

SRC_DIR = Path(__file__).parent.parent / "src"
CELL_ANNOTATION_SCRIPT = SRC_DIR / "hca_schema_validator_service" / "cell_annotation.py"
MAIN_SCRIPT = SRC_DIR / "hca_schema_validator_service" / "main.py"

sys.path.insert(0, str(SRC_DIR))
from hca_schema_validator_service.cell_annotation import (  # noqa: E402
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
            "expected_output": {
                "valid": True,
                "errors": [],
                "warnings": ["Warning foo", "Warning bar"],
            },
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
            "logs": [(logging.WARNING, "Warning foo")],
            "is_valid": None,
            "error": Exception("Error in validation"),
            "expected_output": {
                "valid": False,
                "errors": [
                    "Encountered an unexpected error while calling HCA cell annotation validator: Error in validation"
                ],
                "warnings": [],
            },
        },
    ],
    ids=lambda x: x["name"],
)
@patch("hca_schema_validator_service.cell_annotation.HCACellAnnotationValidator")
def test_hca_cell_annotation_validator_cases(mock_validator_class, test_case):
    def do_mock_validate(_, **__):
        logger = logging.getLogger(validator_logger_name)
        for level, message in test_case["logs"]:
            logger.log(level, message)
        return test_case["is_valid"]

    mock_validator_instance = MagicMock()
    mock_validator_class.return_value = mock_validator_instance

    mock_validate_adata = MagicMock()
    mock_validator_instance.validate_adata = mock_validate_adata

    if test_case["error"]:
        mock_validate_adata.side_effect = test_case["error"]
    else:
        mock_validate_adata.side_effect = do_mock_validate

    result = run_validator(test_case["file_path"])

    mock_validator_class.assert_called_once_with()
    mock_validate_adata.assert_called_once_with(test_case["file_path"])
    # Every response also names the validator release that ran (#802)
    assert result == {**test_case["expected_output"], "validator_version": __version__}


@pytest.mark.parametrize(
    ("script_path", "extra_args"),
    [(MAIN_SCRIPT, ["source"]), (CELL_ANNOTATION_SCRIPT, [])],
    ids=["main", "cell_annotation"],
)
def test_subprocess_script_imports_cleanly(script_path, extra_args, tmp_path):
    """Invoking the script by path (as the dataset-validator does) must not
    fail at import time. Catches relative-import regressions and other
    early-execution failures (ModuleNotFoundError, SyntaxError, etc.) that
    the mock-based dataset-validator tests skip.

    We can't assert returncode == 0 here because HCAValidator.validate_adata
    calls sys.exit(1) on a missing file — a pre-existing behavior unrelated
    to the module-load path we care about. Instead, assert no Python
    traceback appears in stderr; any unhandled exception during import or
    early execution would produce one."""
    result = subprocess.run(
        [sys.executable, str(script_path), str(tmp_path / "nonexistent.h5ad"), *extra_args],
        capture_output=True,
        text=True,
    )
    assert "Traceback" not in result.stderr, f"{script_path.name} failed at import or early execution: {result.stderr}"
    assert "usage:" not in result.stderr, f"{script_path.name} refused its arguments: {result.stderr}"


@pytest.mark.parametrize("object_kind", ["source", "integrated"])
def test_main_subprocess_runs_the_real_validator_with_the_kind(object_kind, tmp_path):
    import anndata as ad
    import numpy as np
    import pandas as pd
    import scipy.sparse as sp

    path = tmp_path / "tiny.h5ad"
    ad.AnnData(
        X=sp.csr_matrix(np.ones((3, 2), dtype=np.float32)),
        obs=pd.DataFrame(index=["c1", "c2", "c3"]),
        var=pd.DataFrame(index=["ENSG00000141510", "ENSG00000012048"]),
    ).write_h5ad(path)

    result = subprocess.run(
        [sys.executable, str(MAIN_SCRIPT), str(path), object_kind], capture_output=True, text=True, check=True
    )
    report = json.loads(result.stdout)

    assert report["validator_version"] == __version__
    assert not [error for error in report["errors"] if "object_kind" in error or "unexpected error" in error]
    # A schema finding only the real validator reports, so it ran rather than failing to construct
    assert "ERROR: 'title' in 'uns' is not present." in report["errors"]


def test_cell_annotation_subprocess_returns_json(tmp_path):
    """End-to-end: cell_annotation.py invoked by path returns a well-formed
    failure report when the input file doesn't exist (HCACellAnnotationValidator
    catches the read error and returns valid=False). This exercises the real
    import + logger-capture path, which test_local_file_mode in the
    dataset-validator tests skips by using a mock script."""
    result = subprocess.run(
        [sys.executable, str(CELL_ANNOTATION_SCRIPT), str(tmp_path / "nonexistent.h5ad")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    output = json.loads(result.stdout)
    assert output["valid"] is False
    assert any("Unable to read h5ad file" in e for e in output["errors"])


def test_main_subprocess_refuses_without_a_kind(tmp_path):
    """main.py invoked by path with no kind exits non-zero, naming the two kinds, before running the validator."""
    result = subprocess.run(
        [sys.executable, str(MAIN_SCRIPT), str(tmp_path / "nonexistent.h5ad")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "{source,integrated}" in result.stderr
