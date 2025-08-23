#!/usr/bin/env python3
"""
Dataset Validator - AWS Batch Job
Main entry point for dataset validation processing.
"""

import os
import sys
from pathlib import Path
import boto3
from botocore.exceptions import ClientError


def create_work_directory(work_dir: str = "/tmp/dataset_validator") -> Path:
    """Create and return the work directory path."""
    work_path = Path(work_dir)
    work_path.mkdir(parents=True, exist_ok=True)
    return work_path


def download_s3_file(bucket: str, key: str, local_path: Path) -> bool:
    """
    Download a file from S3 to the local work directory.
    
    Args:
        bucket: S3 bucket name
        key: S3 object key
        local_path: Local file path to save the downloaded file
        
    Returns:
        True if download successful, False otherwise
    """
    try:
        s3_client = boto3.client('s3')
        s3_client.download_file(bucket, key, str(local_path))
        print(f"Successfully downloaded s3://{bucket}/{key} to {local_path}")
        return True
    except ClientError as e:
        print(f"Error downloading s3://{bucket}/{key}: {e}")
        return False
    except Exception as e:
        print(f"Unexpected error downloading s3://{bucket}/{key}: {e}")
        return False


def main():
    """Main entry point for the dataset validator."""
    print("Dataset Validator - Hello World!")
    
    # Create work directory
    work_dir = create_work_directory()
    print(f"Work directory: {work_dir}")
    
    # Get S3 parameters from environment variables (for AWS Batch)
    bucket = os.environ.get('S3_BUCKET')
    key = os.environ.get('S3_KEY')
    
    if bucket and key:
        print(f"Downloading file from s3://{bucket}/{key}")
        local_file = work_dir / Path(key).name
        success = download_s3_file(bucket, key, local_file)
        if success:
            print(f"File ready for validation: {local_file}")
            # TODO: Add actual validation logic here
        else:
            print("Failed to download file")
            return 1
    else:
        print("No S3_BUCKET and S3_KEY environment variables provided")
        print("Running in demo mode")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
