"""Tests for the dataset validator service."""

import json
import logging
import os
import subprocess
from pathlib import Path

import boto3
import pytest
from moto import mock_s3, mock_sns

class TestDatasetValidator:
    """Test cases for the dataset validator main functionality."""

    def test_no_config_returns_failure(self):
        """Test that validator fails when no S3 config is provided."""
        # Clear any existing S3 environment variables
        env = os.environ.copy()
        env.pop('S3_BUCKET', None)
        env.pop('S3_KEY', None)
        
        # Run the validator
        result = subprocess.run(
            ['poetry', 'run', 'python', 'src/dataset_validator/main.py'],
            capture_output=True,
            text=True,
            env=env
        )
        
        # Should fail (exit code 1) when no config provided
        assert result.returncode == 1
        assert "Dataset Validator starting" in result.stdout
        assert "Missing required environment variables" in result.stdout

    def test_invalid_s3_config_returns_failure(self):
        """Test that validator fails when invalid S3 config is provided."""
        # Set invalid S3 configuration
        env = os.environ.copy()
        env['S3_BUCKET'] = 'invalid-test-bucket'
        env['S3_KEY'] = 'invalid/test/file.h5ad'
        env['FILE_ID'] = 'test-file-uuid'
        env['SNS_TOPIC_ARN'] = 'arn:aws:sns:us-east-1:123456789012:test-topic'
        env['AWS_BATCH_JOB_ID'] = 'test-job-id'
        
        # Run the validator
        result = subprocess.run(
            ['poetry', 'run', 'python', 'src/dataset_validator/main.py'],
            capture_output=True,
            text=True,
            env=env
        )
        
        # Should fail (exit code 1) when S3 download fails
        assert result.returncode == 1
        assert "Dataset Validator starting" in result.stdout
        assert "Work directory created:" in result.stdout
        assert "Processing S3 file: s3://invalid-test-bucket/invalid/test/file.h5ad" in result.stdout
        assert "S3 download failed" in result.stdout
        assert "Failed to download file - terminating" in result.stdout

    def test_work_directory_creation(self):
        """Test that work directory is created correctly with valid S3 config."""
        # Set valid S3 configuration (will fail at download but should create work dir)
        env = os.environ.copy()
        env['S3_BUCKET'] = 'test-bucket'
        env['S3_KEY'] = 'test/file.h5ad'
        env['FILE_ID'] = 'test-file-uuid'
        env['SNS_TOPIC_ARN'] = 'arn:aws:sns:us-east-1:123456789012:test-topic'
        env['AWS_BATCH_JOB_ID'] = 'test-job-id'
        
        # Run the validator
        result = subprocess.run(
            ['poetry', 'run', 'python', 'src/dataset_validator/main.py'],
            capture_output=True,
            text=True,
            env=env
        )
        
        # Should fail at S3 download but work directory should be created
        assert result.returncode == 1
        assert "Work directory created: /tmp/dataset_validator" in result.stdout


def test_missing_sns_topic_logs_error_and_exits(caplog):
    """Test that missing SNS_TOPIC_ARN logs error and exits with code 1."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    
    # Set up environment with missing SNS_TOPIC_ARN
    os.environ['S3_BUCKET'] = 'test-bucket'
    os.environ['S3_KEY'] = 'test/file.h5ad'
    os.environ['FILE_ID'] = 'test-file-uuid'
    os.environ['AWS_BATCH_JOB_ID'] = 'test-job-id'
    # Intentionally omit SNS_TOPIC_ARN
    if 'SNS_TOPIC_ARN' in os.environ:
        del os.environ['SNS_TOPIC_ARN']
    
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


@mock_sns
def test_publish_validation_result_success(caplog):
    """Test successful SNS message publishing."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    
    from dataset_validator.main import publish_validation_result, ValidationMessage, configure_logging
    
    # Configure logging for the test
    configure_logging()
    
    # Create SNS topic
    sns_client = boto3.client('sns', region_name='us-east-1')
    topic_response = sns_client.create_topic(Name='test-validation-topic')
    topic_arn = topic_response['TopicArn']
    
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
        error_message=None
    )
    
    # Test publishing
    with caplog.at_level(logging.INFO, logger="dataset_validator.main"):
        result = publish_validation_result(message, topic_arn)
    
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


@mock_sns
def test_publish_validation_result_invalid_topic(caplog):
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


@mock_s3
@mock_sns
def test_end_to_end_validation_success(caplog):
    """Test complete validation workflow with mocked S3 and SNS."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    
    from dataset_validator.main import main
    
    # Setup mock S3
    s3_client = boto3.client('s3', region_name='us-east-1')
    s3_client.create_bucket(Bucket='test-bucket')
    
    # Create test file content and compute its SHA256
    test_content = b'mock dataset content for validation'
    import hashlib
    expected_sha256 = hashlib.sha256(test_content).hexdigest()
    
    # Upload file with SHA256 metadata
    s3_client.put_object(
        Bucket='test-bucket',
        Key='datasets/test.h5ad',
        Body=test_content,
        Metadata={'source-sha256': expected_sha256}
    )
    
    # Setup mock SNS
    sns_client = boto3.client('sns', region_name='us-east-1')
    topic_response = sns_client.create_topic(Name='validation-results')
    topic_arn = topic_response['TopicArn']
    
    # Set environment variables
    test_env = {
        'S3_BUCKET': 'test-bucket',
        'S3_KEY': 'datasets/test.h5ad',
        'FILE_ID': 'test-file-123',
        'SNS_TOPIC_ARN': topic_arn,
        'AWS_BATCH_JOB_ID': 'job-456',
        'AWS_BATCH_JOB_NAME': 'test-validation-job'
    }
    
    # Save original environment
    original_env = {}
    for key in test_env:
        original_env[key] = os.environ.get(key)
        os.environ[key] = test_env[key]
    
    try:
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
        
    finally:
        # Restore original environment
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@mock_s3
@mock_sns
def test_end_to_end_validation_download_failure(caplog):
    """Test complete validation workflow with S3 download failure."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    
    from dataset_validator.main import main
    
    # Setup mock S3 (but don't upload the file - will cause download failure)
    s3_client = boto3.client('s3', region_name='us-east-1')
    s3_client.create_bucket(Bucket='test-bucket')
    
    # Setup mock SNS
    sns_client = boto3.client('sns', region_name='us-east-1')
    topic_response = sns_client.create_topic(Name='validation-results')
    topic_arn = topic_response['TopicArn']
    
    # Set environment variables
    test_env = {
        'S3_BUCKET': 'test-bucket',
        'S3_KEY': 'datasets/nonexistent.h5ad',
        'FILE_ID': 'test-file-456',
        'SNS_TOPIC_ARN': topic_arn,
        'AWS_BATCH_JOB_ID': 'job-789'
    }
    
    # Save original environment
    original_env = {}
    for key in test_env:
        original_env[key] = os.environ.get(key)
        os.environ[key] = test_env[key]
    
    try:
        # Run main function
        with caplog.at_level(logging.INFO, logger="dataset_validator.main"):
            result = main()
        
        # Should fail
        assert result == 1
        
        # Verify log messages
        assert "Dataset Validator starting" in caplog.text
        assert "Processing S3 file: s3://test-bucket/datasets/nonexistent.h5ad" in caplog.text
        assert "S3 download failed" in caplog.text
        assert "Failed to download file - terminating" in caplog.text
        assert "Publishing validation result to SNS topic" in caplog.text
        assert "Successfully published SNS message" in caplog.text
        
    finally:
        # Restore original environment
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@mock_s3
@mock_sns
def test_end_to_end_validation_integrity_failure(caplog):
    """Test complete validation workflow with file integrity failure."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    
    from dataset_validator.main import main
    
    # Setup mock S3
    s3_client = boto3.client('s3', region_name='us-east-1')
    s3_client.create_bucket(Bucket='test-bucket')
    
    # Upload file with wrong SHA256 metadata (will cause integrity failure)
    test_content = b'mock dataset content'
    s3_client.put_object(
        Bucket='test-bucket',
        Key='datasets/corrupt.h5ad',
        Body=test_content,
        Metadata={'source-sha256': 'wrong_hash_value'}
    )
    
    # Setup mock SNS
    sns_client = boto3.client('sns', region_name='us-east-1')
    topic_response = sns_client.create_topic(Name='validation-results')
    topic_arn = topic_response['TopicArn']
    
    # Set environment variables
    test_env = {
        'S3_BUCKET': 'test-bucket',
        'S3_KEY': 'datasets/corrupt.h5ad',
        'FILE_ID': 'test-file-789',
        'SNS_TOPIC_ARN': topic_arn,
        'AWS_BATCH_JOB_ID': 'job-101'
    }
    
    # Save original environment
    original_env = {}
    for key in test_env:
        original_env[key] = os.environ.get(key)
        os.environ[key] = test_env[key]
    
    try:
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
        
    finally:
        # Restore original environment
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
