import pytest

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


@pytest.fixture(autouse=True)
def fake_aws_credentials(monkeypatch):
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    for name, value in FAKE_AWS_ENV.items():
        monkeypatch.setenv(name, value)
