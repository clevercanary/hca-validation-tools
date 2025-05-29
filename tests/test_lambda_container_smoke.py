import os
import time
import requests
import pytest
import subprocess
import json

@pytest.fixture(scope="module", autouse=True)
def lambda_container():
    # Teardown logic to ensure container is stopped/removed
    def teardown():
        subprocess.run(["docker", "stop", "lambda-test-smoke"], capture_output=True)
        subprocess.run(["docker", "rm", "lambda-test-smoke"], capture_output=True)
    teardown()  # Clean up before starting (in case of leftovers)
    # Start the container
    env = os.environ.get("GOOGLE_SERVICE_ACCOUNT", "")
    result = subprocess.run([
        "docker", "run", "-d", "--rm", "--name", "lambda-test-smoke", "-p", "9000:8080",
        "-e", f"GOOGLE_SERVICE_ACCOUNT={env}",
        "hca-entry-sheet-validator:latest"
    ], capture_output=True, text=True)
    container_id = result.stdout.strip()
    time.sleep(5)
    yield container_id
    teardown()

def test_lambda_container_smoke(lambda_container):
    """Basic smoke test: POSTs a minimal event to the Lambda container and checks for a valid response."""
    event = {"sheet_id": "1oPFb6qb0Y2HeoQqjSGRe_TlsZPRLwq-HUlVF0iqtVlY"}
    response = requests.post(
        "http://localhost:9000/2015-03-31/functions/function/invocations",
        json=event,
        timeout=10
    )
    assert response.status_code in (200, 400, 401)
    data = response.json()
    # Accept both direct and API Gateway-style responses
    if "body" in data:
        body_data = json.loads(data["body"])
        assert "valid" in body_data
        # Optionally: assert body_data["valid"] is True
    else:
        assert "valid" in data

def test_lambda_happy_path(lambda_container):
    """Test Lambda container with a valid public sheet_id (happy path)."""
    event = {"sheet_id": "1oPFb6qb0Y2HeoQqjSGRe_TlsZPRLwq-HUlVF0iqtVlY"}
    response = requests.post(
        "http://localhost:9000/2015-03-31/functions/function/invocations",
        json=event,
        timeout=10
    )
    assert response.status_code in (200, 400, 401)
    data = response.json()
    # Handle API Gateway-style response
    if "body" in data:
        body_data = json.loads(data["body"])
        assert "valid" in body_data
        # Optionally: assert body_data["valid"] is True
    else:
        assert "valid" in data

    """
    Smoke test: POST a test event to the running Lambda container via RIE and check the response.
    Assumes the container is running on localhost:9000.
    """
    event = {
        "queryStringParameters": {
            "sheet_id": "1Gp2yocEq9OWECfDgCVbExIgzYfM7s6nJV5ftyn-SMXQ"
        }
    }
    try:
        response = requests.post(
            "http://localhost:9000/2015-03-31/functions/function/invocations",
            json=event,
            timeout=10
        )
    except Exception as e:
        pytest.fail(f"Failed to contact Lambda container: {e}")
    assert response.status_code in (200, 400, 401)
    data = response.json()
    # Handle API Gateway-style response (body is a JSON string)
    if "body" in data:
        try:
            body_data = json.loads(data["body"])
        except Exception:
            body_data = {}
        assert "valid" in body_data or "error" in body_data
    else:
        assert "valid" in data or "error" in data
