"""Tests for the dataset validator service."""

import os
import subprocess
import unittest
import logging
import pytest
from pathlib import Path


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
