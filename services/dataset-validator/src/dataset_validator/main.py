#!/usr/bin/env python3
"""
Dataset Validator - AWS Batch Job
Main entry point for dataset validation processing.
"""

import hashlib
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import ClientError

# Environment variable constants
S3_BUCKET = 'S3_BUCKET'
S3_KEY = 'S3_KEY'
LOG_LEVEL = 'LOG_LEVEL'
FILE_ID = 'FILE_ID'
SNS_TOPIC_ARN = 'SNS_TOPIC_ARN'
AWS_BATCH_JOB_ID = 'AWS_BATCH_JOB_ID'
AWS_BATCH_JOB_NAME = 'AWS_BATCH_JOB_NAME'


@dataclass
class ValidationMessage:
    """SNS message structure for validation results."""
    # Required fields
    file_id: str              # UUID from Tracker database
    status: str               # "success", "download_failure", "integrity_failure", "validation_failure"
    timestamp: str            # ISO format timestamp (UTC)
    bucket: str               # S3 bucket name
    key: str                  # S3 object key
    batch_job_id: str         # Unique AWS Batch job ID for debugging
    
    # Optional fields
    batch_job_name: Optional[str] = None       # Job definition name (for context)
    downloaded_sha256: Optional[str] = None    # SHA256 computed from downloaded file
    source_sha256: Optional[str] = None        # SHA256 from S3 metadata
    error_message: Optional[str] = None        # Human-readable error description

    def to_json(self) -> str:
        """Convert to JSON string for SNS publishing."""
        return json.dumps(asdict(self), indent=2)


def configure_logging():
    """Configure logging for CloudWatch compatibility."""
    # Get log level from environment variable (default to INFO)
    log_level = os.environ.get(LOG_LEVEL, 'INFO').upper()
    
    logger = logging.getLogger(__name__)
    logger.setLevel(getattr(logging, log_level))
    
    # Only add handlers if none exist (respects caplog handlers)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    # Set boto3 logging to WARNING to reduce noise
    logging.getLogger('boto3').setLevel(logging.WARNING)
    logging.getLogger('botocore').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    
    return logger


# Initialize logger (will be set in main())
logger = None


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


def download_s3_file(bucket: str, key: str, local_path: Path) -> tuple[bool, str | None]:
    """
    Download a file from S3 to the local work directory and extract metadata.
    
    Args:
        bucket: S3 bucket name
        key: S3 object key
        local_path: Local file path to save the downloaded file
        
    Returns:
        Tuple of (success: bool, source_sha256: str | None)
    """
    logger.info(f"Starting download: s3://{bucket}/{key}")
    try:
        s3_client = boto3.client('s3')
        
        # Get object metadata first
        response = s3_client.head_object(Bucket=bucket, Key=key)
        source_sha256 = response.get('Metadata', {}).get('source-sha256')
        
        # Download the file
        s3_client.download_file(bucket, key, str(local_path))
        logger.info(f"Successfully downloaded to {local_path}")
        
        if source_sha256:
            logger.info(f"Source SHA256 from metadata: {source_sha256}")
        else:
            logger.warning(f"No source-sha256 metadata found for s3://{bucket}/{key}")
        
        return True, source_sha256
    except ClientError as e:
        logger.error(f"S3 download failed: {e}")
        return False, None
    except Exception as e:
        logger.error(f"Unexpected error downloading s3://{bucket}/{key}: {e}")
        return False, None


def main():
    """Main entry point for the dataset validator."""
    global logger
    logger = configure_logging()
    
    # Initialize validation tracking variables
    start_time = datetime.now(timezone.utc)
    validation_message = None
    exit_code = 1  # Default to failure
    
    try:
        logger.info("Dataset Validator starting")
        
        # Get required environment variables (for AWS Batch)
        bucket = os.environ.get(S3_BUCKET)
        key = os.environ.get(S3_KEY)
        file_id = os.environ.get(FILE_ID)
        sns_topic_arn = os.environ.get(SNS_TOPIC_ARN)
        batch_job_id = os.environ.get(AWS_BATCH_JOB_ID)
        
        # Fail early if required environment variables are missing
        missing_vars = []
        if not bucket:
            missing_vars.append(f"S3_BUCKET={bucket}")
        if not key:
            missing_vars.append(f"S3_KEY={key}")
        if not file_id:
            missing_vars.append(f"FILE_ID={file_id}")
        if not sns_topic_arn:
            missing_vars.append(f"SNS_TOPIC_ARN={sns_topic_arn}")
        if not batch_job_id:
            missing_vars.append(f"AWS_BATCH_JOB_ID={batch_job_id}")
        
        if missing_vars:
            error_msg = f"Missing required environment variables: {', '.join(missing_vars)}"
            logger.error(error_msg)
            
            # Create validation message for missing env vars (minimal info available)
            validation_message = ValidationMessage(
                file_id=file_id or "unknown",
                status="failure",
                timestamp=start_time.isoformat(),
                bucket=bucket or "unknown",
                key=key or "unknown",
                batch_job_id=batch_job_id or "unknown",
                error_message=error_msg
            )
            exit_code = 1
        else:
            # Initialize validation message with basic info
            validation_message = ValidationMessage(
                file_id=file_id,
                status="in_progress",
                timestamp=start_time.isoformat(),
                bucket=bucket,
                key=key,
                batch_job_id=batch_job_id,
                batch_job_name=os.environ.get('AWS_BATCH_JOB_NAME')
            )
            
            logger.info("Processing S3 file: s3://%s/%s", bucket, key)
            
            # Create work directory
            work_dir = create_work_directory()
            logger.info("Work directory created: %s", work_dir)
            
            # Download file from S3
            local_file = work_dir / Path(key).name
            success, source_sha256 = download_s3_file(bucket, key, local_file)
            
            if success:
                logger.info("File ready for validation: %s", local_file)
                
                # Compute downloaded file SHA256
                downloaded_sha256 = compute_sha256(local_file)
                validation_message.downloaded_sha256 = downloaded_sha256
                validation_message.source_sha256 = source_sha256
                
                # Verify file integrity if SHA256 metadata is available
                if source_sha256:
                    if not verify_file_integrity(local_file, source_sha256):
                        error_msg = "File integrity verification failed"
                        logger.error(error_msg + " - terminating")
                        validation_message.status = "failure"
                        validation_message.error_message = error_msg
                        exit_code = 1
                    else:
                        # TODO: Add actual validation logic here
                        logger.info("Validation completed successfully")
                        validation_message.status = "success"
                        exit_code = 0
                else:
                    logger.warning("Skipping integrity verification - no source SHA256 metadata")
                    # TODO: Add actual validation logic here
                    logger.info("Validation completed successfully")
                    validation_message.status = "success"
                    exit_code = 0
            else:
                error_msg = "Failed to download file"
                logger.error(error_msg + " - terminating")
                validation_message.status = "failure"
                validation_message.error_message = error_msg
                exit_code = 1
        
    except Exception as e:
        error_msg = f"Dataset Validator failed: {e}"
        logger.error(error_msg)
        
        # Update validation message if it exists, otherwise create minimal one
        if validation_message:
            validation_message.status = "failure"
            validation_message.error_message = error_msg
        else:
            validation_message = ValidationMessage(
                file_id="unknown",
                status="failure",
                timestamp=start_time.isoformat(),
                bucket="unknown",
                key="unknown",
                batch_job_id="unknown",
                error_message=error_msg
            )
        exit_code = 1
    
    finally:
        # Always publish SNS message before exiting (if we have topic ARN)
        if validation_message and sns_topic_arn:
            publish_success = publish_validation_result(validation_message, sns_topic_arn)
            if not publish_success:
                logger.warning("SNS publishing failed, but continuing with original exit code")
        
        if exit_code == 0:
            logger.info("Dataset Validator completed successfully")
        
        return exit_code


if __name__ == "__main__":
    sys.exit(main())
