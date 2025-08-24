"""Test for missing SHA256 metadata scenario."""

import json
import logging
import os
from pathlib import Path

import boto3
import pytest
from moto import mock_s3, mock_sns


@mock_s3
@mock_sns
def test_end_to_end_validation_missing_sha256_metadata(caplog):
    """Test complete validation workflow with missing SHA256 metadata."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    
    from dataset_validator.main import main
    
    # Setup mock S3
    s3_client = boto3.client('s3', region_name='us-east-1')
    s3_client.create_bucket(Bucket='test-bucket')
    
    # Upload file WITHOUT SHA256 metadata
    test_content = b'mock dataset content'
    s3_client.put_object(
        Bucket='test-bucket',
        Key='datasets/no-metadata.h5ad',
        Body=test_content
        # No Metadata parameter - missing source-sha256
    )
    
    # Setup mock SNS
    sns_client = boto3.client('sns', region_name='us-east-1')
    topic_response = sns_client.create_topic(Name='validation-results')
    topic_arn = topic_response['TopicArn']
    
    # Set environment variables
    test_env = {
        'S3_BUCKET': 'test-bucket',
        'S3_KEY': 'datasets/no-metadata.h5ad',
        'FILE_ID': 'test-file-999',
        'SNS_TOPIC_ARN': topic_arn,
        'AWS_BATCH_JOB_ID': 'job-999'
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
        assert "No source-sha256 metadata found" in caplog.text
        assert "No source SHA256 metadata found - cannot validate file integrity - terminating" in caplog.text
        assert "Publishing validation result to SNS topic" in caplog.text
        assert "Successfully published SNS message" in caplog.text
        
    finally:
        # Restore original environment
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
