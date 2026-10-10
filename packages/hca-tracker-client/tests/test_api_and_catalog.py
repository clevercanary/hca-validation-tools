"""Tracker API calls, the URL probe, and the listing functions."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from hca_tracker_client import (
    AuthError,
    CheckError,
    SelectionError,
    TrackerClient,
    get_atlas,
    list_atlases,
    list_files,
    validation_report,
)
from hca_tracker_client.api import probe

from .conftest import make_file


def client(tracker, token=None):
    return TrackerClient(tracker.url, token or tracker.token)


def test_bad_token(tracker):
    with pytest.raises(AuthError, match="Tracker token expired or invalid; create a new one at http"):
        client(tracker, "wrong").list_atlases()


def test_probe_reads_size_and_checksum(tracker, tmp_path):
    path = make_file(tmp_path / "f.h5ad", 5000)
    file_id = tracker.add_file(tracker.ids["gut"], "f.h5ad", path)
    presigned = client(tracker).presigned_url(tracker.ids["gut"], file_id)
    assert presigned.filename == "f-r1.h5ad"
    assert presigned.url not in repr(presigned)
    result = probe(presigned)
    assert result.size == 5000
    assert result.sha256 == tracker.blobs[file_id].sha256
    assert tracker.served_bytes == 1


def test_probe_refused_names_file_not_url(tracker, tmp_path):
    file_id = tracker.add_file(tracker.ids["gut"], "f.h5ad", make_file(tmp_path / "f", 10))
    presigned = client(tracker).presigned_url(tracker.ids["gut"], file_id)
    tracker.expire_links()
    with pytest.raises(CheckError) as error:
        probe(presigned)
    assert str(error.value) == "The file f-r1.h5ad was refused (HTTP 403); nothing was downloaded"


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
    tracker.add_file(atlas_id, "source.h5ad", make_file(tmp_path / "b", 10), kind="source")
    result = list_files(client(tracker), "lung", "adipose", "integrated")
    assert result == {
        "network": "lung",
        "atlas": "adipose",
        "version": "v2.1",
        "published": False,
        "files": [
            {
                # The original listing, which start_download callers depend on, comes first and unchanged.
                "name": "lung-r2.h5ad",
                "size_bytes": 1234,
                "size": "1.2 KB",
                "file_id": "file-1",
                "integrity_status": "pending",
                "entry_id": "00000000-0000-4000-8000-000000000001",
                "kind": "integrated",
                "title": "lung-r2",
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
        ],
    }
    sources = list_files(client(tracker), "lung", "adipose", "source", generation=2)
    assert [f["name"] for f in sources["files"]] == ["source.h5ad"]
    assert sources["files"][0]["kind"] == "source"
    assert "reprocessed_status" not in result["files"][0]
    text = json.dumps([result, sources, list_atlases(client(tracker))])
    assert "http" not in text
    assert tracker.token not in text


def test_results_carry_cap_urls_but_never_the_tracker_url_or_token(tracker, tmp_path):
    """A CAP URL is public and passes through; the tracker's own URL and the token never appear."""
    tracker.add_file(
        tracker.ids["gut"],
        "a.h5ad",
        make_file(tmp_path / "a", 10),
        capUrl="https://celltype.info/project/1",
        validationStatus="completed",
        reports={"cap": {"valid": True}},
    )
    tracker.add_atlas("heart", "heart", 1, 0, capId="https://celltype.info/project/heart")
    results = [
        list_files(client(tracker), "gut", "gut", "integrated"),
        validation_report(client(tracker), "gut", "gut", "00000000-0000-4000-8000-000000000001", "integrated"),
        get_atlas(client(tracker), "heart", "heart"),
    ]
    text = json.dumps(results)
    assert text.count("https://celltype.info/") == 2
    assert text.replace("https://celltype.info/", "").count("http") == 0
    assert tracker.url not in text
    assert tracker.token not in text


def validated_file(tracker, tmp_path, name, kind="integrated", **fields):
    """A file whose four validators ran: CAP failed, hcaSchema failed with 3 warnings, the others passed."""
    reports = {
        "cap": {"valid": False, "errors": ["AnnDataMissingObsColumns: organism"]},
        "cellxgene": {"valid": True},
        "hcaSchema": {"valid": False, "errors": ["ERROR: e1", "ERROR: e2"], "warnings": ["w1", "w2", "w3"]},
        "hcaCellAnnotation": {"valid": True},
    }
    return tracker.add_file(
        tracker.ids["gut"],
        name,
        make_file(tmp_path / name, 10),
        kind=kind,
        validationStatus="completed",
        reports=reports,
        **fields,
    )


def test_list_files_validation_and_source_dataset_fields(tracker, tmp_path):
    validated_file(tracker, tmp_path, "src.h5ad", kind="source", used_by=["gut-all.h5ad", "gut-epi.h5ad"])
    tracker.add_file(
        tracker.ids["gut"],
        "broken.h5ad",
        make_file(tmp_path / "broken", 10),
        kind="source",
        validationStatus="job_failed",
        validationErrorMessage="Dataset Validator failed: file signature not found",
        reprocessedStatus="Unspecified",
    )
    rows = list_files(client(tracker), "gut", "gut", "source")["files"]
    validated, broken = rows
    assert validated["validation"] == {
        "overall_valid": False,
        "validators": {
            "cap": {"valid": False, "error_count": 1, "warning_count": 0},
            "cellxgene": {"valid": True, "error_count": 0, "warning_count": 0},
            "hca_schema": {"valid": False, "error_count": 2, "warning_count": 3},
            "hca_cell_annotation": {"valid": True, "error_count": 0, "warning_count": 0},
        },
    }
    assert (validated["tier1_status"], validated["cap_status"]) == ("INVALID", "CAP_VALIDATION_FAILED")
    assert validated["integrated_objects"] == ["gut-all.h5ad", "gut-epi.h5ad"]
    assert (validated["reprocessed_status"], validated["publication_status"]) == ("Original", "Unspecified")
    assert validated["source_study_title"] is None
    assert broken["validation_status"] == "job_failed"
    assert broken["validation_error_message"] == "Dataset Validator failed: file signature not found"
    assert broken["validation"] is None
    assert (broken["tier1_status"], broken["cap_status"]) == ("UNKNOWN", "INFO_REQUIRED")


def test_list_files_partial_summary_leaves_missing_validators_none(tracker, tmp_path):
    tracker.add_file(
        tracker.ids["gut"],
        "cap-only.h5ad",
        make_file(tmp_path / "c", 10),
        validationStatus="completed",
        reports={"cap": {"valid": True}},
        capUrl="https://celltype.info/project/1",
    )
    row = list_files(client(tracker), "gut", "gut", "integrated")["files"][0]
    assert row["validation"]["validators"]["hca_schema"] is None
    assert row["validation"]["overall_valid"] is True
    assert (row["tier1_status"], row["cap_status"], row["cap_url"]) == (
        "UNKNOWN",
        "PUBLISHED",
        "https://celltype.info/project/1",
    )


def test_get_atlas_record_and_lead_logins(tracker):
    tracker.ids["heart"] = tracker.add_atlas(
        "heart",
        "heart",
        1,
        0,
        leads=[
            {"name": "Ann Lead", "email": "Ann@Example.org"},
            {"name": "Bob Lead", "email": "bob@example.org"},
            {"name": "Old Lead", "email": "old@example.org"},
            {"name": "No Account", "email": "none@example.org"},
        ],
        publications=[
            {"doi": "10.1/x", "publication": {"title": "Heart atlas"}},
            {"doi": "10.1/y", "publication": None},
        ],
        title="Heart v1",
        status="OC_ENDORSED",
        wave="2",
        targetCompletion="2026-12-31T23:59:59.999Z",
        capId="https://celltype.info/project/heart",
        sourceStudyCount=3,
        sourceDatasetCount=5,
        componentAtlasCount=2,
        ingestionTaskCounts={
            "CAP": {"count": 3, "completedCount": 1},
            "CELLXGENE": {"count": 3, "completedCount": 0},
            "HCA_DATA_REPOSITORY": {"count": 3, "completedCount": 3},
        },
    )
    tracker.add_user("Ann Lead", "ann@example.org", last_login="2026-03-01T10:00:00.000Z", role="INTEGRATION_LEAD")
    tracker.add_user("Bob Lead", "bob@example.org")  # never logged in
    tracker.add_user("Old Lead", "old@example.org", last_login="2025-02-01T10:00:00.000Z", disabled=True)
    record = get_atlas(client(tracker), "heart", "heart")
    assert record == {
        "network": "heart",
        "atlas": "heart",
        "version": "v1.0",
        "published": False,
        "generation": 1,
        "revision": 0,
        "is_latest": True,
        "title": "Heart v1",
        "short_name": "Heart",
        "status": "OC_ENDORSED",
        "published_at": None,
        "wave": "2",
        "target_completion": "2026-12-31T23:59:59.999Z",
        "cap_project_url": "https://celltype.info/project/heart",
        "integration_leads": [
            {
                "name": "Ann Lead",
                "email": "Ann@Example.org",
                "tracker_account": "active",
                "last_login": "2026-03-01T10:00:00.000Z",
            },
            {"name": "Bob Lead", "email": "bob@example.org", "tracker_account": "active", "last_login": None},
            {
                "name": "Old Lead",
                "email": "old@example.org",
                "tracker_account": "disabled",
                "last_login": "2025-02-01T10:00:00.000Z",
            },
            {"name": "No Account", "email": "none@example.org", "tracker_account": "unknown", "last_login": None},
        ],
        "counts": {"source_studies": 3, "source_datasets": 5, "integrated_objects": 2},
        "ingestion_tasks": {
            "cap": {"count": 3, "completed": 1},
            "cellxgene": {"count": 3, "completed": 0},
            "hca_data_repository": {"count": 3, "completed": 3},
        },
        "publications": [{"doi": "10.1/x", "title": "Heart atlas"}, {"doi": "10.1/y", "title": None}],
    }
    assert tracker.token not in json.dumps(record)


@pytest.mark.parametrize("serialised", ["1970-01-01T05:00:00.000Z", "1969-12-31T19:00:00.000Z", "1970-01-01T00:00:00"])
def test_never_logged_in_in_any_server_time_zone(tracker, serialised):
    """The tracker serialises epoch 0 in its server's zone: west of UTC it lands in 1970, east of UTC in 1969."""
    tracker.add_atlas("heart", "heart", 1, 0, leads=[{"name": "Lead", "email": "lead@example.org"}])
    tracker.add_user("Lead", "lead@example.org", last_login=serialised)
    assert get_atlas(client(tracker), "heart", "heart")["integration_leads"][0]["last_login"] is None


def test_get_atlas_selects_the_version(tracker):
    assert get_atlas(client(tracker), "lung", "adipose")["version"] == "v2.1"
    assert get_atlas(client(tracker), "lung", "adipose", published=True)["version"] == "v2.0"
    assert get_atlas(client(tracker), "lung", "adipose", generation=1)["version"] == "v1.1"
    with pytest.raises(SelectionError, match="No atlas lung/gut"):
        get_atlas(client(tracker), "lung", "gut")


def test_validation_report_messages_and_truncation(tracker, tmp_path):
    validated_file(tracker, tmp_path, "gut-all.h5ad")
    report = validation_report(client(tracker), "gut", "gut", "00000000-0000-4000-8000-000000000001", "integrated")
    assert report["file"] == "gut-all.h5ad"
    assert report["file_id"] == "file-1"
    assert (report["entry_id"], report["kind"]) == ("00000000-0000-4000-8000-000000000001", "integrated")
    assert report["validation_status"] == "completed"
    assert report["validation_error_message"] is None
    assert report["max_messages"] == 200
    assert set(report["reports"]) == {"cap", "cellxgene", "hca_schema", "hca_cell_annotation"}
    assert report["reports"]["hca_schema"] == {
        "valid": False,
        "started_at": "2026-01-02T00:00:00+00:00",
        "finished_at": "2026-01-02T00:01:00+00:00",
        "error_count": 2,
        "warning_count": 3,
        "errors": ["ERROR: e1", "ERROR: e2"],
        "warnings": ["w1", "w2", "w3"],
        "truncated": False,
    }
    assert report["reports"]["cellxgene"]["errors"] == []

    capped = validation_report(
        client(tracker),
        "gut",
        "gut",
        "00000000-0000-4000-8000-000000000001",
        "integrated",
        validator="hca_schema",
        max_messages=2,
    )
    assert list(capped["reports"]) == ["hca_schema"]
    assert capped["reports"]["hca_schema"]["warnings"] == ["w1", "w2"]
    assert capped["reports"]["hca_schema"]["warning_count"] == 3
    assert capped["reports"]["hca_schema"]["errors"] == ["ERROR: e1", "ERROR: e2"]
    assert capped["reports"]["hca_schema"]["truncated"] is True
    assert capped["max_messages"] == 2


def test_validation_report_for_a_file_without_one(tracker, tmp_path):
    tracker.add_file(
        tracker.ids["gut"],
        "broken.h5ad",
        make_file(tmp_path / "broken", 10),
        kind="source",
        validationStatus="job_failed",
        validationErrorMessage="Dataset Validator failed: file signature not found",
    )
    report = validation_report(client(tracker), "gut", "gut", "00000000-0000-4000-8000-000000000001", "source")
    assert report["kind"] == "source"
    assert report["validation_status"] == "job_failed"
    assert report["validation_error_message"] == "Dataset Validator failed: file signature not found"
    assert report["reports"] is None


def test_validation_report_partial_reports_and_arguments(tracker, tmp_path):
    tracker.add_file(
        tracker.ids["gut"],
        "cap-only.h5ad",
        make_file(tmp_path / "c", 10),
        validationStatus="completed",
        reports={"cap": {"valid": True}},
    )
    report = validation_report(client(tracker), "gut", "gut", "00000000-0000-4000-8000-000000000001", "integrated")
    assert report["reports"]["cap"]["valid"] is True
    assert report["reports"]["hca_schema"] is None
    with pytest.raises(SelectionError, match="No validator 'hcaSchema'; validators: cap, cellxgene, hca_schema"):
        validation_report(
            client(tracker), "gut", "gut", "00000000-0000-4000-8000-000000000001", "integrated", validator="hcaSchema"
        )
    with pytest.raises(ValueError, match="max_messages must be at least 1"):
        validation_report(
            client(tracker), "gut", "gut", "00000000-0000-4000-8000-000000000001", "integrated", max_messages=0
        )
    with pytest.raises(ValueError, match="kind must be"):
        validation_report(client(tracker), "gut", "gut", "00000000-0000-4000-8000-000000000001", "files")
    with pytest.raises(SelectionError, match="entry_id must be the entry_id from list_integrated_objects"):
        validation_report(client(tracker), "gut", "gut", "", "integrated")
    with pytest.raises(SelectionError, match="got 'cap-only.h5ad'"):
        validation_report(client(tracker), "gut", "gut", "cap-only.h5ad", "integrated")
    # The wrong kind for a real entry, or an unknown entry, is a 404 from the tracker, reported as a selection error.
    with pytest.raises(
        SelectionError,
        match="No source dataset '00000000-0000-4000-8000-000000000001' in gut/gut v1.0; take entry_id and kind",
    ):
        validation_report(client(tracker), "gut", "gut", "00000000-0000-4000-8000-000000000001", "source")
    with pytest.raises(
        SelectionError, match="No integrated object '00000000-0000-4000-8000-000000000009' in gut/gut v1.0"
    ):
        validation_report(client(tracker), "gut", "gut", "00000000-0000-4000-8000-000000000009", "integrated")


def test_token_goes_only_to_the_tracker(monkeypatch):
    """Every TrackerClient call sends the token, and only to a URL under the tracker's base URL."""
    import io
    import urllib.request

    seen = []

    def capture(request, timeout=None):
        seen.append((request.full_url, request.unredirected_hdrs.get("Authorization"), request.headers))
        body = (
            b'{"url": "https://bucket/x?X-Amz-Signature=1", "filename": "f.h5ad"}'
            if "presigned" in request.full_url
            else b"[]"
        )
        return io.BytesIO(body)

    monkeypatch.setattr(urllib.request, "urlopen", capture)
    tracker = TrackerClient("https://tracker.example/", "s3cret")
    tracker.list_atlases()
    tracker.component_atlases("a1")
    tracker.source_datasets("a1")
    tracker.component_atlas("a1", "e1")
    tracker.source_dataset("a1", "e1")
    tracker.users()
    tracker.presigned_url("a1", "f1")
    assert len(seen) == 7
    for url, authorization, headers in seen:
        assert url.startswith("https://tracker.example/api/"), url
        assert authorization == "Bearer s3cret"
        assert "Authorization" not in headers  # unredirected: dropped by urllib on a redirect


def test_token_not_forwarded_on_redirect():
    """A tracker redirect to another host must not carry the bearer token."""
    seen = {}

    class Target(BaseHTTPRequestHandler):
        def do_GET(self):
            seen["authorization"] = self.headers.get("Authorization")
            body = b"[]"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Target) as target:
        threading.Thread(target=target.serve_forever, daemon=True).start()

        class Redirect(Target):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{target.server_address[1]}/elsewhere")
                self.send_header("Content-Length", "0")
                self.end_headers()

        with ThreadingHTTPServer(("127.0.0.1", 0), Redirect) as origin:
            threading.Thread(target=origin.serve_forever, daemon=True).start()
            assert TrackerClient(f"http://127.0.0.1:{origin.server_address[1]}", "s3cret").list_atlases() == []
            origin.shutdown()
        target.shutdown()
    assert seen == {"authorization": None}


def test_unknown_kind_rejected(tracker):
    with pytest.raises(ValueError, match="kind must be"):
        list_files(client(tracker), "gut", "gut", "integrate")


@pytest.mark.parametrize(("code", "reason"), [(416, "is empty on the server"), (404, "is not in storage")])
def test_probe_names_empty_and_missing_files(monkeypatch, code, reason):
    import urllib.error

    import hca_tracker_client.api as api

    def refuse(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, code, "x", {}, None)

    monkeypatch.setattr(api.urllib.request, "urlopen", refuse)
    with pytest.raises(CheckError, match=f"The file f-r1.h5ad {reason}"):
        probe(api.Presigned(url="https://bucket/f?X-Amz-Signature=1", filename="f-r1.h5ad"))
