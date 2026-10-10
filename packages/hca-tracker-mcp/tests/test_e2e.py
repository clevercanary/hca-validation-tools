"""End-to-end tests through the FastMCP client, against the fake tracker."""

import json
import os
import shutil
import time

import pytest
import pytest_asyncio
from fastmcp.client import Client

from hca_tracker_client.daemon import shutdown
from hca_tracker_client.testing import FakeTracker
from hca_tracker_mcp.server import mcp

requires_aria2 = pytest.mark.skipif(shutil.which("aria2c") is None, reason="aria2c is not installed")

TOOLS = {
    "list_atlases",
    "list_integrated_objects",
    "list_source_datasets",
    "get_atlas",
    "get_validation_report",
    "start_download",
    "download_status",
    "cancel_download",
    "list_downloads",
    "delete_download",
    "check_environment",
}


@pytest.fixture
def tracker(tmp_path, monkeypatch):
    """A fake tracker with one atlas and one file, and the server configured for it."""
    with FakeTracker() as fake:
        atlas_id = fake.add_atlas(
            "gut",
            "gut",
            1,
            0,
            published=True,
            leads=[{"name": "Ann Lead", "email": "ann@example.org"}, {"name": "No Account", "email": "x@example.org"}],
            sourceDatasetCount=1,
            componentAtlasCount=1,
        )
        fake.add_user("Ann Lead", "ann@example.org", last_login="2026-03-01T10:00:00.000Z")
        data = tmp_path / "bucket" / "gut"
        data.parent.mkdir()
        data.write_bytes(os.urandom(500_000))
        fake.add_file(atlas_id, "gut.h5ad", data, integrity="pending")
        fake.add_file(
            atlas_id,
            "src.h5ad",
            data,
            kind="source",
            validationStatus="completed",
            reports={
                "cap": {"valid": True},
                "hcaSchema": {"valid": False, "errors": ["ERROR: e1"], "warnings": ["w1", "w2", "w3"]},
            },
            used_by=["gut.h5ad"],
        )
        fake.add_file(
            atlas_id,
            "broken.h5ad",
            data,
            kind="source",
            validationStatus="job_failed",
            validationErrorMessage="Dataset Validator failed: file signature not found",
        )
        cache = tmp_path / "cache"
        monkeypatch.chdir(tmp_path)  # no stray .env
        monkeypatch.setenv("HCA_TRACKER_URL", fake.url)
        monkeypatch.setenv("HCA_TRACKER_API_TOKEN", fake.token)
        monkeypatch.setenv("HCA_TRACKER_CACHE_DIR", str(cache))
        monkeypatch.setattr("hca_tracker_client.checks.free_bytes", lambda path: 10**12)
        yield fake
        shutdown(cache)


@pytest_asyncio.fixture
async def client():
    async with Client(mcp) as c:
        yield c


OUTPUTS: list[str] = []


async def _call(client, tool, args=None) -> dict:
    result = await client.call_tool(tool, args or {})
    assert not result.is_error, f"{tool} returned error: {result.content}"
    text = result.content[0].text
    OUTPUTS.append(text)
    return json.loads(text)


@pytest.mark.asyncio
async def test_registered_tools(client):
    tools = {tool.name: tool for tool in await client.list_tools()}
    assert set(tools) == TOOLS
    params = tools["list_integrated_objects"].inputSchema["properties"]
    assert "1 = v1.x" in params["generation"]["description"]
    assert "list_atlases" in params["network"]["description"]
    assert "confirm" not in tools["start_download"].inputSchema["properties"]
    # The validator names the schema offers are the client's; a validator added there must be added here.
    from hca_tracker_client.status import VALIDATORS

    validator = tools["get_validation_report"].inputSchema["properties"]["validator"]
    offered = next(option["enum"] for option in validator["anyOf"] if "enum" in option)
    assert offered == list(VALIDATORS.values())


@pytest.mark.asyncio
async def test_listing(client, tracker):
    atlases = await _call(client, "list_atlases")
    assert atlases["atlases"] == [
        {
            "network": "gut",
            "atlas": "gut",
            "version": "v1.0",
            "generation": 1,
            "revision": 0,
            "is_latest": True,
            "published": True,
        }
    ]
    integrated = await _call(client, "list_integrated_objects", {"network": "gut", "atlas": "gut"})
    assert integrated["files"] == [
        {
            "name": "gut.h5ad",
            "size_bytes": 500_000,
            "size": "500.0 KB",
            "file_id": "file-1",
            "integrity_status": "pending",
            "entry_id": "00000000-0000-4000-8000-000000000001",
            "kind": "integrated",
            "title": "gut",
            "cell_count": 1000,
            "revision": 1,
            "wip_number": 1,
            "uploaded_at": "2026-01-01T12:00:00.000Z",
            "is_archived": False,
            "cap_url": None,
            "validation_status": "pending",
            "validation_error_message": None,
            "validation": None,
            "tier1_status": "UNKNOWN",
            "cap_status": "NEEDS_VALIDATION",
        }
    ]
    sources = await _call(client, "list_source_datasets", {"network": "gut", "atlas": "gut", "published": True})
    assert [f["name"] for f in sources["files"]] == ["src.h5ad", "broken.h5ad"]
    src, broken = sources["files"]
    assert src["validation"]["validators"]["hca_schema"] == {"valid": False, "error_count": 1, "warning_count": 3}
    assert src["validation"]["validators"]["cellxgene"] is None
    assert (src["tier1_status"], src["cap_status"], src["integrated_objects"]) == ("INVALID", "CAP_READY", ["gut.h5ad"])
    assert (broken["validation"], broken["tier1_status"], broken["cap_status"]) == (None, "UNKNOWN", "NEEDS_VALIDATION")
    assert broken["validation_error_message"].startswith("Dataset Validator failed")


@pytest.mark.asyncio
async def test_atlas_record(client, tracker):
    record = await _call(client, "get_atlas", {"network": "gut", "atlas": "gut"})
    assert (record["version"], record["status"], record["counts"]["source_datasets"]) == ("v1.0", "IN_PROGRESS", 1)
    assert record["integration_leads"] == [
        {
            "name": "Ann Lead",
            "email": "ann@example.org",
            "tracker_account": "active",
            "last_login": "2026-03-01T10:00:00.000Z",
        },
        {"name": "No Account", "email": "x@example.org", "tracker_account": "unknown", "last_login": None},
    ]
    assert record["ingestion_tasks"]["cap"] == {"count": 0, "completed": 0}


@pytest.mark.asyncio
async def test_validation_report(client, tracker):
    args = {"network": "gut", "atlas": "gut", "entry_id": "00000000-0000-4000-8000-000000000002", "kind": "source"}
    report = await _call(client, "get_validation_report", args)
    assert (report["file"], report["kind"], report["validation_status"]) == ("src.h5ad", "source", "completed")
    assert report["reports"]["hca_schema"]["warnings"] == ["w1", "w2", "w3"]
    assert report["reports"]["hca_schema"]["truncated"] is False
    assert report["reports"]["cellxgene"] is None

    capped = await _call(client, "get_validation_report", {**args, "validator": "hca_schema", "max_messages": 1})
    assert list(capped["reports"]) == ["hca_schema"]
    assert capped["reports"]["hca_schema"]["warnings"] == ["w1"]
    assert (capped["reports"]["hca_schema"]["warning_count"], capped["reports"]["hca_schema"]["truncated"]) == (3, True)

    failed = await _call(client, "get_validation_report", {**args, "entry_id": "00000000-0000-4000-8000-000000000003"})
    assert (failed["validation_status"], failed["reports"]) == ("job_failed", None)
    assert failed["validation_error_message"] == "Dataset Validator failed: file signature not found"

    unknown = await _call(client, "get_validation_report", {**args, "entry_id": "00000000-0000-4000-8000-000000000009"})
    assert unknown["error"].startswith("No source dataset '00000000-0000-4000-8000-000000000009' in gut/gut v1.0")


@pytest.mark.asyncio
async def test_missing_network_is_an_error_result(client, tracker):
    result = await _call(client, "list_integrated_objects", {"network": "", "atlas": "gut"})
    assert result == {"error": "network must be given; use list_atlases to find the network/atlas pair"}


@pytest.mark.asyncio
async def test_bad_token(client, tracker, monkeypatch):
    monkeypatch.setenv("HCA_TRACKER_API_TOKEN", "wrong")
    result = await _call(client, "list_atlases")
    assert result["error"].startswith("Tracker token expired or invalid")
    assert "wrong" not in result["error"]


@requires_aria2
@pytest.mark.asyncio
async def test_download_flow(client, tracker):
    OUTPUTS.clear()  # earlier tests ran against other fake trackers
    started = await _call(client, "start_download", {"network": "gut", "atlas": "gut", "file": "gut.h5ad"})
    assert set(started) >= {"job_id", "path", "size", "state"}
    assert started["warnings"] == ["The tracker's integrity status for this file is 'pending', not 'valid'"]

    deadline = time.monotonic() + 60
    status = {}
    while time.monotonic() < deadline:
        status = await _call(client, "download_status", {"job_id": started["job_id"]})
        if status["state"] in ("done", "failed"):
            break
        time.sleep(0.1)
    assert status["state"] == "done", status
    assert status["verified"] == "sha256"

    every = await _call(client, "download_status")
    assert [j["job_id"] for j in every["jobs"]] == [started["job_id"]]
    listed = await _call(client, "list_downloads")
    assert [f["path"] for f in listed["files"]] == [started["path"]]

    cancel = await _call(client, "cancel_download", {"job_id": started["job_id"]})
    assert cancel["error"].endswith("is done; there is nothing to cancel")

    deleted = await _call(client, "delete_download", {"path": started["path"]})
    assert deleted["deleted"] == [started["path"]]

    environment = await _call(client, "check_environment")
    assert environment["aria2c"]["ok"] is True
    assert environment["aria2_daemon"]["running"] is True
    assert environment["cache_dir"]["writable"] is True
    assert environment["tracker"] == {"url": tracker.url, "reachable": True, "token_valid": True}

    # Nothing any tool returned carries the token or a presigned URL. The
    # only URLs are the tracker's base URL (check_environment) and public
    # CAP links, which no fixture here sets.
    text = "\n".join(OUTPUTS)
    assert tracker.token not in text
    assert "X-Amz" not in text
    assert "/s3/" not in text
    assert "http" not in text.replace(tracker.url, "")


def test_unexpected_errors_are_redacted(monkeypatch):
    """The fallback for non-tracker errors strips URLs and the token from the message."""
    from hca_tracker_mcp.tools import _call

    monkeypatch.setenv("HCA_TRACKER_API_TOKEN", "tok123")

    def boom():
        raise ValueError("GET https://bucket/x?X-Amz-Signature=abc failed with tok123")

    assert _call(boom) == {"error": "ValueError: GET <url> failed with <redacted>"}
