import os
import time
import pytest
import subprocess
import tempfile
from pathlib import Path


@pytest.fixture(scope="module", autouse=True)
def dataset_validator_container():
    """Build and run the dataset-validator Docker container for testing."""
    image_name = "hca-dataset-validator:test"
    
    # Teardown logic to ensure container is stopped/removed and clean up test artifacts
    def teardown():
        # Stop and remove any test containers
        subprocess.run(["docker", "stop", "dataset-validator-test"], capture_output=True)
        subprocess.run(["docker", "rm", "dataset-validator-test"], capture_output=True)
        
        # Remove any temporary containers that might have been created during tests
        result = subprocess.run(["docker", "ps", "-a", "--filter", f"ancestor={image_name}", "-q"], 
                              capture_output=True, text=True)
        if result.stdout.strip():
            container_ids = result.stdout.strip().split('\n')
            for container_id in container_ids:
                subprocess.run(["docker", "rm", "-f", container_id], capture_output=True)
        
        # Clean up any dangling volumes or networks created during testing
        subprocess.run(["docker", "system", "prune", "-f", "--volumes"], capture_output=True)
    
    teardown()  # Clean up before starting (in case of leftovers)
    
    # Build the container first - need to run from project root
    project_root = Path(__file__).parent.parent.parent.parent
    build_result = subprocess.run([
        "docker", "build", 
        "-f", "deployment/dataset-validator/Dockerfile",
        "-t", image_name,
        "."
    ], capture_output=True, text=True, cwd=project_root)
    
    if build_result.returncode != 0:
        pytest.fail(f"Docker build failed: {build_result.stderr}")
    
    yield image_name
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


def test_docker_metadata_coverage_schema_loads(dataset_validator_container):
    """Verify the metadata_coverage module + LinkML schema YAMLs resolve inside
    the container. Catches gaps the unit tests miss because they run in the dev
    venv: missing schema/*.yaml files in /app/hca_validation/, missing
    linkml_runtime in the main venv, etc.
    """
    result = subprocess.run([
        "docker", "run", "--rm", "--entrypoint", "python",
        dataset_validator_container,
        "-c",
        "from hca_validation.metadata_coverage import compute_metadata_coverage, SCHEMA_NAME; "
        "from hca_validation.schema_utils import load_schemaview, coverage_classes; "
        "sv = load_schemaview(); "
        "print(f'{SCHEMA_NAME}|{sv.schema.version}|{\",\".join(coverage_classes(sv))}')"
    ], capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, f"stderr: {result.stderr}"
    schema_name, version, classes = result.stdout.strip().split("|")
    assert schema_name == "tier_1"
    assert version  # version pulled from LinkML schema
    assert set(classes.split(",")) >= {"Dataset", "Donor", "Sample"}


def test_docker_subprocess_validator_imports_resolve(dataset_validator_container):
    """The HCA schema validator runs in a separate venv invoked as a script
    subprocess by the dataset-validator. Its top-level `from hca_schema_validator
    import HCAValidator` must resolve to the installed PyPI package, NOT to a
    sibling /app/hca_schema_validator/ wrapper dir.

    Regression guard for two PYTHONPATH bugs we hit on dev:
      1. PYTHONPATH=/app exposing /app/hca_schema_validator/ as the package.
      2. PYTHONPATH ending in `:` adding cwd (/app) to sys.path implicitly.

    Invokes the validator as a script (mirrors production: `subprocess.run(
    [venv/bin/python, /app/hca_schema_validator/main.py, file])`). Uses a
    deliberately-invalid file so the validator's expected error path runs
    quickly and the JSON output proves the imports resolved cleanly.
    """
    # Invoke with no args. The script raises `Exception("Missing command line
    # argument for file path")` AFTER its top-level imports complete — so that
    # specific error message in stderr proves the imports resolved correctly.
    # If the imports were broken (the PYTHONPATH bug), stderr would contain
    # `ImportError` from line 4 (`from hca_schema_validator import HCAValidator`)
    # and the missing-arg check would never run.
    result = subprocess.run([
        "docker", "run", "--rm",
        "--entrypoint", "/opt/venvs/hca-schema-validator/bin/python",
        dataset_validator_container,
        "/app/hca_schema_validator/main.py"
    ], capture_output=True, text=True, timeout=30)

    assert result.returncode != 0  # script raises on missing argv
    assert "ImportError" not in result.stderr, (
        f"schema validator subprocess could not import its own package: {result.stderr}"
    )
    assert "Missing command line argument" in result.stderr, (
        f"expected post-import argv check; got: {result.stderr}"
    )
