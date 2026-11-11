import json
import os
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
import pytest
from aws_guard import AwsHostRefused, is_aws_host
from moto import mock_s3, mock_sns

TESTS_DIR = Path(__file__).parent
SNS_HOST = "sns.us-east-1.amazonaws.com"
PUBLISH_UNMOCKED = (
    "import boto3; boto3.client('sns').publish(TopicArn='arn:aws:sns:us-east-1:123456789012:t', Message='m')"
)


def _take_hosts(log: Path) -> list[str]:
    """Read the hosts the guard logged, then remove the log so this test's own teardown check passes."""
    hosts = [json.loads(line)["host"] for line in log.read_text().splitlines()]
    log.unlink()
    return hosts


@pytest.mark.parametrize(
    "host, expected",
    [
        (SNS_HOST, True),
        ("test-bucket.s3.amazonaws.com", True),
        ("S3.AMAZONAWS.COM.", True),
        ("s3.cn-north-1.amazonaws.com.cn", True),
        ("s3.dualstack.us-east-1.api.aws", True),
        ("169.254.169.254", True),
        ("localhost", False),
        ("127.0.0.1", False),
        ("amazonaws.com.example.org", False),
        ("notamazonaws.com", False),
    ],
)
def test_is_aws_host(host, expected):
    assert is_aws_host(host) is expected


def test_local_lookups_pass():
    assert socket.getaddrinfo("localhost", 80)


def test_an_aws_lookup_is_refused_and_logged(aws_guard_log):
    with pytest.raises(AwsHostRefused, match=SNS_HOST):
        socket.getaddrinfo(SNS_HOST, 443)
    assert _take_hosts(aws_guard_log) == [SNS_HOST]


def test_the_refusal_passes_through_except_exception_handlers(aws_guard_log):
    from dataset_validator.main import create_failure_message, publish_validation_result

    message = create_failure_message({}, "test", datetime.now(timezone.utc))
    with pytest.raises(AwsHostRefused):  # publish_validation_result catches every Exception
        publish_validation_result(message, "arn:aws:sns:us-east-1:123456789012:t")
    assert _take_hosts(aws_guard_log) == [SNS_HOST]


def test_calls_moto_answers_are_not_refused(aws_guard_log):
    with mock_s3(), mock_sns():
        s3 = boto3.client("s3")
        s3.create_bucket(Bucket="guard-test")
        s3.put_object(Bucket="guard-test", Key="k", Body=b"x")
        assert s3.get_object(Bucket="guard-test", Key="k")["Body"].read() == b"x"
        sns = boto3.client("sns")
        sns.publish(TopicArn=sns.create_topic(Name="t")["TopicArn"], Message="m")
    assert not aws_guard_log.exists()


def test_a_child_process_lookup_is_refused_and_logged(aws_guard_log):
    result = subprocess.run([sys.executable, "-c", PUBLISH_UNMOCKED], capture_output=True, text=True)
    assert result.returncode != 0
    assert "AwsHostRefused" in result.stderr
    assert _take_hosts(aws_guard_log) == [SNS_HOST]


def test_a_test_that_reaches_aws_fails_even_when_its_assertions_pass(pytester):
    shutil.copy(TESTS_DIR / "conftest.py", pytester.path)
    shutil.copy(TESTS_DIR / "aws_guard.py", pytester.path)
    shutil.copytree(TESTS_DIR / "aws_guard_site", pytester.path / "aws_guard_site")
    pytester.makepyfile(
        test_inner=f"""
        import subprocess, sys
        import boto3

        def test_swallows_the_refusal():
            try:
                boto3.client("sns").publish(TopicArn="arn:aws:sns:us-east-1:123456789012:t", Message="m")
            except BaseException:
                pass

        def test_ignores_a_child_that_reached_aws():
            subprocess.run([sys.executable, "-c", {PUBLISH_UNMOCKED!r}], capture_output=True)

        def test_reaches_nothing():
            pass
        """
    )
    result = pytester.runpytest_subprocess("-p", "no:cacheprovider")
    result.assert_outcomes(passed=3, errors=2)
    result.stdout.fnmatch_lines(["*The test looked up an AWS host*", f'*"host": "{SNS_HOST}"*'])


def test_proxy_variables_are_cleared():
    from conftest import PROXY_VARS

    assert "HTTPS_PROXY" in PROXY_VARS and "https_proxy" in PROXY_VARS
    assert not [name for name in PROXY_VARS if name in os.environ]
