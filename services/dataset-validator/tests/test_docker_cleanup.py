from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from docker_cleanup import IMAGE_NAME, remove_test_artifacts


def test_remove_test_artifacts_removes_only_the_test_containers_and_image():
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(stdout="abc123\ndef456\n" if cmd[1] == "ps" else "", returncode=0)

    with patch("docker_cleanup.subprocess.run", fake_run):
        remove_test_artifacts()

    assert calls == [
        ["docker", "ps", "-a", "--filter", f"ancestor={IMAGE_NAME}", "-q"],
        ["docker", "rm", "-f", "abc123", "def456"],
        ["docker", "rmi", "-f", IMAGE_NAME],
    ]


def test_docker_smoke_tests_never_prune_the_machine():
    tests_dir = Path(__file__).parent
    for name in ["docker_cleanup.py", "test_docker_smoke.py"]:
        assert "prune" not in (tests_dir / name).read_text(), f"{name} must clean up only what the tests created"
