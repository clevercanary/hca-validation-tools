import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

# The handler's own imports, plus the ones validation makes lazily inside functions.
IMPORT_EVERYTHING_THE_LAMBDA_LOADS = """
import entry_sheet_validator_lambda.handler
import gspread
import googleapiclient.discovery
import googleapiclient.errors
import hca_validation.validator
from hca_validation.schema_utils import load_schemaview
load_schemaview().imports_closure()
"""


def test_lambda_imports_with_read_only_home(tmp_path):
    # Lambda's filesystem is read-only outside /tmp. This makes $HOME, the XDG and pystow directories and the
    # working directory read-only; it can't make site-packages read-only, so a write next to a module goes unseen.
    read_only = tmp_path / "read-only"
    read_only.mkdir()
    read_only.chmod(0o555)
    assert not os.access(read_only, os.W_OK), "directory is writable (running as root?), so the test can't fail"
    redirects = ("XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "PYSTOW_HOME")
    env = {
        **os.environ,
        "HOME": str(read_only / "home"),
        **{name: str(read_only / name.lower()) for name in redirects},
        "PYTHONPATH": str(SRC),
    }
    result = subprocess.run(
        [sys.executable, "-c", IMPORT_EVERYTHING_THE_LAMBDA_LOADS],
        env=env,
        cwd=read_only,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
