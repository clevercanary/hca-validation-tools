#!/usr/bin/env python3
"""
Dataset Validator - AWS Batch Job
Main entry point for dataset validation processing.
"""

import hashlib
import json
import logging
import os
import shutil
import sys
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import boto3
from botocore.exceptions import ClientError
import anndata
import pandas as pd
from cap_upload_validator import UploadValidator
from cap_upload_validator.errors import CapException, CapMultiException


# Environment variable constants
# Batch job variables
S3_BUCKET = 'S3_BUCKET'
S3_KEY = 'S3_KEY'
LOG_LEVEL = 'LOG_LEVEL'
FILE_ID = 'FILE_ID'
SNS_TOPIC_ARN = 'SNS_TOPIC_ARN'
AWS_BATCH_JOB_ID = 'AWS_BATCH_JOB_ID'
AWS_BATCH_JOB_NAME = 'AWS_BATCH_JOB_NAME'
AWS_DEFAULT_REGION = 'AWS_DEFAULT_REGION'
# Other variables
CELLXGENE_VALIDATOR_VENV = 'CELLXGENE_VALIDATOR_VENV'

# Status constants
STATUS_SUCCESS = 'success'
STATUS_FAILURE = 'failure'

# Integrity status constants
INTEGRITY_VALID = 'valid'
INTEGRITY_INVALID = 'invalid'
INTEGRITY_ERROR = 'error'


class JobContextFilter(logging.Filter):
    """Inject AWS Batch job context into each log record.

    In AWS Batch, the container environment is immutable for the lifetime of a job.
    We cache these values once at initialization for clarity and minimal overhead.
    """
    def __init__(self) -> None:
        super().__init__()
        self._job_id = os.environ.get(AWS_BATCH_JOB_ID, "unknown")
        # Prefer non-reserved name inside container
        self._job_name = os.environ.get('BATCH_JOB_NAME', "-")

    def filter(self, record: logging.LogRecord) -> bool:
        record.job_id = self._job_id
        record.job_name = self._job_name
        return True


@dataclass
class MetadataSummary:
    """Summary of metadata from a dataset file."""
    title: str
    assay: List[str]
    suspension_type: List[str]
    tissue: List[str]
    disease: List[str]
    cell_count: int

@dataclass
class ValidationToolReport:
    """Validation report and metadata of a run of an individual validation tool."""
    valid: bool
    errors: List[str]
    warnings: List[str]
    started_at: str
    finished_at: str

@dataclass
class ValidationMessage:
    """SNS message structure for validation results."""
    # Required fields
    file_id: str              # UUID from Tracker database
    status: str               # "success", "failure"
    timestamp: str            # ISO format timestamp (UTC)
    bucket: str               # S3 bucket name
    key: str                  # S3 object key
    batch_job_id: str         # Unique AWS Batch job ID for debugging
    
    # Optional fields
    batch_job_name: Optional[str] = None                 # Job definition name (for context)
    downloaded_sha256: Optional[str] = None              # SHA256 computed from downloaded file
    source_sha256: Optional[str] = None                  # SHA256 from S3 metadata
    integrity_status: Optional[str] = None               # "valid", "invalid", "error"
    metadata_summary: Optional[MetadataSummary] = None   # Metadata from the file
    tool_reports: Optional[                              # Reports for individual validation tools
        dict[str, ValidationToolReport]
    ] = None
    error_message: Optional[str] = None                  # Human-readable error description

    def to_json(self) -> str:
        """Convert to JSON string for SNS publishing."""
        return json.dumps(asdict(self), indent=2)


def configure_logging() -> logging.Logger:
    """Configure logging for CloudWatch compatibility."""
    # Get log level from environment variable (default to INFO)
    log_level = os.environ.get(LOG_LEVEL, 'INFO').upper()
    
    logger = logging.getLogger(__name__)
    logger.setLevel(getattr(logging, log_level))
    
    # Only add handlers if none exist (respects caplog handlers)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        # Enrich logs with Batch context
        handler.addFilter(JobContextFilter())
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] job_id=%(job_id)s job_name=%(job_name)s %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    # Set boto3 logging to WARNING to reduce noise
    logging.getLogger('boto3').setLevel(logging.WARNING)
    logging.getLogger('botocore').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    
    return logger


# Module-level logger
logger: logging.Logger = logging.getLogger(__name__)


def publish_validation_result(message: ValidationMessage, sns_topic_arn: str) -> bool:
    """
    Publish validation result to SNS topic.
    
    Args:
        message: ValidationMessage containing result data
        sns_topic_arn: ARN of the SNS topic to publish to
        
    Returns:
        True if published successfully, False otherwise
    """
    try:
        logger.info("Publishing validation result to SNS topic: %s", sns_topic_arn)
        
        # Create SNS client
        # Let boto3 resolve region from the environment/metadata
        sns_client = boto3.client('sns')
        
        # Publish message
        response = sns_client.publish(
            TopicArn=sns_topic_arn,
            Message=message.to_json(),
            Subject=f"Dataset Validation Result - {message.status.upper()}"
        )
        
        message_id = response.get('MessageId', 'unknown')
        logger.info("Successfully published SNS message: %s", message_id)
        return True
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_message = e.response.get('Error', {}).get('Message', str(e))
        logger.error("SNS publish failed [%s]: %s", error_code, error_message)
        return False
        
    except Exception as e:
        logger.error("Unexpected error publishing to SNS: %s", str(e))
        return False


def create_work_directory(work_dir: str = "/tmp/dataset_validator") -> Path:
    """Create and return the work directory path."""
    work_path = Path(work_dir)
    work_path.mkdir(parents=True, exist_ok=True)
    return work_path


def compute_sha256(file_path: Path) -> str:
    """
    Compute SHA256 hash of a file using streaming to handle large files efficiently.
    
    Args:
        file_path: Path to the file to hash
        
    Returns:
        Hexadecimal SHA256 hash string
    """
    logger.debug("Computing SHA256 for: %s", file_path)
    sha256_hash = hashlib.sha256()
    
    with open(file_path, "rb") as f:
        # Read file in 64KB chunks to handle large files efficiently
        for chunk in iter(lambda: f.read(65536), b""):
            sha256_hash.update(chunk)
    
    computed_hash = sha256_hash.hexdigest()
    logger.debug("Computed SHA256: %s", computed_hash)
    return computed_hash


def verify_file_integrity(file_path: Path, expected_sha256: str) -> bool:
    """
    Verify file integrity by comparing computed SHA256 with expected value.
    
    Args:
        file_path: Path to the file to verify
        expected_sha256: Expected SHA256 hash from S3 metadata
        
    Returns:
        True if hashes match, False otherwise
    """
    logger.info("Verifying file integrity: %s", file_path)
    computed_sha256 = compute_sha256(file_path)
    
    if computed_sha256.lower() == expected_sha256.lower():
        logger.info("File integrity verified successfully")
        return True
    else:
        logger.error("File integrity check failed - computed: %s, expected: %s", 
                    computed_sha256, expected_sha256)
        return False


def get_column_unique_values_if_present(df: pd.DataFrame, name: str, map_value=str):
    """
    Get unique values after applying a mapping function to a given column of a dataframe.

    Args:
        df: Dataframe to get values from
        name: Name of the dataframe column to get values from
        map_value: Function to apply to each value to get the value to be used in the result (defaults to `str`)
    
    Returns:
        Unique mapped values from the specified column
    """
    return list(df[name].map(map_value).unique()) if name in df else []


def read_metadata(file_path: Path) -> MetadataSummary:
    """
    Read metadata from an H5AD file and extract key biological annotations.
    
    This function opens an H5AD (AnnData) file in backed mode and extracts unique values
    from key observation columns to create a metadata summary. The file is automatically
    closed after reading to prevent resource leaks.
    
    Args:
        file_path: Path to the H5AD file to read metadata from
        
    Returns:
        MetadataSummary: A summary containing:
            - title: Title of the individual dataset
            - assay: List of unique assay types in the dataset
            - suspension_type: List of unique suspension types
            - tissue: List of unique tissue types
            - disease: List of unique disease conditions
            - cell_count: Total number of cells/observations in the dataset
            
    Raises:
        Exception: If the H5AD file cannot be read or required columns are missing
        
    Note:
        The file is opened in backed mode ('r') for memory efficiency and automatically
        closed in the finally block to ensure proper resource cleanup.
    """
    adata = None
    try:
        adata = anndata.io.read_h5ad(file_path, backed="r")
        title = adata.uns.get("title")
        return MetadataSummary(
            title=title if isinstance(title, str) else "",
            assay=get_column_unique_values_if_present(adata.obs, "assay"),
            suspension_type=get_column_unique_values_if_present(adata.obs, "suspension_type"),
            tissue=get_column_unique_values_if_present(adata.obs, "tissue"),
            disease=get_column_unique_values_if_present(adata.obs, "disease"),
            cell_count=adata.n_obs
        )
    except Exception as e:
        logger.error("Error reading metadata: %s", e)
        raise
    finally:
        if adata is not None:
            adata.file.close()


def apply_cap_validator(file_path: Path) -> ValidationToolReport:
    """
    Apply the CAP validator to the given file and create a validation report.

    Args:
        file_path: Path of the file to validate
    
    Returns:
        Validation report
    """
    started_at = datetime.now(timezone.utc)
    valid = False
    errors: List[str] = []
    try:
        uv = UploadValidator(str(file_path))
        uv.validate()
        valid = True
    except CapMultiException as multi_ex:
        errors.extend(str(e) for e in multi_ex.ex_list)
    except (Exception, CapException) as e:
        message = f"Encountered an unexpected error while calling CAP validator: {e}"
        logger.error(message)
        errors.append(message)
    finished_at = datetime.now(timezone.utc)
    return ValidationToolReport(
        valid=valid,
        errors=errors,
        warnings=[],
        started_at=started_at.isoformat(),
        finished_at=finished_at.isoformat()
    )


def apply_cellxgene_validator(file_path: Path) -> ValidationToolReport:
    """
    Apply the CELLxGENE validator to the given file and create a validation report.

    Args:
        file_path: Path of the file to validate

    Returns:
        Validation report
    """
    started_at = datetime.now(timezone.utc)

    # Determine path of CELLxGENE validator installation and script
    validator_path = Path(__file__).parent.parent.parent.parent / "cellxgene-validator"
    validator_script_path = validator_path / "src" / "cellxgene_validator" / "main.py"

    # Get CELLxGENE validator venv path from environment, if present
    venv_path = os.environ.get(CELLXGENE_VALIDATOR_VENV)

    # If environment variable is not present, get venv path via Poetry
    if venv_path is None:
        venv_result = subprocess.run(
            ["poetry", "env", "info", "--path"],
            cwd=validator_path,
            capture_output=True,
            text=True,
            check=True
        )
        venv_path = venv_result.stdout.strip()

    # Call validator and parse output
    validator_result = subprocess.run(
        [f"{venv_path}/bin/python", str(validator_script_path), str(file_path)],
        capture_output=True,
        text=True,
        check=True
    )
    validator_output = json.loads(validator_result.stdout)

    finished_at = datetime.now(timezone.utc)

    return ValidationToolReport(
        valid=validator_output["valid"],
        errors=validator_output["errors"],
        warnings=validator_output["warnings"],
        started_at=started_at.isoformat(),
        finished_at=finished_at.isoformat()
    )


def download_s3_file(bucket: str, key: str, local_path: Path) -> str | None:
    """
    Download a file from S3 to the local work directory and extract metadata.
    
    Args:
        bucket: S3 bucket name
        key: S3 object key
        local_path: Local file path to save the downloaded file
        
    Returns:
        Source SHA256 from S3 metadata, or None if not available
        
    Raises:
        ClientError: AWS S3 errors (permissions, missing files, etc.)
        Exception: Other errors (network, disk space, etc.)
    """
    logger.info("Starting download: s3://%s/%s", bucket, key)
    try:
        # Let boto3 resolve region from the environment/metadata
        s3_client = boto3.client('s3')
        
        # Get object metadata first
        response = s3_client.head_object(Bucket=bucket, Key=key)
        source_sha256 = response.get('Metadata', {}).get('source-sha256')
        
        # Download the file
        s3_client.download_file(bucket, key, str(local_path))
        logger.info("Successfully downloaded to %s", local_path)
        
        if source_sha256:
            logger.info("Source SHA256 from metadata: %s", source_sha256)
        else:
            logger.warning("No source-sha256 metadata found for s3://%s/%s", bucket, key)
        
        return source_sha256
    except ClientError as e:
        logger.error("S3 download failed: %s", e)
        raise
    except Exception as e:
        logger.error("Unexpected error downloading s3://%s/%s: %s", bucket, key, e)
        raise


def validate_environment() -> tuple[dict[str, str], list[str]]:
    """
    Validate required environment variables.
    
    Returns:
        Tuple of (env_vars dict, missing_vars list)
    """
    env_vars = {
        'bucket': os.environ.get(S3_BUCKET),
        'key': os.environ.get(S3_KEY),
        'file_id': os.environ.get(FILE_ID),
        'sns_topic_arn': os.environ.get(SNS_TOPIC_ARN),
        'batch_job_id': os.environ.get(AWS_BATCH_JOB_ID),
        # Read non-reserved job name if provided
        'batch_job_name': os.environ.get('BATCH_JOB_NAME')
    }
    
    # Check required variables (batch_job_name is optional; region is resolved by boto3)
    required_vars = ['bucket', 'key', 'file_id', 'sns_topic_arn', 'batch_job_id']
    var_name_mapping = {
        'bucket': 'S3_BUCKET',
        'key': 'S3_KEY',
        'file_id': 'FILE_ID',
        'sns_topic_arn': 'SNS_TOPIC_ARN',
        'batch_job_id': 'AWS_BATCH_JOB_ID'
    }
    missing_vars = []
    
    for var in required_vars:
        if not env_vars[var]:
            env_name = var_name_mapping[var]
            missing_vars.append(f"{env_name}={env_vars[var]}")
    
    return env_vars, missing_vars


def create_failure_message(env_vars: dict[str, str], error: str, start_time: datetime) -> ValidationMessage:
    """Create ValidationMessage for failure cases."""
    return ValidationMessage(
        file_id=env_vars.get('file_id') or "unknown",
        status=STATUS_FAILURE,
        timestamp=start_time.isoformat(),
        bucket=env_vars.get('bucket') or "unknown",
        key=env_vars.get('key') or "unknown",
        batch_job_id=env_vars.get('batch_job_id') or "unknown",
        batch_job_name=env_vars.get('batch_job_name'),
        error_message=error
    )


def cleanup_files(work_dir: Optional[Path] = None) -> None:
    """
    Clean up work directory after validation.
    
    This function attempts to remove the entire work directory (including downloaded files)
    but logs warnings if cleanup fails without affecting the validation result.
    
    Args:
        work_dir: Path to the work directory to remove
    """
    if work_dir and work_dir.exists():
        try:
            shutil.rmtree(work_dir)
            logger.info("Successfully removed work directory: %s", work_dir)
        except Exception as e:
            logger.warning("Failed to remove work directory %s: %s - validation result unaffected", work_dir, e)
    else:
        logger.info("No work directory to clean up")


def main() -> int:
    """Main entry point for the dataset validator."""
    configure_logging()
    
    # Initialize validation tracking variables
    start_time = datetime.now(timezone.utc)
    validation_message: Optional[ValidationMessage] = None
    exit_code = 1  # Default to failure
    work_dir: Optional[Path] = None
    
    try:
        logger.info("Dataset Validator starting")
        
        # Validate environment variables
        env_vars, missing_vars = validate_environment()
        
        if missing_vars:
            error_msg = f"Missing required environment variables: {', '.join(missing_vars)}"
            logger.error(error_msg)
            validation_message = create_failure_message(env_vars, error_msg, start_time)
            exit_code = 1
            return exit_code
        
        # Initialize validation message with basic info
        validation_message = ValidationMessage(
            file_id=env_vars['file_id'],
            status="in_progress",
            timestamp=start_time.isoformat(),
            bucket=env_vars['bucket'],
            key=env_vars['key'],
            batch_job_id=env_vars['batch_job_id'],
            batch_job_name=env_vars['batch_job_name']
        )
        
        logger.info("Processing S3 file: s3://%s/%s", env_vars['bucket'], env_vars['key'])
        
        # Create work directory
        work_dir = create_work_directory()
        logger.info("Work directory created: %s", work_dir)
        
        # Download file from S3
        local_file = work_dir / Path(env_vars['key']).name
        source_sha256 = download_s3_file(env_vars['bucket'], env_vars['key'], local_file)
        logger.info("File ready for validation: %s", local_file)
        
        # Check for SHA256 metadata - required for validation
        if not source_sha256:
            error_msg = "No source SHA256 metadata found - cannot validate file integrity"
            logger.error(error_msg + " - terminating")
            validation_message.status = STATUS_FAILURE
            validation_message.integrity_status = INTEGRITY_ERROR
            validation_message.error_message = error_msg
            exit_code = 1
            return exit_code
        
        # Compute downloaded file SHA256
        downloaded_sha256 = compute_sha256(local_file)
        validation_message.downloaded_sha256 = downloaded_sha256
        validation_message.source_sha256 = source_sha256
        
        # Verify file integrity
        if not verify_file_integrity(local_file, source_sha256):
            error_msg = "File integrity verification failed"
            logger.error(error_msg + " - terminating")
            validation_message.status = STATUS_FAILURE
            validation_message.integrity_status = INTEGRITY_INVALID
            validation_message.error_message = error_msg
            exit_code = 1
            return exit_code
        
        validation_message.integrity_status = INTEGRITY_VALID
        
        # Read metadata
        validation_message.metadata_summary = read_metadata(local_file)

        # Call CAP validator
        cap_validation_report = apply_cap_validator(local_file)

        # Add individual validation reports to message
        validation_message.tool_reports = {
            "cap": cap_validation_report
        }

        logger.info("Validation completed successfully")
        validation_message.status = STATUS_SUCCESS
        exit_code = 0
        
    except Exception as e:
        error_msg = f"Dataset Validator failed: {e}"
        logger.error(error_msg)
        
        # Update validation message if it exists, otherwise create minimal one
        if validation_message:
            validation_message.status = STATUS_FAILURE
            validation_message.error_message = error_msg
        else:
            # Use empty dict if env_vars doesn't exist yet
            empty_env_vars = {}
            validation_message = create_failure_message(empty_env_vars, error_msg, start_time)
        exit_code = 1
    
    finally:
        # Clean up work directory (includes downloaded files)
        cleanup_files(work_dir)
        
        # Always publish SNS message before exiting (if we have topic ARN)
        sns_topic_arn = env_vars.get('sns_topic_arn') if 'env_vars' in locals() else None
        if validation_message and sns_topic_arn:
            publish_success = publish_validation_result(validation_message, sns_topic_arn)
            if not publish_success:
                logger.warning("SNS publishing failed, but continuing with original exit code")
        
        if exit_code == 0:
            logger.info("Dataset Validator completed successfully")
        
        return exit_code


if __name__ == "__main__":
    sys.exit(main())
