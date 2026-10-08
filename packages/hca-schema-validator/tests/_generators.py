"""Loading the reference-table generators that live outside this package.

The reference-table generators live in ``scripts/`` at the repository root
rather than in this package: they are run by hand and their output is committed.
They are files rather than an importable package, so a test has to load one by
path -- and since they import a sibling module (``_ensembl``), the directory
holding them has to be on the path first. Run normally, Python does that itself;
loading by path does not.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"


def load_script(name: str):
    """Import a generator from ``scripts/`` by name, sibling imports and all."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
