#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Shared test configuration for HCA validation tools."""

import pytest
import sys
from pathlib import Path

# Add the src directory to the Python path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))
