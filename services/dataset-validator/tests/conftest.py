import os
from pathlib import Path

import aws_guard
import pytest

pytest_plugins = ["pytester"]

# Fake credentials and no config files, so boto3 can never load a real profile from the machine running the tests.
FAKE_AWS_ENV = {
    "AWS_CONFIG_FILE": "/dev/null",
    "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_EC2_METADATA_DISABLED": "true",
}
GUARD_SITE = Path(__file__).parent / "aws_guard_site"


def pytest_configure(config):
    aws_guard.install()


# Through a proxy, only the proxy's host is looked up, so aws_guard would never see the AWS host.
PROXY_VARS = [name for base in ("http_proxy", "https_proxy", "all_proxy") for name in (base, base.upper())]


@pytest.fixture(autouse=True)
def fake_aws_credentials(monkeypatch):
    for name in ["AWS_PROFILE", *PROXY_VARS]:
        monkeypatch.delenv(name, raising=False)
    for name, value in FAKE_AWS_ENV.items():
        monkeypatch.setenv(name, value)


@pytest.fixture(autouse=True)
def aws_guard_log(monkeypatch, tmp_path_factory):
    """Fail the test if it, or any Python process it starts, looked up an AWS host.

    The check reads the log after the test, so it holds even when the code under test caught the refusal.
    """
    log = tmp_path_factory.mktemp("aws_guard") / "lookups.jsonl"
    monkeypatch.setenv(aws_guard.LOG_ENV, str(log))
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(filter(None, [str(GUARD_SITE), os.environ.get("PYTHONPATH")])))
    yield log
    if log.exists():
        pytest.fail(f"The test looked up an AWS host; mock the call with moto:\n{log.read_text()}", pytrace=False)
