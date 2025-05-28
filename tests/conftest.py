#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Pytest configuration file for HCA validation tools tests.
"""
import pytest

# Register custom pytest marks
def pytest_configure(config):
    """Register custom pytest marks."""
    config.addinivalue_line(
        "markers", "integration: mark tests that require external services"
    )
