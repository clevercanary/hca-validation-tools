import json
import os
import subprocess
import time

import pytest
import requests


@pytest.fixture(scope="module", autouse=True)
def lambda_container():
    # Teardown logic to ensure container is stopped/removed
    def teardown():
        subprocess.run(["docker", "stop", "lambda-test-smoke"], capture_output=True)
        subprocess.run(["docker", "rm", "lambda-test-smoke"], capture_output=True)

    teardown()  # Clean up before starting (in case of leftovers)
    # Start the container
    env = os.environ.get("GOOGLE_SERVICE_ACCOUNT", "")
    result = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            "lambda-test-smoke",
            "-p",
            "9000:8080",
            "-e",
            f"GOOGLE_SERVICE_ACCOUNT={env}",
            "hca-entry-sheet-validator:latest",
        ],
        capture_output=True,
        text=True,
    )
    container_id = result.stdout.strip()
    time.sleep(5)
    yield container_id
    teardown()


def test_lambda_container_smoke(lambda_container):
    """Basic smoke: the container boots and returns a well-formed response (a `valid` result or an `error`).

    Deliberately credential-agnostic — this only proves the container serves the endpoint; the credentialed
    happy path is asserted in test_lambda_happy_path.
    """
    event = {"sheet_id": "1oPFb6qb0Y2HeoQqjSGRe_TlsZPRLwq-HUlVF0iqtVlY"}
    response = requests.post("http://localhost:9000/2015-03-31/functions/function/invocations", json=event, timeout=10)
    assert response.status_code in (200, 400, 401)
    data = response.json()
    # Accept both direct and API Gateway-style (body is a JSON string) responses.
    body_data = json.loads(data["body"]) if "body" in data else data
    assert "valid" in body_data or "error" in body_data


def test_lambda_happy_path(lambda_container):
    """Happy path: with credentials present, a valid public sheet_id must return 200 and a boolean `valid`.

    Without credentials the read cannot authenticate, so the happy path is untestable and the test skips
    rather than passing on an auth failure (the weakness this replaced).
    """
    if not os.environ.get("GOOGLE_SERVICE_ACCOUNT"):
        pytest.skip("GOOGLE_SERVICE_ACCOUNT not set (load the root .env); happy path needs credentials")

    event = {"sheet_id": "1oPFb6qb0Y2HeoQqjSGRe_TlsZPRLwq-HUlVF0iqtVlY"}
    response = requests.post("http://localhost:9000/2015-03-31/functions/function/invocations", json=event, timeout=10)
    assert response.status_code == 200
    data = response.json()
    # Handle both direct and API Gateway-style (body is a JSON string) responses.
    body_data = json.loads(data["body"]) if "body" in data else data
    assert isinstance(body_data.get("valid"), bool)
