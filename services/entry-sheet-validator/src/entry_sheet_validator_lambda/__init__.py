"""
HCA Entry Sheet validator Lambda function.

This module provides an AWS Lambda function for validating HCA entry sheets
in Google Sheets format using the HCA validation tools.
"""

from .handler import handler

__all__ = ["handler"]
