import ast
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
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


def test_docker_smoke_containers_have_no_network():
    tree = ast.parse((Path(__file__).parent / "test_docker_smoke.py").read_text())
    runs = [
        [element.value for element in node.elts if isinstance(element, ast.Constant)]
        for node in ast.walk(tree)
        if isinstance(node, ast.List) and [getattr(e, "value", None) for e in node.elts[:2]] == ["docker", "run"]
    ]
    assert runs, "expected docker run commands in test_docker_smoke.py"
    for run in runs:
        flag = run.index("--network") if "--network" in run else None
        assert flag is not None and run[flag + 1] == "none", f"docker run without --network none: {run}"


SMOKE_TEST_COUNT = 6


@pytest.mark.parametrize(
    ("env", "outcomes"),
    [
        ({}, {"skipped": SMOKE_TEST_COUNT}),
        ({"RUN_DOCKER_TESTS": "1"}, {"errors": SMOKE_TEST_COUNT}),
        ({"RUN_DOCKER_TESTS": "true"}, {"skipped": SMOKE_TEST_COUNT}),
        ({"CI": "true"}, {"errors": SMOKE_TEST_COUNT}),
    ],
)
def test_docker_smoke_tests_run_only_when_opted_in_or_on_ci(pytester, monkeypatch, env, outcomes):
    shutil.copy(Path(__file__).parent / "test_docker_smoke.py", pytester.path)
    # Raises from the fixture's first step, so a run that isn't skipped errors before it reaches Docker
    pytester.makepyfile(
        docker_cleanup="""
        IMAGE_NAME = "hca-dataset-validator:test"

        def remove_test_artifacts(image_name=IMAGE_NAME):
            raise AssertionError("the stub stands in for Docker")
        """
    )
    for name in ["RUN_DOCKER_TESTS", "CI"]:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    # A child process, so the skip condition is read from this environment, not the one the outer run imported it under
    result = pytester.runpytest_subprocess("-p", "no:cacheprovider")
    result.assert_outcomes(**outcomes)
