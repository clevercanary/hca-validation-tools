"""Tests for the dataset validator service."""

import json
import logging
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Any, List
from unittest.mock import MagicMock, patch
import sys

import boto3
import pytest
from moto import mock_s3, mock_sns
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _setup_metadata_mocks(mock_read_inputs, mock_matrix_storage, test_adata):
    """Configure the read_file_metadata seam mocks from a test ``adata`` spec.

    ``read_file_metadata`` reads obs/uns/shape via ``_read_metadata_inputs`` and
    per-matrix storage via ``get_matrix_storage`` (no full h5ad open), so tests
    drive those two seams instead of mocking ``anndata.read_h5ad``.
    """
    if test_adata is None:
        return
    if "exception" in test_adata:
        mock_read_inputs.side_effect = test_adata["exception"]
        return
    obs_df = pd.DataFrame(test_adata["obs"])
    mock_read_inputs.return_value = (
        obs_df,
        test_adata["uns"],
        obs_df.shape[0],
        test_adata["n_vars"],
    )
    mock_matrix_storage.return_value = test_adata.get("matrix_storage")


# Use the venv prefix of the interpreter running the tests (apply_external_validator
# appends `/bin/python` to this), so the suite doesn't depend on an in-project
# `.venv/` existing — works under `uv run pytest`, an IDE runner, or CI regardless
# of how the env was created.
dataset_validator_venv_path = sys.prefix
mock_modules_path = Path(__file__).parent / "mock-modules"
external_validator_path_vars = {
    'CELLXGENE_VALIDATOR_VENV': dataset_validator_venv_path,
    'CELLXGENE_VALIDATOR_SCRIPT': str(mock_modules_path / "cellxgene_validator.py"),
    'HCA_SCHEMA_VALIDATOR_VENV': dataset_validator_venv_path,
    'HCA_SCHEMA_VALIDATOR_SCRIPT': str(mock_modules_path / "hca_schema_validator.py"),
    'HCA_CELL_ANNOTATION_VALIDATOR_SCRIPT': str(mock_modules_path / "hca_cell_annotation_validator.py"),
    'CAP_VALIDATOR_SCRIPT': str(mock_modules_path / "cap_validator.py"),
}


@pytest.fixture
def mock_aws():
    """Fixture that provides mocked AWS services (S3 and SNS)."""
    # Set AWS_DEFAULT_REGION for consistent behavior
    original_region = os.environ.get('AWS_DEFAULT_REGION')
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
    
    try:
        with mock_s3(), mock_sns():
            # Create S3 client and buckets
            s3_client = boto3.client('s3', region_name='us-east-1')
            s3_client.create_bucket(Bucket='test-bucket')
            s3_client.create_bucket(Bucket='test-results-bucket')

            # Create SNS client and topic
            sns_client = boto3.client('sns', region_name='us-east-1')
            topic_response = sns_client.create_topic(Name='test-topic')
            topic_arn = topic_response['TopicArn']

            yield {
                's3_client': s3_client,
                'sns_client': sns_client,
                'topic_arn': topic_arn,
                'bucket_name': 'test-bucket',
                'validation_results_bucket_name': 'test-results-bucket',
            }
    finally:
        # Restore original region
        if original_region is None:
            os.environ.pop('AWS_DEFAULT_REGION', None)
        else:
            os.environ['AWS_DEFAULT_REGION'] = original_region


@pytest.fixture
def base_env_vars():
    """Fixture that provides base environment variables for testing."""
    return {
        'S3_BUCKET': 'test-bucket',
        'S3_KEY': 'test/file.h5ad',
        'FILE_ID': 'test-file-uuid',
        'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-1:123456789012:test-topic',
        'AWS_BATCH_JOB_ID': 'test-job-id',
        'BATCH_JOB_NAME': 'test-job',
        'AWS_DEFAULT_REGION': 'us-east-1'
    }


@pytest.fixture
def env_manager():
    """Fixture that provides environment variable management utilities."""
    original_env = {}
    
    def set_env(env_vars: Dict[str, str]):
        """Set environment variables and save originals for cleanup."""
        for key, value in env_vars.items():
            original_env[key] = os.environ.get(key)
            os.environ[key] = value
    
    def clear_env(keys: list):
        """Clear specific environment variables."""
        for key in keys:
            original_env[key] = os.environ.get(key)
            os.environ.pop(key, None)
    
    def restore_env():
        """Restore original environment variables."""
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        original_env.clear()
    
    yield {
        'set': set_env,
        'clear': clear_env,
        'restore': restore_env
    }
    
    # Cleanup after test
    restore_env()

class TestDatasetValidator:
    """Test cases for the dataset validator main functionality."""

    @pytest.mark.parametrize("test_case", [
        {
            "name": "no_config",
            "description": "Test that validator fails when no S3 config is provided",
            "env_vars": {},  # Empty - will clear S3_BUCKET and S3_KEY
            "clear_vars": ['S3_BUCKET', 'S3_KEY'],
            "expected_exit_code": 1,
            "expected_logs": [
                "Dataset Validator starting",
                "Missing required environment variables"
            ]
        },
        {
            "name": "invalid_s3_config", 
            "description": "Test that validator fails when invalid S3 config is provided",
            "env_vars": {
                'S3_BUCKET': 'invalid-test-bucket',
                'S3_KEY': 'invalid/test/file.h5ad',
                'FILE_ID': 'test-file-uuid',
                'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-1:123456789012:test-topic',
                'AWS_BATCH_JOB_ID': 'test-job-id',
                'AWS_DEFAULT_REGION': 'us-east-1'
            },
            "clear_vars": [],
            "expected_exit_code": 1,
            "expected_logs": [
                "Dataset Validator starting",
                "Work directory created:",
                "Processing S3 file: s3://invalid-test-bucket/invalid/test/file.h5ad",
                "S3 download failed",
                "Dataset Validator failed:"
            ]
        },
        {
            "name": "work_directory_creation",
            "description": "Test that work directory is created correctly with valid S3 config",
            "env_vars": {
                'S3_BUCKET': 'test-bucket',
                'S3_KEY': 'test/file.h5ad',
                'FILE_ID': 'test-file-uuid',
                'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-1:123456789012:test-topic',
                'AWS_BATCH_JOB_ID': 'test-job-id',
                'AWS_DEFAULT_REGION': 'us-east-1',
                'BATCH_JOB_NAME': 'test-job'
            },
            "clear_vars": [],
            "expected_exit_code": 1,
            "expected_logs": [
                "Work directory created: /tmp/dataset_validator"
            ]
        }
    ], ids=lambda x: x["name"])
    def test_subprocess_validation_scenarios(self, test_case):
        """Parameterized test for various subprocess validation scenarios."""
        # Prepare environment
        env = os.environ.copy()
        
        # Add mock AWS credentials for subprocess tests
        env.update({
            'AWS_ACCESS_KEY_ID': 'testing',
            'AWS_SECRET_ACCESS_KEY': 'testing',
            'AWS_SECURITY_TOKEN': 'testing',
            'AWS_SESSION_TOKEN': 'testing'
        })
        
        # Clear specified variables
        for var in test_case["clear_vars"]:
            env.pop(var, None)
            
        # Set test-specific variables
        env.update(test_case["env_vars"])
        
        # Run the validator
        result = subprocess.run(
            [sys.executable, 'src/dataset_validator/main.py'],
            capture_output=True,
            text=True,
            env=env
        )
        
        # Verify exit code
        assert result.returncode == test_case["expected_exit_code"]
        
        # Verify expected log messages
        for expected_log in test_case["expected_logs"]:
            assert expected_log in result.stdout


def test_missing_sns_topic_logs_error_and_exits(caplog, env_manager, base_env_vars):
    """Test that missing SNS_TOPIC_ARN logs error and exits with code 1."""
    from dataset_validator.main import main

    # Set up environment with missing SNS_TOPIC_ARN
    test_env = base_env_vars.copy()
    del test_env['SNS_TOPIC_ARN']  # Remove SNS topic to test missing variable
    env_manager['set'](test_env)

    # Capture logs from the specific logger
    with caplog.at_level(logging.ERROR, logger="dataset_validator.main"):
        result = main()

    # Should exit with code 1
    assert result == 1

    # Should log the missing environment variable error
    assert "Missing required environment variables" in caplog.text
    assert "SNS_TOPIC_ARN=None" in caplog.text


def test_missing_bucket_skips_s3_claim_check(caplog, env_manager, base_env_vars):
    """When env validation fails before resolving a bucket, no S3 write is attempted."""
    from dataset_validator.main import main

    test_env = base_env_vars.copy()
    del test_env['S3_BUCKET']
    env_manager['set'](test_env)
    env_manager['clear'](['S3_BUCKET'])

    with caplog.at_level(logging.INFO, logger="dataset_validator.main"):
        result = main()

    assert result == 1
    assert "Missing required environment variables" in caplog.text
    # The S3 claim-check write must be skipped — there's no actionable bucket.
    assert "S3 claim check write" not in caplog.text


@pytest.mark.parametrize("test_case", [
    {
        "name": "all_present",
        "description": "Test reading metadata with all fields present",
        "adata": {
            "obs": {
                "assay": ["assay-a", "assay-b", "assay-b", "assay-c", "assay-a"],
                "suspension_type": [
                    "suspension-type-a",
                    "suspension-type-a",
                    "suspension-type-a",
                    "suspension-type-a",
                    "suspension-type-a",
                ],
                "tissue": ["tissue-a", "tissue-a", "tissue-b", "tissue-a", "tissue-a"],
                "disease": ["disease-a", "disease-b", "disease-c", "disease-d", "disease-e"]
            },
            "uns": {"title": "test-dataset-123"},
            "n_vars": 12
        },
        "expected_result": {
            "title": "test-dataset-123",
            "assay": ["assay-a", "assay-b", "assay-c"],
            "suspension_type": ["suspension-type-a"],
            "tissue": ["tissue-a", "tissue-b"],
            "disease": ["disease-a", "disease-b", "disease-c", "disease-d", "disease-e"],
            "cell_count": 5,
            "gene_count": 12
        }
    },
    {
        "name": "all_missing",
        "description": "Test reading metadata with all possible fields absent",
        "adata": {
            "obs": {},
            "uns": {},
            "n_vars": 0
        },
        "expected_result": {
            "title": "",
            "assay": [],
            "suspension_type": [],
            "tissue": [],
            "disease": [],
            "cell_count": 0,
            "gene_count": 0
        }
    },
    {
        "name": "nan",
        "description": "Test that NAN is converted to string",
        "adata": {
            "obs": {
                "assay": ["assay-a", "assay-b", np.nan],
                "suspension_type": ["suspension-type-a", np.nan, "suspension-type-b"],
                "tissue": [np.nan, "tissue-a", "tissue-a"],
                "disease": ["disease-a", np.nan, np.nan]
            },
            "uns": {"title": "test-dataset-456"},
            "n_vars": 23
        },
        "expected_result": {
            "title": "test-dataset-456",
            "assay": ["assay-a", "assay-b", "nan"],
            "suspension_type": ["suspension-type-a", "nan", "suspension-type-b"],
            "tissue": ["nan", "tissue-a"],
            "disease": ["disease-a", "nan"],
            "cell_count": 3,
            "gene_count": 23
        }
    }
], ids=lambda x: x["name"])
def test_extract_metadata_summary_scenarios(test_case):
    """Parameterized test for the metadata summary extraction (obs/uns -> MetadataSummary)."""
    from dataset_validator.main import _extract_metadata_summary, MetadataSummary

    # _extract_metadata_summary only reads .obs/.uns/.n_obs/.n_vars
    obs = pd.DataFrame(test_case["adata"]["obs"])
    adata_like = SimpleNamespace(
        obs=obs,
        uns=test_case["adata"]["uns"],
        n_obs=obs.shape[0],
        n_vars=test_case["adata"]["n_vars"],
    )

    metadata_summary = _extract_metadata_summary(adata_like)

    assert metadata_summary == MetadataSummary(**test_case["expected_result"])


def test_read_file_metadata_real_h5ad(tmp_path):
    """read_file_metadata reads obs/uns/shape + matrix_storage from a real h5ad
    without loading matrices (the #447 fix path: no read_h5ad(backed="r"))."""
    import anndata as ad
    import scipy.sparse as sp
    from dataset_validator.main import read_file_metadata

    n_obs, n_vars = 5, 8
    X = sp.random(n_obs, n_vars, density=0.5, format="csr", dtype=np.float32)
    obs = pd.DataFrame({
        "assay": ["a", "a", "b", "b", "a"],
        "suspension_type": ["cell"] * 5,
        "tissue": ["lung"] * 5,
        "disease": ["normal"] * 5,
        "donor_id": ["d1", "d1", "d2", "d2", "d2"],
    }, index=[f"cell{i}" for i in range(n_obs)])
    adata = ad.AnnData(X=X, obs=obs)
    adata.uns["title"] = "tiny"
    adata.raw = adata
    adata.layers["denoised"] = X.copy()
    path = tmp_path / "tiny.h5ad"
    adata.write_h5ad(path)

    summary, coverage, storage = read_file_metadata(path)

    # Summary read straight from obs/uns (not the matrices)
    assert summary.title == "tiny"
    assert summary.cell_count == n_obs
    assert summary.gene_count == n_vars
    assert set(summary.assay) == {"a", "b"}

    # Coverage still computed from the same obs/uns
    assert coverage is not None
    assert isinstance(coverage["field_coverage"], list)

    # Matrix storage captured from the HDF5 header for X, raw.X and the layer
    assert storage["X"]["format"] == "csr_matrix"
    assert (storage["X"]["n_obs"], storage["X"]["n_vars"]) == (n_obs, n_vars)
    assert storage["raw_X"] is not None
    assert "denoised" in storage["layers"]


def test_read_shape_var_fallback_is_robust(tmp_path):
    """When X has no shape header, _read_shape falls back to var — and must
    degrade (n_vars=0) rather than raise on a missing/malformed var index."""
    import h5py
    from dataset_validator.main import _read_shape

    obs = pd.DataFrame({"a": [1, 2, 3]})

    # X is a 1-D dataset (no usable 2-D shape) and var lacks an "_index" attr.
    path = tmp_path / "weird.h5ad"
    with h5py.File(path, "w") as f:
        f.create_dataset("X", data=np.zeros(3, dtype=np.float32))
        f.create_group("var")
        n_obs, n_vars = _read_shape(f, obs)
    assert (n_obs, n_vars) == (3, 0)

    # var with a valid (bytes) _index pointing at a real dataset → counted.
    path2 = tmp_path / "weird2.h5ad"
    with h5py.File(path2, "w") as f:
        f.create_dataset("X", data=np.zeros(3, dtype=np.float32))
        var = f.create_group("var")
        var.attrs["_index"] = b"gene_id"
        var.create_dataset("gene_id", data=np.arange(7))
        n_obs, n_vars = _read_shape(f, obs)
    assert (n_obs, n_vars) == (3, 7)

    # var._index points at a group (not a dataset) → degrade, don't raise.
    path3 = tmp_path / "weird3.h5ad"
    with h5py.File(path3, "w") as f:
        f.create_dataset("X", data=np.zeros(3, dtype=np.float32))
        var = f.create_group("var")
        var.attrs["_index"] = "idx"
        var.create_group("idx")
        n_obs, n_vars = _read_shape(f, obs)
    assert (n_obs, n_vars) == (3, 0)

    # X has a scalar (non-sequence) shape attr → fall through to the var index
    # rather than raising on len(shape).
    path4 = tmp_path / "weird4.h5ad"
    with h5py.File(path4, "w") as f:
        x = f.create_group("X")
        x.attrs["shape"] = np.int64(5)            # scalar, not a 2-tuple
        var = f.create_group("var")
        var.attrs["_index"] = "gene_id"
        var.create_dataset("gene_id", data=np.arange(7))
        n_obs, n_vars = _read_shape(f, obs)
    assert (n_obs, n_vars) == (3, 7)


def test_matrix_storage_excluded_from_sns_message():
    """matrix_storage is kept in the full claim-check JSON but never reaches SNS.

    Formerly (#447) this was enforced by a `_to_sns_json` serializer that
    stripped the key, because a large matrix_storage could push the inline SNS
    body over the limit. The body is now pointer-only (#408), so the guarantee
    holds by construction: matrix_storage is excluded the same way tool_reports
    and metadata_summary are — by not being a pointer field at all.
    """
    from dataset_validator.main import ValidationMessage

    # A pathologically large matrix_storage (thousands of layers) with empty
    # tool reports — the case that previously slipped past the length limiter.
    big_layers = {
        f"layer_{i}": {
            "format": "csr_matrix", "n_obs": 1, "n_vars": 1, "nnz": 0,
            "data_dtype": "float32", "index_dtype": "int64",
            "on_disk_bytes": 0, "resident_bytes": 0,
        }
        for i in range(5000)
    }
    msg = ValidationMessage(
        file_id="f", status="success", timestamp="2024-01-01T00:00:00Z",
        bucket="b", key="k", batch_job_id="j",
        matrix_storage={"X": None, "raw_X": None, "layers": big_layers},
    )

    # Full claim-check payload retains matrix_storage...
    full = json.loads(msg.to_json())
    assert len(full["matrix_storage"]["layers"]) == 5000

    # ...while the SNS body carries the six pointer fields and nothing else,
    # however large matrix_storage grows.
    sns = json.loads(msg.to_pointer().to_json())
    assert set(sns) == {
        "file_id", "status", "timestamp", "bucket", "key", "batch_job_id"
    }


@pytest.mark.parametrize("test_case", [
    {
        "name": "success",
        "description": "Test successful CAP validation via mock subprocess",
        "cap_mock_error": None,
        "expected_report": {
            "valid": True,
            "errors": []
        }
    },
    {
        "name": "error",
        "description": "Test CAP validation error via mock subprocess",
        "cap_mock_error": "Error in CAP validator",
        "expected_report": {
            "valid": False,
            "errors": ["Encountered an unexpected error while calling CAP validator: Error in CAP validator"]
        }
    }
], ids=lambda x: x["name"])
def test_cap_validator_scenarios(test_case, monkeypatch):
    """Parameterized test for CAP validation via subprocess."""
    from dataset_validator.main import apply_cap_validator, ValidationToolReport

    # Point at the mock CAP validator script
    monkeypatch.setenv("CAP_VALIDATOR_SCRIPT", str(mock_modules_path / "cap_validator.py"))
    if test_case["cap_mock_error"]:
        monkeypatch.setenv("CAP_MOCK_ERROR", test_case["cap_mock_error"])
    else:
        monkeypatch.delenv("CAP_MOCK_ERROR", raising=False)

    report = apply_cap_validator(Path("test-file.h5ad"))

    assert isinstance(report, ValidationToolReport)
    assert isinstance(report.started_at, str)
    assert isinstance(report.finished_at, str)
    assert report.started_at <= report.finished_at
    assert report.valid == test_case["expected_report"]["valid"]
    assert report.errors == test_case["expected_report"]["errors"]
    assert report.warnings == []


def _build_cap_multi_exception(exceptions):
    """Helper to build a CapMultiException from a list of exceptions."""
    from cap_upload_validator.errors import CapMultiException
    multi_ex = CapMultiException()
    for ex in exceptions:
        multi_ex.append(ex)
    return multi_ex


@pytest.mark.parametrize("test_case", [
    {
        "name": "success",
        "description": "Test cap_validator_script with successful validation",
        "exception": None,
        "expected_valid": True,
        "expected_errors": []
    },
    {
        "name": "cap_exception",
        "description": "Test cap_validator_script with CapException",
        "exception": "AnnDataMissingCountMatrix",
        "expected_valid": False,
        "expected_errors_contain": "AnnDataMissingCountMatrix"
    },
    {
        "name": "cap_multi_exception",
        "description": "Test cap_validator_script with CapMultiException (multiple errors)",
        "exception": "CapMultiException",
        "expected_valid": False,
        "expected_error_count": 2
    },
    {
        "name": "generic_exception",
        "description": "Test cap_validator_script with unexpected Exception",
        "exception": "Exception",
        "expected_valid": False,
        "expected_errors_contain": "Encountered an unexpected error"
    }
], ids=lambda x: x["name"])
@patch("dataset_validator.cap_validator_script.UploadValidator")
def test_cap_validator_script_scenarios(mock_upload_validator, test_case):
    """Unit tests for cap_validator_script.py exception handling."""
    from cap_upload_validator.errors import CapException, CapMultiException, AnnDataMissingCountMatrix
    from dataset_validator.cap_validator_script import main

    mock_instance = MagicMock()
    mock_upload_validator.return_value = mock_instance

    if test_case["exception"] == "AnnDataMissingCountMatrix":
        mock_instance.validate.side_effect = AnnDataMissingCountMatrix()
    elif test_case["exception"] == "CapMultiException":
        mock_instance.validate.side_effect = _build_cap_multi_exception([
            CapException(), AnnDataMissingCountMatrix()
        ])
    elif test_case["exception"] == "Exception":
        mock_instance.validate.side_effect = Exception("something broke")
    # else: no exception, validate() succeeds

    # Patch sys.argv for the script.
    # Note: we patch sys.stdout to capture output. The script internally redirects
    # stdout during validation (to suppress UploadValidator prints) and restores it
    # afterward — which restores to our patched StringIO, so the final JSON lands here.
    with patch("sys.argv", ["cap_validator_script.py", "test-file.h5ad"]):
        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            main()

    output = json.loads(captured.getvalue())

    assert output["valid"] == test_case["expected_valid"]
    assert output["warnings"] == []

    if "expected_errors" in test_case:
        assert output["errors"] == test_case["expected_errors"]
    if "expected_errors_contain" in test_case:
        assert any(test_case["expected_errors_contain"] in e for e in output["errors"]), \
            f"Expected error containing '{test_case['expected_errors_contain']}', got: {output['errors']}"
    if "expected_error_count" in test_case:
        assert len(output["errors"]) == test_case["expected_error_count"], \
            f"Expected {test_case['expected_error_count']} errors, got {len(output['errors'])}: {output['errors']}"

    mock_upload_validator.assert_called_once_with("test-file.h5ad")
    mock_instance.validate.assert_called_once()


@pytest.mark.parametrize("test_case", [
    {
        "name": "success",
        "description": "Test successful SNS message publishing",
        "message_data": {
            'file_id': 'test-file-123',
            'status': 'success',
            'timestamp': '2024-01-01T12:00:00Z',
            'bucket': 'test-bucket',
            'key': 'test/file.h5ad',
            'batch_job_id': 'job-123',
            'batch_job_name': 'test-job',
            'downloaded_sha256': 'abc123',
            'source_sha256': 'abc123',
            'integrity_status': 'valid',
            'metadata_summary': None,
            'tool_reports': None,
            'metadata_coverage': None,
            'matrix_storage': None,
            'error_message': None
        },
        "use_valid_topic": True,
        "expected_result": True,
        "log_level": logging.INFO,
        "expected_logs": [
            "Publishing validation result to SNS topic",
            "Successfully published SNS message"
        ]
    },
    {
        "name": "invalid_topic",
        "description": "Test SNS publishing with invalid topic ARN",
        "message_data": {
            'file_id': 'test-file-123',
            'status': 'failure',
            'timestamp': '2024-01-01T12:00:00Z',
            'bucket': 'test-bucket',
            'key': 'test/file.h5ad',
            'batch_job_id': 'job-123',
            'error_message': 'Test error'
        },
        "use_valid_topic": False,
        "expected_result": False,
        "log_level": logging.ERROR,
        "expected_logs": [
            "SNS publish failed"
        ]
    }
], ids=lambda x: x["name"])
def test_publish_validation_result_scenarios(caplog, mock_aws, test_case):
    """Parameterized test for SNS publishing scenarios."""
    from dataset_validator.main import publish_validation_result, ValidationMessage, configure_logging
    
    # Configure logging for the test
    configure_logging()
    
    # Create test validation message
    message = ValidationMessage(**test_case["message_data"])
    
    # Choose topic ARN based on test case
    if test_case["use_valid_topic"]:
        topic_arn = mock_aws['topic_arn']
    else:
        topic_arn = 'arn:aws:sns:us-east-1:123456789012:nonexistent-topic'
    
    # Test publishing
    with caplog.at_level(test_case["log_level"], logger="dataset_validator.main"):
        result = publish_validation_result(message, topic_arn)
    
    # Verify result
    assert result is test_case["expected_result"]
    
    # Verify expected log messages
    for expected_log in test_case["expected_logs"]:
        assert expected_log in caplog.text
    
    # For success case, verify the SNS body is the pointer-only payload
    # — file_id / status / timestamp / bucket / key / batch_job_id and nothing
    # else. The full ValidationMessage lives in the S3 claim check.
    if test_case["name"] == "success":
        published = _get_last_sns_message(_get_sns_backend(), topic_arn)
        assert published == {
            "file_id": test_case["message_data"]["file_id"],
            "status": test_case["message_data"]["status"],
            "timestamp": test_case["message_data"]["timestamp"],
            "bucket": test_case["message_data"]["bucket"],
            "key": test_case["message_data"]["key"],
            "batch_job_id": test_case["message_data"]["batch_job_id"],
        }


def _build_message(**overrides) -> "object":
    """Helper to build a ValidationMessage for claim-check tests."""
    from dataset_validator.main import ValidationMessage
    base = {
        'file_id': 'test-file-uuid',
        'status': 'success',
        'timestamp': '2024-01-01T12:00:00Z',
        'bucket': 'test-bucket',
        'key': 'datasets/test.h5ad',
        'batch_job_id': 'job-abc',
        'batch_job_name': 'test-job',
        'downloaded_sha256': 'abc123',
        'source_sha256': 'abc123',
        'integrity_status': 'valid',
        'metadata_summary': None,
        'tool_reports': None,
        'error_message': None,
    }
    base.update(overrides)
    return ValidationMessage(**base)


def test_write_validation_results_to_s3_success(caplog, mock_aws):
    """Successful claim-check write places a JSON object at the expected key."""
    from dataset_validator.main import write_validation_results_to_s3, configure_logging
    configure_logging()

    message = _build_message(file_id='file-1', batch_job_id='job-1')

    with caplog.at_level(logging.INFO, logger="dataset_validator.main"):
        result = write_validation_results_to_s3(
            message, mock_aws['bucket_name'], 'file-1', 'job-1'
        )

    assert result is True
    assert "S3 claim check write succeeded for file file-1" in caplog.text

    obj = mock_aws['s3_client'].get_object(
        Bucket=mock_aws['bucket_name'],
        Key='validation-metadata/file-1/job-1.json',
    )
    body = obj['Body'].read().decode('utf-8')
    assert json.loads(body) == json.loads(message.to_json())
    assert obj['ContentType'] == 'application/json'


def test_write_validation_results_to_s3_failure(caplog, mock_aws):
    """Write to a nonexistent bucket logs the error and returns False without raising."""
    from dataset_validator.main import write_validation_results_to_s3, configure_logging
    configure_logging()

    message = _build_message(file_id='file-2', batch_job_id='job-2')

    with caplog.at_level(logging.ERROR, logger="dataset_validator.main"):
        result = write_validation_results_to_s3(
            message, 'nonexistent-bucket', 'file-2', 'job-2'
        )

    assert result is False
    assert "S3 claim check write failed for file file-2" in caplog.text


def test_write_validation_results_to_s3_writes_full_untruncated_json(mock_aws):
    """The body written to S3 is the full to_json() output, however large.

    Nothing truncates on this path. The binding size constraint is the tracker's,
    not ours: it caps the claim check at 5 MB and rejects an oversized payload
    visibly as `results_not_loaded` (hca-atlas-tracker#1265) rather than silently
    ingesting a lossy one. Our own ceiling is `put_object`'s 5 GB single-request
    limit — three orders of magnitude above that cap, and five above the ~100 KB
    a payload actually runs to since #400/#402.
    """
    from dataset_validator.main import (
        write_validation_results_to_s3,
        ValidationToolReport,
    )

    # Comfortably larger than the 250 KB the old SNS body was capped at, so the
    # test shows the claim check is not bounded by that historical limit.
    OLD_SNS_CAP = 250_000

    huge_errors = [f"error-{i}" for i in range(20000)]
    tool_reports = {
        "cap": ValidationToolReport(
            valid=False, errors=huge_errors, warnings=[],
            started_at='2024-01-01T12:00:00Z', finished_at='2024-01-01T12:00:01Z',
        ),
        "cellxgene": ValidationToolReport(
            valid=True, errors=[], warnings=[],
            started_at='2024-01-01T12:00:00Z', finished_at='2024-01-01T12:00:01Z',
        ),
        "hcaSchema": ValidationToolReport(
            valid=True, errors=[], warnings=[],
            started_at='2024-01-01T12:00:00Z', finished_at='2024-01-01T12:00:01Z',
        ),
        "hcaCellAnnotation": ValidationToolReport(
            valid=True, errors=[], warnings=[],
            started_at='2024-01-01T12:00:00Z', finished_at='2024-01-01T12:00:01Z',
        ),
    }
    message = _build_message(
        file_id='file-3', batch_job_id='job-3', tool_reports=tool_reports
    )

    # Sanity: the message must actually exceed the old SNS cap, otherwise the
    # test wouldn't be meaningfully exercising the claim-check use case.
    full_json = message.to_json()
    assert len(full_json) > OLD_SNS_CAP

    assert write_validation_results_to_s3(
        message, mock_aws['bucket_name'], 'file-3', 'job-3'
    ) is True

    obj = mock_aws['s3_client'].get_object(
        Bucket=mock_aws['bucket_name'],
        Key='validation-metadata/file-3/job-3.json',
    )
    body = obj['Body'].read().decode('utf-8')
    assert body == full_json


@pytest.mark.parametrize("test_case", [
    {
        "name": "success",
        "description": "Local file mode completes validation, skips S3 and prints JSON to stdout",
        "adata": {
            "obs": {
                "assay": ["assay-a"],
                "suspension_type": ["cell"],
                "tissue": ["lung"],
                "disease": ["normal"]
            },
            "uns": {"title": "local-test"},
            "n_vars": 10
        },
        "expected_exit_code": 0,
        "expected_logs": [
            "Local file mode: validating",
            "Validation completed successfully",
        ],
        "unexpected_logs": [
            "Starting download:",
            "Verifying file integrity",
            "Publishing validation result to SNS",
            "S3 claim check write",
        ],
        "expected_stdout": {
            "status": "success",
            "integrity_status": "valid",
            "file_id": "local",
            "batch_job_id": "local",
            "bucket": "local",
            "metadata_summary": {
                "title": "local-test",
                "assay": ["assay-a"],
                "suspension_type": ["cell"],
                "tissue": ["lung"],
                "disease": ["normal"],
                "cell_count": 1,
                "gene_count": 10
            }
        }
    },
    {
        "name": "file_not_found",
        "description": "Local file mode fails when file does not exist",
        "adata": None,
        "local_file_override": "/nonexistent/path.h5ad",
        "expected_exit_code": 1,
        "expected_logs": [
            "Missing required environment variables",
            "file does not exist",
        ],
        "unexpected_logs": [],
        "expected_stdout": None
    }
], ids=lambda x: x["name"])
@patch("dataset_validator.main.get_matrix_storage")
@patch("dataset_validator.main._read_metadata_inputs")
def test_local_file_mode(mock_read_inputs, mock_matrix_storage, caplog, env_manager, tmp_path, test_case, capsys):
    """Test LOCAL_FILE mode skips S3/integrity, prints JSON when no SNS."""
    from dataset_validator.main import main

    # Create a dummy local file (unless the test overrides the path)
    local_file = test_case.get("local_file_override")
    if local_file is None:
        local_file = str(tmp_path / "test.h5ad")
        Path(local_file).touch()

    # Set only LOCAL_FILE — no S3/SNS/Batch vars
    env_manager['set']({
        'LOCAL_FILE': local_file,
        **external_validator_path_vars,
    })
    # Ensure S3/SNS vars are not set
    env_manager['clear'](['S3_BUCKET', 'S3_KEY', 'FILE_ID', 'SNS_TOPIC_ARN', 'AWS_BATCH_JOB_ID'])

    # Drive the metadata read seam (obs/uns/shape + matrix storage)
    _setup_metadata_mocks(mock_read_inputs, mock_matrix_storage, test_case["adata"])

    with caplog.at_level(logging.INFO, logger="dataset_validator.main"):
        result = main()

    assert result == test_case["expected_exit_code"]

    for expected_log in test_case["expected_logs"]:
        assert expected_log in caplog.text

    for unexpected_log in test_case["unexpected_logs"]:
        assert unexpected_log not in caplog.text, f"Did not expect log: {unexpected_log}"

    # Verify JSON output on stdout (local mode with no SNS)
    if test_case["expected_stdout"] is not None:
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        for key, expected_value in test_case["expected_stdout"].items():
            assert output[key] == expected_value, f"Expected {key}={expected_value}, got {output[key]}"
        # Verify tool reports are present
        assert output["tool_reports"] is not None
        assert "cap" in output["tool_reports"]
        assert "cellxgene" in output["tool_reports"]
        assert "hcaSchema" in output["tool_reports"]
        assert "hcaCellAnnotation" in output["tool_reports"]


@pytest.mark.parametrize("test_case", [
    {
        "name": "success",
        "description": "Test complete validation workflow with successful validation",
        "s3_key": "datasets/test.h5ad",
        "file_id": "test-file-123",
        "batch_job_id": "job-456",
        "batch_job_name": "test-validation-job",
        "setup_s3": lambda s3_client, bucket_name: _setup_valid_s3_file(s3_client, bucket_name, "datasets/test.h5ad"),
        "adata": {
            "obs": {
                "assay": ["assay-a", "assay-b", "assay-b", "assay-c", "assay-a"],
                "suspension_type": [
                    "suspension-type-a",
                    "suspension-type-a",
                    "suspension-type-a",
                    "suspension-type-a",
                    "suspension-type-a",
                ],
                "tissue": ["tissue-a", "tissue-a", "tissue-b", "tissue-a", "tissue-a"],
                "disease": ["disease-a", "disease-b", "disease-c", "disease-d", "disease-e"]
            },
            "uns": {"title": "test-dataset-123"},
            "n_vars": 14
        },
        "expected_exit_code": 0,
        "expected_logs": [
            "Dataset Validator starting",
            "Processing S3 file: s3://test-bucket/datasets/test.h5ad",
            "Work directory created:",
            "File ready for validation:",
            "Validation completed successfully",
            "Publishing validation result to SNS topic",
            "Successfully published SNS message",
            "Dataset Validator completed successfully"
        ],
        "expected_sns_message": {
            "status": "success",
            "integrity_status": "valid",
            "file_id": "test-file-123",
            "batch_job_id": "job-456",
            "batch_job_name": "test-validation-job",
            "error_message": None,
            "metadata_summary": {
                "title": "test-dataset-123",
                "assay": ["assay-a", "assay-b", "assay-c"],
                "suspension_type": ["suspension-type-a"],
                "tissue": ["tissue-a", "tissue-b"],
                "disease": ["disease-a", "disease-b", "disease-c", "disease-d", "disease-e"],
                "cell_count": 5,
                "gene_count": 14
            },
            "tool_reports": {
                "cap": {
                    "valid": True,
                    "errors": [],
                    "warnings": []
                },
                # cellxgene is stubbed in main.py (apply_cellxgene_validator
                # is no longer called) — see #382. Expected output reflects
                # the empty stub, not the mock script's "ERROR: test" output.
                "cellxgene": {
                    "valid": True,
                    "errors": [],
                    "warnings": []
                },
                "hcaSchema": {
                    "valid": False,
                    "errors": ["ERROR: test bar"],
                    "warnings": ["WARNING: test bar"]
                },
                "hcaCellAnnotation": {
                    "valid": False,
                    "errors": ["ERROR: test baz"],
                    "warnings": ["WARNING: test baz"]
                }
            }
        }
    },
    {
        "name": "download_failure",
        "description": "Test complete validation workflow with S3 download failure",
        "s3_key": "datasets/nonexistent.h5ad",
        "file_id": "test-file-456",
        "batch_job_id": "job-789",
        "batch_job_name": None,
        "setup_s3": lambda s3_client, bucket_name: None,  # Don't upload any file
        "adata": None,
        "expected_exit_code": 1,
        "expected_logs": [
            "Dataset Validator starting",
            "Processing S3 file: s3://test-bucket/datasets/nonexistent.h5ad",
            "S3 download failed",
            "Dataset Validator failed:",
            "Publishing validation result to SNS topic",
            "Successfully published SNS message"
        ],
        "expected_sns_message": {
            "status": "failure",
            "integrity_status": None,
            "file_id": "test-file-456",
            "batch_job_id": "job-789",
            "batch_job_name": None,
            "metadata_summary": None,
            "tool_reports": None
        }
    },
    {
        "name": "integrity_failure",
        "description": "Test complete validation workflow with file integrity failure",
        "s3_key": "datasets/corrupt.h5ad",
        "file_id": "test-file-789",
        "batch_job_id": "job-101",
        "batch_job_name": None,
        "setup_s3": lambda s3_client, bucket_name: _setup_corrupt_s3_file(
            s3_client, bucket_name, "datasets/corrupt.h5ad"
        ),
        "adata": None,
        "expected_exit_code": 1,
        "expected_logs": [
            "Dataset Validator starting",
            "File ready for validation:",
            "File integrity verification failed - terminating",
            "Publishing validation result to SNS topic",
            "Successfully published SNS message"
        ],
        "expected_sns_message": {
            "status": "failure",
            "integrity_status": "invalid",
            "file_id": "test-file-789",
            "batch_job_id": "job-101",
            "batch_job_name": None,
            "metadata_summary": None,
            "tool_reports": None
        }
    },
    {
        "name": "metadata_failure",
        "description": "Test complete validation workflow with failure reading metadata",
        "s3_key": "datasets/test.h5ad",
        "file_id": "test-file-123",
        "batch_job_id": "job-456",
        "batch_job_name": "test-validation-job",
        "setup_s3": lambda s3_client, bucket_name: _setup_valid_s3_file(s3_client, bucket_name, "datasets/test.h5ad"),
        "adata": {
            "exception": Exception("Test metadata error")
        },
        "expected_exit_code": 1,
        "expected_logs": [
            "Dataset Validator starting",
            "Processing S3 file: s3://test-bucket/datasets/test.h5ad",
            "Work directory created:",
            "File ready for validation:",
            "Error reading metadata:",
            "Dataset Validator failed:",
            "Publishing validation result to SNS topic",
            "Successfully published SNS message"
        ],
        "expected_sns_message": {
            "status": "failure",
            "integrity_status": "valid",
            "file_id": "test-file-123",
            "batch_job_id": "job-456",
            "batch_job_name": "test-validation-job",
            "error_message": "Dataset Validator failed: Test metadata error",
            "metadata_summary": None,
            "tool_reports": None
        }
    },
    {
        "name": "cap_failure",
        "description": "Test complete validation workflow with successful validation",
        "s3_key": "datasets/test.h5ad",
        "file_id": "test-file-123",
        "batch_job_id": "job-456",
        "batch_job_name": "test-validation-job",
        "setup_s3": lambda s3_client, bucket_name: _setup_valid_s3_file(s3_client, bucket_name, "datasets/test.h5ad"),
        "adata": {
            "obs": {
                "assay": ["assay-a", "assay-b", "assay-b", "assay-c", "assay-a"],
                "suspension_type": [
                    "suspension-type-a",
                    "suspension-type-a",
                    "suspension-type-a",
                    "suspension-type-a",
                    "suspension-type-a",
                ],
                "tissue": ["tissue-a", "tissue-a", "tissue-b", "tissue-a", "tissue-a"],
                "disease": ["disease-a", "disease-b", "disease-c", "disease-d", "disease-e"]
            },
            "uns": {"title": "test-dataset-123"},
            "n_vars": 17
        },
        "cap_mock_error": "Error in CAP validator",
        "expected_exit_code": 0,
        "expected_logs": [
            "Dataset Validator starting",
            "Processing S3 file: s3://test-bucket/datasets/test.h5ad",
            "Work directory created:",
            "File ready for validation:",
            "Validation completed successfully",
            "Publishing validation result to SNS topic",
            "Successfully published SNS message",
            "Dataset Validator completed successfully"
        ],
        "expected_sns_message": {
            "status": "success",
            "integrity_status": "valid",
            "file_id": "test-file-123",
            "batch_job_id": "job-456",
            "batch_job_name": "test-validation-job",
            "error_message": None,
            "metadata_summary": {
                "title": "test-dataset-123",
                "assay": ["assay-a", "assay-b", "assay-c"],
                "suspension_type": ["suspension-type-a"],
                "tissue": ["tissue-a", "tissue-b"],
                "disease": ["disease-a", "disease-b", "disease-c", "disease-d", "disease-e"],
                "cell_count": 5,
                "gene_count": 17
            },
            "tool_reports": {
                "cap": {
                    "valid": False,
                    "errors": ["Encountered an unexpected error while calling CAP validator: Error in CAP validator"],
                    "warnings": []
                },
                # cellxgene stubbed in main.py — see #382.
                "cellxgene": {
                    "valid": True,
                    "errors": [],
                    "warnings": []
                },
                "hcaSchema": {
                    "valid": False,
                    "errors": ["ERROR: test bar"],
                    "warnings": ["WARNING: test bar"]
                },
                "hcaCellAnnotation": {
                    "valid": False,
                    "errors": ["ERROR: test baz"],
                    "warnings": ["WARNING: test baz"]
                }
            }
        }
    }
], ids=lambda x: x["name"])
@patch("dataset_validator.main.get_matrix_storage")
@patch("dataset_validator.main._read_metadata_inputs")
def test_end_to_end_validation_scenarios(mock_read_inputs, mock_matrix_storage, caplog, mock_aws, env_manager, test_case):
    """Parameterized test for end-to-end validation scenarios."""
    from dataset_validator.main import main

    # Setup S3 file based on test case
    test_case["setup_s3"](mock_aws['s3_client'], mock_aws['bucket_name'])

    # Set environment variables using fixture
    test_env = {
        'S3_BUCKET': mock_aws['bucket_name'],
        'S3_KEY': test_case["s3_key"],
        'VALIDATION_RESULTS_BUCKET': mock_aws['validation_results_bucket_name'],
        'FILE_ID': test_case["file_id"],
        'SNS_TOPIC_ARN': mock_aws['topic_arn'],
        'AWS_BATCH_JOB_ID': test_case["batch_job_id"],
        **external_validator_path_vars
    }
    if test_case["batch_job_name"]:
        test_env['BATCH_JOB_NAME'] = test_case["batch_job_name"]
    env_manager['set'](test_env)
    # Manage CAP_MOCK_ERROR: set if specified, clear otherwise to prevent bleed between tests
    if test_case.get("cap_mock_error"):
        env_manager['set']({'CAP_MOCK_ERROR': test_case["cap_mock_error"]})
    else:
        env_manager['clear'](['CAP_MOCK_ERROR'])

    # Drive the metadata read seam (obs/uns/shape + matrix storage)
    _setup_metadata_mocks(mock_read_inputs, mock_matrix_storage, test_case["adata"])

    # Run main function
    with caplog.at_level(logging.INFO, logger="dataset_validator.main"):
        result = main()

    # Verify exit code
    assert result == test_case["expected_exit_code"]

    # Verify expected log messages
    for expected_log in test_case["expected_logs"]:
        assert expected_log in caplog.text

    # Verify SNS pointer body + S3 claim-check heavy fields
    _validate_published_result(
        mock_aws,
        caplog,
        test_case["expected_sns_message"],
        source_bucket=mock_aws['bucket_name'],
        source_key=test_case["s3_key"],
    )
    assert "S3 claim check write succeeded" in caplog.text


@patch("dataset_validator.main.get_matrix_storage")
@patch("dataset_validator.main._read_metadata_inputs")
def test_unset_validation_results_bucket_skips_s3_claim_check(
    mock_read_inputs, mock_matrix_storage, caplog, mock_aws, env_manager
):
    """VALIDATION_RESULTS_BUCKET is optional: when unset, validation still
    completes successfully but no S3 claim-check write is attempted."""
    from dataset_validator.main import main

    s3_key = "datasets/test.h5ad"
    _setup_valid_s3_file(mock_aws['s3_client'], mock_aws['bucket_name'], s3_key)

    env_manager['set']({
        'S3_BUCKET': mock_aws['bucket_name'],
        'S3_KEY': s3_key,
        'FILE_ID': 'test-file-no-results-bucket',
        'SNS_TOPIC_ARN': mock_aws['topic_arn'],
        'AWS_BATCH_JOB_ID': 'job-no-results-bucket',
        **external_validator_path_vars,
    })
    env_manager['clear'](['VALIDATION_RESULTS_BUCKET', 'CAP_MOCK_ERROR'])

    _setup_metadata_mocks(mock_read_inputs, mock_matrix_storage, {
        "obs": {
            "assay": ["assay-a"],
            "suspension_type": ["cell"],
            "tissue": ["lung"],
            "disease": ["normal"],
        },
        "uns": {"title": "test"},
        "n_vars": 10,
    })

    with caplog.at_level(logging.INFO, logger="dataset_validator.main"):
        result = main()

    assert result == 0
    assert "Validation completed successfully" in caplog.text
    # Claim-check write must be skipped entirely — no success or failure log.
    assert "S3 claim check write" not in caplog.text


def _get_last_sns_message(sns_backend, topic_arn):
    """Helper function to extract and parse the last SNS message from moto backend."""
    import json
    
    # Get all sent notifications for our topic
    all_sent_notifications = sns_backend.topics[topic_arn].sent_notifications
    assert len(all_sent_notifications) > 0, "No SNS messages were published"
    
    # Parse the last published message
    last_notification = all_sent_notifications[-1]
    
    # Handle different moto notification formats
    if isinstance(last_notification, dict):
        message_content = last_notification['Message']
    elif isinstance(last_notification, tuple):
        # In some moto versions, notifications are stored as tuples
        message_content = last_notification[1]  # Usually (subject, message, ...)
    else:
        message_content = str(last_notification)
    
    return json.loads(message_content)


def _get_sns_backend():
    """Return moto's in-memory SNS backend for us-east-1."""
    from moto.core import DEFAULT_ACCOUNT_ID
    from moto.sns import sns_backends
    return sns_backends[DEFAULT_ACCOUNT_ID]["us-east-1"]


def _validate_published_result(mock_aws, caplog, expected_message, source_bucket, source_key):
    """Validate the published validation result.

    The SNS body is pointer-only (file_id / status / timestamp / bucket
    / key / batch_job_id) and the heavy fields (integrity_status,
    batch_job_name, metadata_summary, tool_reports, error_message) live in
    the S3 claim check. This helper enforces that split: pointer fields are
    checked on SNS, everything else on the claim-check object.

    source_bucket / source_key identify the file that was validated; they
    appear on both the SNS pointer and the claim-check body and must match.
    """

    topic_arn = mock_aws['topic_arn']

    # Verify at least one message was published
    assert "Successfully published SNS message" in caplog.text

    # Get and parse the last published message
    sns_body = _get_last_sns_message(_get_sns_backend(), topic_arn)

    # SNS body is pointer-only — assert the exact set of keys plus their values
    # for fields the test pins. timestamp isn't pinned by the test cases but
    # must be present (it's a required pointer field).
    assert set(sns_body.keys()) == {
        "file_id", "status", "timestamp", "bucket", "key", "batch_job_id"
    }, f"SNS body should be pointer-only, got keys: {sorted(sns_body.keys())}"
    assert sns_body["status"] == expected_message["status"]
    assert sns_body["file_id"] == expected_message["file_id"]
    assert sns_body["batch_job_id"] == expected_message["batch_job_id"]
    assert sns_body["bucket"] == source_bucket
    assert sns_body["key"] == source_key

    # Heavy fields are asserted on the S3 claim check, which is the
    # authoritative payload.
    expected_key = (
        f"validation-metadata/{expected_message['file_id']}"
        f"/{expected_message['batch_job_id']}.json"
    )
    claim_obj = mock_aws['s3_client'].get_object(
        Bucket=mock_aws['validation_results_bucket_name'], Key=expected_key
    )
    claim_body = json.loads(claim_obj['Body'].read().decode('utf-8'))

    assert claim_body["status"] == expected_message["status"]
    assert claim_body["bucket"] == source_bucket
    assert claim_body["key"] == source_key
    assert claim_body["integrity_status"] == expected_message["integrity_status"], (
        f"Expected integrity_status '{expected_message['integrity_status']}', "
        f"got '{claim_body['integrity_status']}'"
    )
    assert claim_body["file_id"] == expected_message["file_id"]
    assert claim_body["batch_job_id"] == expected_message["batch_job_id"]
    assert claim_body["batch_job_name"] == expected_message["batch_job_name"]
    assert claim_body["metadata_summary"] == expected_message["metadata_summary"]

    if expected_message["tool_reports"] is None:
        assert claim_body["tool_reports"] is None
    else:
        tool_reports_without_times = {
            tool: {k: v for k, v in report.items() if k not in {"started_at", "finished_at"}}
            for tool, report in claim_body["tool_reports"].items()
        }
        assert tool_reports_without_times == expected_message["tool_reports"]

    if expected_message.get("error_message") is not None:
        assert claim_body.get("error_message") == expected_message["error_message"]


def _setup_valid_s3_file(s3_client, bucket_name: str, key: str):
    """Helper function to setup a valid S3 file with correct SHA256 metadata."""
    import hashlib
    test_content = b'mock dataset content for validation'
    expected_sha256 = hashlib.sha256(test_content).hexdigest()
    
    s3_client.put_object(
        Bucket=bucket_name,
        Key=key,
        Body=test_content,
        Metadata={'source-sha256': expected_sha256}
    )


def _setup_corrupt_s3_file(s3_client, bucket_name: str, key: str):
    """Helper function to setup a corrupt S3 file with wrong SHA256 metadata."""
    test_content = b'mock dataset content'

    s3_client.put_object(
        Bucket=bucket_name,
        Key=key,
        Body=test_content,
        Metadata={'source-sha256': 'wrong_hash_value'}
    )


def test_get_uv_venv_path_from_returns_project_local_venv():
    """The uv venv path for a project is its project-local `.venv/` directory."""
    from dataset_validator.main import get_uv_venv_path_from

    assert get_uv_venv_path_from(Path("/x/y")) == str(Path("/x/y") / ".venv")


def test_apply_external_validator_falls_back_to_uv_venv(monkeypatch):
    """When the venv env var is unset, the validator subprocess is invoked via
    the project-local uv venv (`<project>/.venv/bin/python`) rather than the old
    `poetry env info` lookup. The Batch container always sets `*_VALIDATOR_VENV`,
    so this fallback is the local-dev path and is otherwise unexercised."""
    from dataset_validator.main import apply_external_validator

    root = Path("/fake/project")
    # Ensure both env vars are unset so the default script path + uv venv
    # fallback branches are exercised.
    monkeypatch.delenv("TEST_VALIDATOR_SCRIPT", raising=False)
    monkeypatch.delenv("TEST_VALIDATOR_VENV", raising=False)

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(
            stdout=json.dumps({"valid": True, "errors": [], "warnings": []}),
            stderr="",
            returncode=0,
        )

    monkeypatch.setattr("dataset_validator.main.subprocess.run", fake_run)

    report = apply_external_validator(
        Path("/data/file.h5ad"),
        script_path_var="TEST_VALIDATOR_SCRIPT",
        venv_path_var="TEST_VALIDATOR_VENV",
        get_default_root_path=lambda: root,
        default_package_name="pkg",
        validator_name="test validator",
    )

    assert report.valid is True
    assert captured["cmd"][0] == f"{root}/.venv/bin/python"
    assert captured["cmd"][1] == str(root / "src" / "pkg" / "main.py")
    assert captured["cmd"][2] == "/data/file.h5ad"
