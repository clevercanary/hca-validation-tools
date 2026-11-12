import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def test_handler_imports_with_read_only_home(tmp_path):
    # Lambda's filesystem is read-only outside /tmp; an import that writes under $HOME crashes the function.
    read_only = tmp_path / "read-only"
    read_only.mkdir()
    read_only.chmod(0o555)
    env = {**os.environ, "HOME": str(read_only / "home"), "PYTHONPATH": str(SRC)}
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import entry_sheet_validator_lambda.handler"],
            env=env,
            capture_output=True,
            text=True,
        )
    finally:
        read_only.chmod(0o755)
    assert result.returncode == 0, result.stderr
