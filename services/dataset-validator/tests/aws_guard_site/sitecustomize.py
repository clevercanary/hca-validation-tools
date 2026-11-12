"""Install aws_guard in every Python process a test starts; conftest puts this folder first on PYTHONPATH."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("aws_guard", Path(__file__).resolve().parent.parent / "aws_guard.py")
assert _spec is not None and _spec.loader is not None
_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_guard)
_guard.install()
