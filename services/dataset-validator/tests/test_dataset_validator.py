"""Tests for the dataset validator service."""

import os
import subprocess
import pytest
from pathlib import Path


class TestDatasetValidator:
    """Test cases for the dataset validator main functionality."""

    def test_no_config_returns_success_demo_mode(self):
        """Test that validator runs in demo mode when no S3 config is provided."""
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
        
        # Should succeed (exit code 0) in demo mode
        assert result.returncode == 0
        assert "Dataset Validator - Hello World!" in result.stdout
        assert "Work directory:" in result.stdout
        assert "No S3_BUCKET and S3_KEY environment variables provided" in result.stdout
        assert "Running in demo mode" in result.stdout

    def test_invalid_s3_config_returns_failure(self):
        """Test that validator fails when invalid S3 config is provided."""
        # Set invalid S3 configuration
        env = os.environ.copy()
        env['S3_BUCKET'] = 'invalid-test-bucket'
        env['S3_KEY'] = 'invalid/test/file.h5ad'
        
        # Run the validator
        result = subprocess.run(
            ['poetry', 'run', 'python', 'src/dataset_validator/main.py'],
            capture_output=True,
            text=True,
            env=env
        )
        
        # Should fail (exit code 1) when S3 download fails
        assert result.returncode == 1
        assert "Dataset Validator - Hello World!" in result.stdout
        assert "Work directory:" in result.stdout
        assert "Downloading file from s3://invalid-test-bucket/invalid/test/file.h5ad" in result.stdout
        assert "Error downloading" in result.stdout
        assert "Failed to download file" in result.stdout

    def test_work_directory_creation(self):
        """Test that work directory is created correctly."""
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
        
        # Should succeed and create work directory
        assert result.returncode == 0
        assert "Work directory: /tmp/dataset_validator" in result.stdout
        
        # Verify work directory exists
        work_dir = Path("/tmp/dataset_validator")
        assert work_dir.exists()
        assert work_dir.is_dir()
