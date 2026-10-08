"""Tracker API calls, the URL probe, and the listing functions."""

import json

import pytest

from hca_tracker_client import AuthError, CheckError, TrackerClient, list_atlases, list_files
from hca_tracker_client.api import probe

from .conftest import make_file


def client(tracker, token=None):
    return TrackerClient(tracker.url, token or tracker.token)


def test_bad_token(tracker):
    with pytest.raises(AuthError, match="Tracker token expired or invalid; create a new one at http"):
        client(tracker, "wrong").list_atlases()


def test_probe_reads_size_and_checksum(tracker, tmp_path):
    path = make_file(tmp_path / "f.h5ad", 5000)
    file_id = tracker.add_file(tracker.ids["gut"], "f-r1.h5ad", path)
    presigned = client(tracker).presigned_url(tracker.ids["gut"], file_id)
    assert presigned.filename == "f-r1.h5ad"
    assert presigned.url not in repr(presigned)
    result = probe(presigned)
    assert result.size == 5000
    assert result.sha256 == tracker.blobs[file_id].sha256
    assert tracker.served_bytes == 1


def test_probe_refused_names_file_not_url(tracker, tmp_path):
    file_id = tracker.add_file(tracker.ids["gut"], "f-r1.h5ad", make_file(tmp_path / "f", 10))
    presigned = client(tracker).presigned_url(tracker.ids["gut"], file_id)
    tracker.expire_links()
    with pytest.raises(CheckError) as error:
        probe(presigned)
    assert str(error.value) == "The download link for f-r1.h5ad was refused (HTTP 403); nothing was downloaded"


def test_list_atlases_fields(tracker):
    rows = list_atlases(client(tracker))
    assert rows[0] == {
        "network": "adipose",
        "atlas": "adipose",
        "version": "v1.0",
        "generation": 1,
        "revision": 0,
        "is_latest": True,
        "published": True,
    }
    lung = [(r["version"], r["is_latest"]) for r in rows if r["network"] == "lung"]
    assert lung == [("v1.0", False), ("v1.1", True), ("v2.0", False), ("v2.1", True)]


def test_list_files_fields_and_no_secrets(tracker, tmp_path):
    atlas_id = tracker.ids["lung-2.1"]
    tracker.add_file(atlas_id, "lung-r2.h5ad", make_file(tmp_path / "a", 1234), integrity="pending")
    tracker.add_file(atlas_id, "source-r1.h5ad", make_file(tmp_path / "b", 10), kind="source")
    result = list_files(client(tracker), "lung", "adipose", "integrated")
    assert result == {
        "network": "lung",
        "atlas": "adipose",
        "version": "v2.1",
        "published": False,
        "files": [
            {
                "name": "lung-r2.h5ad",
                "size_bytes": 1234,
                "size": "1.2 KB",
                "file_id": "file-1",
                "integrity_status": "pending",
            }
        ],
    }
    sources = list_files(client(tracker), "lung", "adipose", "source", generation=2)
    assert [f["name"] for f in sources["files"]] == ["source-r1.h5ad"]
    text = json.dumps([result, sources, list_atlases(client(tracker))])
    assert "http" not in text
    assert tracker.token not in text
