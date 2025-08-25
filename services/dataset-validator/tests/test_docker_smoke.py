import os
import time
import pytest
import subprocess
import tempfile
import json
from pathlib import Path


@pytest.fixture(scope="module", autouse=True)
def dataset_validator_container():
    """Build and run the dataset-validator Docker container for testing."""
    # Teardown logic to ensure container is stopped/removed
    def teardown():
        subprocess.run(["docker", "stop", "dataset-validator-test"], capture_output=True)
        subprocess.run(["docker", "rm", "dataset-validator-test"], capture_output=True)
    
    teardown()  # Clean up before starting (in case of leftovers)
    
    # Build the container first - need to run from project root
    project_root = Path(__file__).parent.parent.parent.parent
    build_result = subprocess.run([
        "docker", "build", 
        "-f", "deployment/dataset-validator/Dockerfile",
        "-t", "hca-dataset-validator:test",
        "."
    ], capture_output=True, text=True, cwd=project_root)
    
    if build_result.returncode != 0:
        pytest.fail(f"Docker build failed: {build_result.stderr}")
    
    yield "hca-dataset-validator:test"
    teardown()


def test_docker_container_help(dataset_validator_container):
    """Test that the Docker container can run and show help/usage."""
    result = subprocess.run([
        "docker", "run", "--rm", 
        dataset_validator_container,
        "--help"
    ], capture_output=True, text=True, timeout=30)
    
    # Should exit with non-zero (missing required env vars) and show error message
    assert result.returncode != 0
    assert "Dataset Validator starting" in result.stdout
    assert "Missing required environment variables" in result.stdout


def test_docker_container_missing_env_vars(dataset_validator_container):
    """Test that the Docker container fails gracefully with missing environment variables."""
    result = subprocess.run([
        "docker", "run", "--rm",
        dataset_validator_container
    ], capture_output=True, text=True, timeout=30)
    
    # Should exit with non-zero due to missing required environment variables
    assert result.returncode != 0
    # Should mention missing environment variables (check stdout where logs go)
    assert any(env_var in result.stdout for env_var in ["S3_BUCKET", "S3_KEY", "FILE_ID", "SNS_TOPIC_ARN"])
    assert "Missing required environment variables" in result.stdout


def test_docker_container_with_mock_env_vars(dataset_validator_container):
    """Test that the Docker container starts properly with required environment variables."""
    # Create a temporary directory for any potential file operations
    with tempfile.TemporaryDirectory() as temp_dir:
        result = subprocess.run([
            "docker", "run", "--rm",
            "-e", "S3_BUCKET=test-bucket",
            "-e", "S3_KEY=test-key.h5ad", 
            "-e", "FILE_ID=test-file-123",
            "-e", "SNS_TOPIC_ARN=arn:aws:sns:us-east-1:123456789012:test-topic",
            "-e", "AWS_BATCH_JOB_ID=test-job-456",
            "-e", "AWS_ACCESS_KEY_ID=fake",
            "-e", "AWS_SECRET_ACCESS_KEY=fake",
            "-e", "AWS_DEFAULT_REGION=us-east-1",
            dataset_validator_container
        ], capture_output=True, text=True, timeout=30)
        
        # Should fail due to AWS credentials/S3 access, but should start properly
        # and show our expected log messages before failing
        assert "Dataset Validator starting" in result.stderr or "Dataset Validator starting" in result.stdout
        
        # Should attempt to process the S3 file
        expected_s3_url = "s3://test-bucket/test-key.h5ad"
        assert expected_s3_url in result.stderr or expected_s3_url in result.stdout


def test_docker_container_python_imports(dataset_validator_container):
    """Test that all required Python packages are available in the container."""
    result = subprocess.run([
        "docker", "run", "--rm",
        dataset_validator_container,
        "-c", "import boto3, hashlib, json, logging, os, tempfile, dataclasses; print('All imports successful')"
    ], capture_output=True, text=True, timeout=30, 
    # Override entrypoint to run python directly
    )
    
    # Run with python -c instead of the main script
    result = subprocess.run([
        "docker", "run", "--rm", "--entrypoint", "python",
        dataset_validator_container,
        "-c", "import boto3, hashlib, json, logging, os, tempfile; from dataclasses import dataclass; print('All imports successful')"
    ], capture_output=True, text=True, timeout=30)
    
    assert result.returncode == 0
    assert "All imports successful" in result.stdout


def test_docker_container_file_structure(dataset_validator_container):
    """Test that the application files are correctly placed in the container."""
    result = subprocess.run([
        "docker", "run", "--rm", "--entrypoint", "ls",
        dataset_validator_container,
        "-la", "/app/dataset_validator/"
    ], capture_output=True, text=True, timeout=30)
    
    assert result.returncode == 0
    assert "main.py" in result.stdout
    assert "__init__.py" in result.stdout or "__pycache__" in result.stdout
