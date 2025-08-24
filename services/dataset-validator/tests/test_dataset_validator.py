"""Tests for the dataset validator service."""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, Any

import boto3
import pytest
from moto import mock_s3, mock_sns


@pytest.fixture
def mock_aws():
    """Fixture that provides mocked AWS services (S3 and SNS)."""
    with mock_s3(), mock_sns():
        # Create S3 client and bucket
        s3_client = boto3.client('s3', region_name='us-east-1')
        s3_client.create_bucket(Bucket='test-bucket')
        
        # Create SNS client and topic
        sns_client = boto3.client('sns', region_name='us-east-1')
        topic_response = sns_client.create_topic(Name='test-validation-topic')
        topic_arn = topic_response['TopicArn']
        
        yield {
            's3_client': s3_client,
            'sns_client': sns_client,
            'topic_arn': topic_arn,
            'bucket_name': 'test-bucket'
        }


@pytest.fixture
def base_env_vars():
    """Fixture that provides base environment variables for testing."""
    return {
        'S3_BUCKET': 'test-bucket',
        'S3_KEY': 'test/file.h5ad',
        'FILE_ID': 'test-file-uuid',
        'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-1:123456789012:test-topic',
        'AWS_BATCH_JOB_ID': 'test-job-id',
        'AWS_BATCH_JOB_NAME': 'test-job'
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
                'AWS_BATCH_JOB_ID': 'test-job-id'
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
                'AWS_BATCH_JOB_ID': 'test-job-id'
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
        
        # Clear specified variables
        for var in test_case["clear_vars"]:
            env.pop(var, None)
            
        # Set test-specific variables
        env.update(test_case["env_vars"])
        
        # Run the validator
        result = subprocess.run(
            ['poetry', 'run', 'python', 'src/dataset_validator/main.py'],
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
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    
    # Set up environment with missing SNS_TOPIC_ARN
    test_env = base_env_vars.copy()
    del test_env['SNS_TOPIC_ARN']  # Remove SNS topic to test missing variable
    env_manager['set'](test_env)
    
    # Import after setting environment to ensure fresh logger config
    from dataset_validator.main import main
    
    # Capture logs from the specific logger
    with caplog.at_level(logging.ERROR, logger="dataset_validator.main"):
        result = main()
    
    # Should exit with code 1
    assert result == 1
    
    # Should log the missing environment variable error
    assert "Missing required environment variables" in caplog.text
    assert "SNS_TOPIC_ARN=None" in caplog.text


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
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    
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
    
    # For success case, verify message serialization
    if test_case["name"] == "success":
        message_json = message.to_json()
        parsed_message = json.loads(message_json)
        assert parsed_message == test_case["message_data"]


@pytest.mark.parametrize("test_case", [
    {
        "name": "success",
        "description": "Test complete validation workflow with successful validation",
        "s3_key": "datasets/test.h5ad",
        "file_id": "test-file-123",
        "batch_job_id": "job-456",
        "batch_job_name": "test-validation-job",
        "setup_s3": lambda s3_client, bucket_name: _setup_valid_s3_file(s3_client, bucket_name, "datasets/test.h5ad"),
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
            "error_message": None
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
            "batch_job_name": None
        }
    },
    {
        "name": "integrity_failure",
        "description": "Test complete validation workflow with file integrity failure",
        "s3_key": "datasets/corrupt.h5ad",
        "file_id": "test-file-789",
        "batch_job_id": "job-101",
        "batch_job_name": None,
        "setup_s3": lambda s3_client, bucket_name: _setup_corrupt_s3_file(s3_client, bucket_name, "datasets/corrupt.h5ad"),
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
            "batch_job_name": None
        }
    }
], ids=lambda x: x["name"])
def test_end_to_end_validation_scenarios(caplog, mock_aws, env_manager, test_case):
    """Parameterized test for end-to-end validation scenarios."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    
    from dataset_validator.main import main
    
    # Setup S3 file based on test case
    test_case["setup_s3"](mock_aws['s3_client'], mock_aws['bucket_name'])
    
    # Set environment variables using fixture
    test_env = {
        'S3_BUCKET': mock_aws['bucket_name'],
        'S3_KEY': test_case["s3_key"],
        'FILE_ID': test_case["file_id"],
        'SNS_TOPIC_ARN': mock_aws['topic_arn'],
        'AWS_BATCH_JOB_ID': test_case["batch_job_id"]
    }
    if test_case["batch_job_name"]:
        test_env['AWS_BATCH_JOB_NAME'] = test_case["batch_job_name"]
    
    env_manager['set'](test_env)
    
    # Run main function
    with caplog.at_level(logging.INFO, logger="dataset_validator.main"):
        result = main()
    
    # Verify exit code
    assert result == test_case["expected_exit_code"]
    
    # Verify expected log messages
    for expected_log in test_case["expected_logs"]:
        assert expected_log in caplog.text
    
    # Verify SNS message content
    _validate_sns_message(mock_aws, caplog, test_case["expected_sns_message"])


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


def _validate_sns_message(mock_aws, caplog, expected_message):
    """Helper function to validate SNS message content using moto's internal API."""
    import json
    from moto.core import DEFAULT_ACCOUNT_ID
    from moto.sns import sns_backends
    
    # Get the SNS backend and retrieve sent notifications
    sns_backend = sns_backends[DEFAULT_ACCOUNT_ID]["us-east-1"]
    topic_arn = mock_aws['topic_arn']
    
    # Verify at least one message was published
    assert "Successfully published SNS message" in caplog.text
    
    # Get and parse the last published message
    message = _get_last_sns_message(sns_backend, topic_arn)
    
    # Validate key fields that use constants - these should fail if constants change
    assert message["status"] == expected_message["status"], f"Expected status '{expected_message['status']}', got '{message['status']}'"
    assert message["integrity_status"] == expected_message["integrity_status"], f"Expected integrity_status '{expected_message['integrity_status']}', got '{message['integrity_status']}'"
    assert message["file_id"] == expected_message["file_id"]
    assert message["batch_job_id"] == expected_message["batch_job_id"]
    assert message["batch_job_name"] == expected_message["batch_job_name"]
    
    # For success case, verify error_message is None
    if expected_message.get("error_message") is not None:
        assert message.get("error_message") == expected_message["error_message"]


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
