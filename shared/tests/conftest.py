#!/usr/bin/env python

"""Shared test configuration for HCA validation tools."""

import sys
from pathlib import Path

import pytest

# Add the src directory to the Python path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))


@pytest.fixture(scope="module")
def schemaview():
    """Shared across the module because `class_induced_slots` is the expensive part —
    linkml_runtime memoizes it per SchemaView instance, so a fresh instance per test
    re-pays roughly 40ms per class. Mirrors the fixture in the dataset-validator's
    coverage tests. Imported here, not at module level, so a broken linkml-runtime fails
    test_dependency_imports rather than the whole suite at collection."""
    from hca_validation.schema_utils.schema_utils import load_schemaview

    return load_schemaview()
