"""
Tests for file cleanup functionality in dataset validator.
"""
import logging
import os
import sys
import tempfile
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

# Add src directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dataset_validator.main import cleanup_files


def test_cleanup_files_success(caplog):
    """Test successful cleanup of work directory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Create work directory with files
        work_dir = temp_path / "work"
        work_dir.mkdir()
        (work_dir / "downloaded_file.h5ad").write_text("test content")
        (work_dir / "nested_file.txt").write_text("nested content")
        
        # Verify directory and files exist before cleanup
        assert work_dir.exists()
        assert (work_dir / "downloaded_file.h5ad").exists()
        assert (work_dir / "nested_file.txt").exists()
        
        # Capture logs from the dataset_validator.main logger
        with caplog.at_level(logging.INFO, logger="dataset_validator.main"):
            cleanup_files(work_dir)
        
        # Verify entire work directory is removed
        assert not work_dir.exists()
        
        # Check log messages
        assert "Successfully removed work directory" in caplog.text


def test_cleanup_files_nonexistent_directory(caplog):
    """Test cleanup with non-existent directory (should not error)."""
    nonexistent_dir = Path("/tmp/nonexistent_dir")
    
    # Ensure directory doesn't exist
    assert not nonexistent_dir.exists()
    
    # Capture logs from the dataset_validator.main logger
    with caplog.at_level(logging.INFO, logger="dataset_validator.main"):
        cleanup_files(nonexistent_dir)
    
    # Should log that no directory to clean up
    assert "No work directory to clean up" in caplog.text


def test_cleanup_files_none_parameter(caplog):
    """Test cleanup with None parameter."""
    with caplog.at_level(logging.INFO, logger="dataset_validator.main"):
        cleanup_files(None)
    
    # Should log that no directory to clean up
    assert "No work directory to clean up" in caplog.text


def test_cleanup_files_directory_removal_error(caplog):
    """Test cleanup when directory removal fails."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        work_dir = temp_path / "work"
        work_dir.mkdir()
        
        # Mock shutil.rmtree to raise an exception
        with patch('dataset_validator.main.shutil.rmtree', side_effect=OSError("Directory busy")), \
             caplog.at_level(logging.WARNING, logger="dataset_validator.main"):
            cleanup_files(work_dir)
        
        # Check warning was logged
        assert "Failed to remove work directory" in caplog.text
        assert "Directory busy" in caplog.text
        assert "validation result unaffected" in caplog.text


def test_cleanup_integration_with_main_function():
    """Test that cleanup is called during main() execution."""
    # This test verifies cleanup is integrated into the main flow
    with patch('dataset_validator.main.cleanup_files') as mock_cleanup, \
         patch('dataset_validator.main.validate_environment') as mock_validate:
        
        # Mock environment validation to fail early (missing vars)
        mock_validate.return_value = ({}, ['S3_BUCKET=None'])
        
        from dataset_validator.main import main
        
        # Run main function
        exit_code = main()
        
        # Should exit with failure due to missing env vars
        assert exit_code == 1
        
        # Cleanup should still be called (in finally block) with work_dir=None
        mock_cleanup.assert_called_once_with(None)


def test_cleanup_preserves_exit_code(caplog):
    """Test that cleanup errors don't change the main function exit code."""
    with patch('dataset_validator.main.validate_environment') as mock_validate, \
         patch('dataset_validator.main.download_s3_file', side_effect=Exception("Download failed")), \
         patch('shutil.rmtree', side_effect=OSError("Permission denied")), \
         patch('pathlib.Path.exists', return_value=True), \
         patch('tempfile.mkdtemp', return_value='/tmp/test_work_dir'):
        
        # Mock environment validation to succeed so we get to file download
        mock_validate.return_value = ({
            'bucket': 'test-bucket',
            'key': 'test-key.h5ad',
            'file_id': 'test-file-123',
            'sns_topic_arn': 'arn:aws:sns:us-east-1:123456789012:test-topic',
            'batch_job_id': 'test-job-456',
            'batch_job_name': 'test-job-name'
        }, [])
        
        from dataset_validator.main import main
        
        # Capture logs to verify cleanup warning is logged
        with caplog.at_level(logging.WARNING):
            exit_code = main()
        
        # Should still exit with 1 (download failure), not affected by cleanup error
        assert exit_code == 1
        
        # Verify cleanup warning was logged
        assert any("Failed to remove work directory" in record.message for record in caplog.records)
