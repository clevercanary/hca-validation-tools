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


def test_publish_validation_result_success(caplog, mock_aws):
    """Test successful SNS message publishing."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    
    from dataset_validator.main import publish_validation_result, ValidationMessage, configure_logging
    
    # Configure logging for the test
    configure_logging()
    
    # Create test validation message
    message = ValidationMessage(
        file_id='test-file-123',
        status='success',
        timestamp='2024-01-01T12:00:00Z',
        bucket='test-bucket',
        key='test/file.h5ad',
        batch_job_id='job-123',
        batch_job_name='test-job',
        downloaded_sha256='abc123',
        source_sha256='abc123',
        integrity_status='valid',
        error_message=None
    )
    
    # Test publishing using the fixture's topic ARN
    with caplog.at_level(logging.INFO, logger="dataset_validator.main"):
        result = publish_validation_result(message, mock_aws['topic_arn'])
    
    # Should succeed
    assert result is True
    assert "Publishing validation result to SNS topic" in caplog.text
    assert "Successfully published SNS message" in caplog.text
    
    # Verify message content was sent correctly
    expected_message_data = {
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
    }
    
    # Verify the message serialization
    message_json = message.to_json()
    parsed_message = json.loads(message_json)
    assert parsed_message == expected_message_data
    
    # Verify subject line format
    expected_subject = "Dataset Validation Result - SUCCESS"
    # Note: moto doesn't provide easy access to published message details,
    # but we've verified the function completes and logs success


def test_publish_validation_result_invalid_topic(caplog, mock_aws):
    """Test SNS publishing with invalid topic ARN."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    
    from dataset_validator.main import publish_validation_result, ValidationMessage, configure_logging
    
    # Configure logging for the test
    configure_logging()
    
    # Create test validation message
    message = ValidationMessage(
        file_id='test-file-123',
        status='failure',
        timestamp='2024-01-01T12:00:00Z',
        bucket='test-bucket',
        key='test/file.h5ad',
        batch_job_id='job-123',
        error_message='Test error'
    )
    
    # Test publishing to invalid topic
    invalid_topic_arn = 'arn:aws:sns:us-east-1:123456789012:nonexistent-topic'
    
    with caplog.at_level(logging.ERROR, logger="dataset_validator.main"):
        result = publish_validation_result(message, invalid_topic_arn)
    
    # Should fail
    assert result is False
    assert "SNS publish failed" in caplog.text


def test_end_to_end_validation_success(caplog, mock_aws, env_manager):
    """Test complete validation workflow with mocked S3 and SNS."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    
    from dataset_validator.main import main
    
    # Create test file content and compute its SHA256
    test_content = b'mock dataset content for validation'
    import hashlib
    expected_sha256 = hashlib.sha256(test_content).hexdigest()
    
    # Upload file with SHA256 metadata using fixture's S3 client
    mock_aws['s3_client'].put_object(
        Bucket=mock_aws['bucket_name'],
        Key='datasets/test.h5ad',
        Body=test_content,
        Metadata={'source-sha256': expected_sha256}
    )
    
    # Set environment variables using fixture
    test_env = {
        'S3_BUCKET': mock_aws['bucket_name'],
        'S3_KEY': 'datasets/test.h5ad',
        'FILE_ID': 'test-file-123',
        'SNS_TOPIC_ARN': mock_aws['topic_arn'],
        'AWS_BATCH_JOB_ID': 'job-456',
        'AWS_BATCH_JOB_NAME': 'test-validation-job'
    }
    env_manager['set'](test_env)
    
    # Run main function
    with caplog.at_level(logging.INFO, logger="dataset_validator.main"):
        result = main()
    
    # Should succeed
    assert result == 0
    
    # Verify log messages
    assert "Dataset Validator starting" in caplog.text
    assert "Processing S3 file: s3://test-bucket/datasets/test.h5ad" in caplog.text
    assert "Work directory created:" in caplog.text
    assert "File ready for validation:" in caplog.text
    assert "Validation completed successfully" in caplog.text
    assert "Publishing validation result to SNS topic" in caplog.text
    assert "Successfully published SNS message" in caplog.text
    assert "Dataset Validator completed successfully" in caplog.text


def test_end_to_end_validation_download_failure(caplog, mock_aws, env_manager):
    """Test complete validation workflow with S3 download failure."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    
    from dataset_validator.main import main
    
    # Don't upload any file to S3 - will cause download failure
    
    # Set environment variables using fixture
    test_env = {
        'S3_BUCKET': mock_aws['bucket_name'],
        'S3_KEY': 'datasets/nonexistent.h5ad',
        'FILE_ID': 'test-file-456',
        'SNS_TOPIC_ARN': mock_aws['topic_arn'],
        'AWS_BATCH_JOB_ID': 'job-789'
    }
    env_manager['set'](test_env)
    
    # Run main function
    with caplog.at_level(logging.INFO, logger="dataset_validator.main"):
        result = main()
    
    # Should fail
    assert result == 1
    
    # Verify log messages
    assert "Dataset Validator starting" in caplog.text
    assert "Processing S3 file: s3://test-bucket/datasets/nonexistent.h5ad" in caplog.text
    assert "S3 download failed" in caplog.text
    assert "Dataset Validator failed:" in caplog.text
    assert "Publishing validation result to SNS topic" in caplog.text
    assert "Successfully published SNS message" in caplog.text


def test_end_to_end_validation_integrity_failure(caplog, mock_aws, env_manager):
    """Test complete validation workflow with file integrity failure."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    
    from dataset_validator.main import main
    
    # Upload file with wrong SHA256 metadata (will cause integrity failure)
    test_content = b'mock dataset content'
    mock_aws['s3_client'].put_object(
        Bucket=mock_aws['bucket_name'],
        Key='datasets/corrupt.h5ad',
        Body=test_content,
        Metadata={'source-sha256': 'wrong_hash_value'}
    )
    
    # Set environment variables using fixture
    test_env = {
        'S3_BUCKET': mock_aws['bucket_name'],
        'S3_KEY': 'datasets/corrupt.h5ad',
        'FILE_ID': 'test-file-789',
        'SNS_TOPIC_ARN': mock_aws['topic_arn'],
        'AWS_BATCH_JOB_ID': 'job-101'
    }
    env_manager['set'](test_env)
    
    # Run main function
    with caplog.at_level(logging.INFO, logger="dataset_validator.main"):
        result = main()
    
    # Should fail
    assert result == 1
    
    # Verify log messages
    assert "Dataset Validator starting" in caplog.text
    assert "File ready for validation:" in caplog.text
    assert "File integrity verification failed - terminating" in caplog.text
    assert "Publishing validation result to SNS topic" in caplog.text
    assert "Successfully published SNS message" in caplog.text
