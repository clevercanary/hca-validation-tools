"""Uploads: the target path, the trust boundary, the plan, and the detached worker, over a fake engine."""

import contextlib
import inspect
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import ClassVar

import pytest

from hca_tracker_client import CheckError, ConfigError, JobError, Uploads, environment_report, load_config
from hca_tracker_client import uploads as module
from hca_tracker_client.testing import fake_s3 as make_fake_s3
from hca_tracker_client.testing import save_profile
from hca_tracker_client.uploads import (
    BUCKETS,
    TRACKER_HOSTS,
    UploadStore,
    atlas_folder,
    bucket_for,
    resolve_profile,
    resolve_target,
    s3_prefix,
    smart_sync_atlas,
    tracker_environment,
    worker_alive,
)

from .conftest import make_config, make_file, wait_for

FAKE_ENGINE = "hca_tracker_client.testing:FakeSmartSync"
REAL_TRANSFER_TOOL = module.transfer_tool  # captured before any fixture replaces it
PROD_URL = "https://tracker.data.humancellatlas.org"
DEV_URL = "https://test-tracker.data.humancellatlas.dev.clevercanary.com/"


# --- fixtures -----------------------------------------------------------------


@pytest.fixture
def fake_s3(tmp_path, monkeypatch):
    """A folder standing in for S3, with both buckets present."""
    monkeypatch.delenv("HCA_TRACKER_FAKE_S3_DELAY", raising=False)
    monkeypatch.setenv("HCA_TRACKER_FAKE_S3", "")  # restored by monkeypatch; make_fake_s3 sets it
    return make_fake_s3(tmp_path / "s3", *BUCKETS.values())


@pytest.fixture
def profile(tmp_path, monkeypatch):
    """A profile saved the way `hca-smart-sync config` saves it, in a HOME of its own."""
    home = tmp_path / "home"
    save_profile(home, "team-profile")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("HCA_AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    return "team-profile"


@pytest.fixture
def transfer_tool(monkeypatch):
    """Pretend s5cmd is installed: the fake engine transfers nothing, and CI has neither tool."""
    monkeypatch.setattr("hca_tracker_client.uploads.transfer_tool", lambda: ("s5cmd", "/usr/local/bin/s5cmd"))


@pytest.fixture
def uploads(cache_dir, tracker, fake_s3, profile, transfer_tool):
    """Uploads against the fake tracker, declared the dev tracker, with the fake engine."""
    return Uploads(make_config(cache_dir, tracker, tracker_environment="dev", upload_engine=FAKE_ENGINE))


@pytest.fixture
def staged(tmp_path):
    """A folder with two files to upload."""
    folder = tmp_path / "outbox"
    make_file(folder / "a.h5ad", 20_000)
    make_file(folder / "b.h5ad", 30_000)
    (folder / "notes.txt").write_text("ignored")
    return folder


UPLOAD_ENDED = ("done", "failed", "interrupted")


# --- the hca-smart-sync contract ------------------------------------------------


def test_smart_sync_import_contract(tmp_path):
    """The undeclared names this package uses, and the shapes it reads, as of hca-smart-sync 0.4.x."""
    import hca_smart_sync
    from hca_smart_sync import Config, SmartSync
    from hca_smart_sync.cli import ATLAS_BIONETWORKS, FileType, _build_s3_path
    from hca_smart_sync.config_manager import get_config_path
    from hca_smart_sync.config_manager import load_config as load_smart_sync_config

    assert hca_smart_sync.__version__.startswith("0.4.")
    assert {ft.value for ft in FileType} == {"source-datasets", "integrated-objects"}
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in ATLAS_BIONETWORKS.items())
    assert list(inspect.signature(SmartSync.sync).parameters) == [
        "self",
        "local_path",
        "s3_path",
        "dry_run",
        "verbose",
        "force",
        "plan_only",
    ]
    assert list(inspect.signature(_build_s3_path).parameters) == ["bucket_name", "atlas", "folder"]
    assert list(inspect.signature(SmartSync._upload_file).parameters) == [
        "self",
        "local_path",
        "s3_url",
        "include_checksum",
        "file_size",
    ]
    assert get_config_path() == Path.home() / ".hca-smart-sync" / "config.yaml"
    assert load_smart_sync_config(tmp_path / "missing.yaml") is None

    # The return dict of a plan, over a stubbed S3 client: the keys run_plan reads.
    config = Config()
    config.aws.profile = "stub"
    engine = SmartSync(config)

    class S3:
        class exceptions:
            class NoSuchKey(Exception): ...

            class NoSuchBucket(Exception): ...

            class ClientError(Exception):
                response: ClassVar[dict] = {"Error": {"Code": "AccessDenied", "Message": "denied"}}

        def list_objects_v2(self, **kwargs):
            return {}

        def get_bucket_location(self, **kwargs):
            return {}

        def head_object(self, **kwargs):
            raise S3.exceptions.NoSuchKey()

    engine._s3_client = S3()
    make_file(tmp_path / "x.h5ad", 10)
    result = engine.sync(tmp_path, "s3://b/p/q/", plan_only=True)
    assert result["plan_only"] is True and result["manifest_path"] is None
    (entry,) = result["files_to_upload"]
    assert {"local_path", "filename", "size", "checksum", "reason"} <= set(entry)
    assert (entry["filename"], entry["size"], entry["reason"]) == ("x.h5ad", 10, "new")

    (tmp_path / "x.h5ad").unlink()
    assert engine.sync(tmp_path, "s3://b/p/q/", plan_only=True)["no_files_found"] is True

    class Denied(S3):
        def list_objects_v2(self, **kwargs):
            raise S3.exceptions.ClientError()

    engine._s3_client = Denied()
    assert engine.sync(tmp_path, "s3://b/p/q/", plan_only=True)["error"] == "access_denied"


def test_prefix_matches_the_cli_for_every_known_atlas():
    """Byte for byte what `hca-smart-sync sync <atlas> <file-type>` would use, for every map entry."""
    from hca_smart_sync.cli import ATLAS_BIONETWORKS, FileType, _build_s3_path

    assert ATLAS_BIONETWORKS, "the map is empty"
    for name, bionetwork in ATLAS_BIONETWORKS.items():
        slug, _, generation = name.rpartition("-v")
        assert smart_sync_atlas(slug, int(generation)) == name
        for file_type in FileType:
            for environment, bucket in BUCKETS.items():
                ours = f"s3://{bucket}/{s3_prefix(bionetwork, name, file_type.value)}"
                assert ours == _build_s3_path(bucket, name, file_type.value), (name, file_type, environment)


def test_buckets_are_the_cli_literals():
    """The CLI hardcodes these in its `sync` command; a tool that lands files elsewhere is useless."""
    import hca_smart_sync.cli as cli

    source = inspect.getsource(cli.sync)
    assert 'bucket = "hca-atlas-tracker-data"' in source
    assert 'bucket = "hca-atlas-tracker-data-dev"' in source
    assert BUCKETS == {"dev": "hca-atlas-tracker-data-dev", "prod": "hca-atlas-tracker-data"}
    assert bucket_for("dev") == "hca-atlas-tracker-data-dev"
    with pytest.raises(CheckError, match="environment must be 'dev' or 'prod', got 'staging'"):
        bucket_for("staging")
    assert inspect.signature(Uploads.plan).parameters["environment"].default == "dev"
    assert inspect.signature(Uploads.start).parameters["environment"].default == "dev"


def test_base_package_does_not_import_smart_sync():
    """`import hca_tracker_client` must work without the extra; the engine is imported on first use."""
    code = (
        "import sys, hca_tracker_client; assert 'hca_smart_sync' not in sys.modules; assert 'boto3' not in sys.modules"
    )
    import subprocess

    subprocess.run([sys.executable, "-c", code], check=True)


def test_missing_extra_is_a_clean_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "hca_smart_sync", None)  # makes `import hca_smart_sync` raise ImportError
    with pytest.raises(ConfigError, match=r"hca-smart-sync is not installed; install the upload extra"):
        module.smart_sync()


# --- the profile and the tracker environment --------------------------------------


def test_profile_resolution(profile, monkeypatch, tmp_path):
    assert resolve_profile() == ("team-profile", str(Path.home() / ".hca-smart-sync" / "config.yaml"))
    monkeypatch.setenv("AWS_PROFILE", "ambient")
    assert resolve_profile()[0] == "team-profile", "the saved profile wins over AWS_PROFILE, as in the CLI"
    monkeypatch.setenv("HCA_AWS_PROFILE", "explicit")
    assert resolve_profile() == ("explicit", "HCA_AWS_PROFILE")

    monkeypatch.delenv("HCA_AWS_PROFILE")
    (Path.home() / ".hca-smart-sync" / "config.yaml").write_text("atlas: gut-v1\n")
    assert resolve_profile() == ("ambient", "AWS_PROFILE")
    monkeypatch.delenv("AWS_PROFILE")
    with pytest.raises(ConfigError, match=r"run `hca-smart-sync config`.*or set HCA_AWS_PROFILE"):
        resolve_profile()
    (Path.home() / ".hca-smart-sync" / "config.yaml").write_text("profile: [\n")
    with pytest.raises(ConfigError, match="Could not read hca-smart-sync's settings"):
        resolve_profile()


def test_tracker_environment_by_host(cache_dir, tracker):
    assert tracker_environment(make_config(cache_dir, tracker, tracker_url=PROD_URL)) == (
        "tracker.data.humancellatlas.org",
        "prod",
    )
    assert tracker_environment(make_config(cache_dir, tracker, tracker_url=DEV_URL))[1] == "dev"
    assert tracker_environment(make_config(cache_dir, tracker, tracker_environment="prod")) == ("127.0.0.1", "prod")
    with pytest.raises(CheckError, match=r"host '127.0.0.1' is not one this package knows.*HCA_TRACKER_ENVIRONMENT"):
        tracker_environment(make_config(cache_dir, tracker))
    with pytest.raises(
        CheckError, match=r"HCA_TRACKER_ENVIRONMENT='prod' contradicts the configured tracker .*dev tracker"
    ):
        tracker_environment(make_config(cache_dir, tracker, tracker_url=DEV_URL, tracker_environment="prod"))
    assert (
        tracker_environment(make_config(cache_dir, tracker, tracker_url=DEV_URL, tracker_environment="dev"))[1] == "dev"
    )
    with pytest.raises(ConfigError, match="HCA_TRACKER_URL must be set"):
        tracker_environment(make_config(cache_dir, tracker, tracker_url=None))
    assert set(TRACKER_HOSTS.values()) == set(BUCKETS)


def test_environment_must_match_the_tracker(uploads, staged):
    with pytest.raises(
        CheckError,
        match=r"is the dev tracker, which ingests from hca-atlas-tracker-data-dev, but "
        r"environment='prod' names hca-atlas-tracker-data.*Nothing was uploaded",
    ):
        uploads.plan("gut", "gut", "source-datasets", str(staged), environment="prod")
    assert not list(uploads.store.directory.glob("*.json")) if uploads.store.directory.exists() else True


def test_environment_variable_validation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HCA_TRACKER_ENVIRONMENT", "staging")
    with pytest.raises(ConfigError, match="HCA_TRACKER_ENVIRONMENT must be one of dev, prod"):
        load_config()
    monkeypatch.setenv("HCA_TRACKER_ENVIRONMENT", "")
    monkeypatch.setenv("HCA_TRACKER_UPLOAD_ENGINE", FAKE_ENGINE)
    config = load_config()
    assert (config.tracker_environment, config.upload_engine) == (None, FAKE_ENGINE)
    # The value is imported, and .env is repo-controlled: only the two known factories are accepted.
    (tmp_path / ".env").write_text("HCA_TRACKER_UPLOAD_ENGINE=os:system\n")
    monkeypatch.delenv("HCA_TRACKER_UPLOAD_ENGINE")
    with pytest.raises(
        ConfigError, match=r"HCA_TRACKER_UPLOAD_ENGINE must be one of .*make_engine, .*FakeSmartSync, got 'os:system'"
    ):
        load_config()


# --- the target -----------------------------------------------------------------


def test_atlas_folder_follows_the_tracker_parser():
    """The tracker's parseS3AtlasName examples: 'gut-v1' is v1.0, 'retina-v1-1' is v1.1."""
    assert atlas_folder("gut", 1, 0) == "gut-v1"
    assert atlas_folder("retina", 1, 1) == "retina-v1-1"
    assert atlas_folder("gut", 2, 3) == "gut-v2-3"
    assert atlas_folder("gut", 1, 0) == smart_sync_atlas("gut", 1), "revision 0 is the name the CLI's map knows"


def test_target_from_tracker_and_map(tracker):
    atlases = tracker.atlases
    target = resolve_target(atlases, "gut", "gut", None, "source-datasets", "dev")
    assert target.url == "s3://hca-atlas-tracker-data-dev/gut/gut-v1/source-datasets/"
    assert (target.version, target.atlas_folder) == ("v1.0", "gut-v1")
    with pytest.raises(CheckError, match="file_type must be one of source-datasets, integrated-objects, got 'cells'"):
        resolve_target(atlases, "gut", "gut", None, "cells", "dev")

    # A later revision has its own folder; the newest revision of the generation is the one selected.
    tracker.add_atlas("gut", "gut", 1, 1)
    target = resolve_target(tracker.atlases, "gut", "gut", None, "integrated-objects", "prod")
    assert target.url == "s3://hca-atlas-tracker-data/gut/gut-v1-1/integrated-objects/"
    assert (target.version, target.atlas_folder) == ("v1.1", "gut-v1-1")


def test_target_refusals(tracker):
    atlases = tracker.atlases
    # lung/adipose generation 2: adipose-v2 is not in the map.
    with pytest.raises(
        CheckError,
        match=r"does not know the atlas 'adipose-v2' \(lung/adipose v2.1\); add it to "
        r"ATLAS_BIONETWORKS in hca-ingest-tools.*Nothing was uploaded",
    ):
        resolve_target(atlases, "lung", "adipose", None, "source-datasets", "dev")
    # adipose/adipose v1: the map files adipose-v1 under adipose, so lung/adipose v1 disagrees.
    with pytest.raises(
        CheckError,
        match=r"files 'adipose-v1' under the bionetwork 'adipose', but the tracker lists "
        r"the atlas under 'lung'; nothing was uploaded",
    ):
        resolve_target(atlases, "lung", "adipose", 1, "source-datasets", "dev")
    # adipose/adipose v1.0 is published: the tracker would reject the files after the transfer.
    with pytest.raises(
        CheckError,
        match=r"Atlas version adipose/adipose v1.0 is published, and the tracker refuses uploads to a published "
        r"version. Create its next revision in the tracker",
    ):
        resolve_target(atlases, "adipose", "adipose", None, "source-datasets", "dev")
    tracker.add_atlas("adipose", "adipose", 1, 1)
    assert resolve_target(tracker.atlases, "adipose", "adipose", None, "source-datasets", "dev").prefix == (
        "adipose/adipose-v1-1/source-datasets/"
    )


# --- plan --------------------------------------------------------------------------


def test_plan(uploads, staged, fake_s3):
    plan = uploads.plan("gut", "gut", "source-datasets", str(staged))
    assert plan["target"] == "s3://hca-atlas-tracker-data-dev/gut/gut-v1/source-datasets/"
    assert (plan["bucket"], plan["prefix"]) == ("hca-atlas-tracker-data-dev", "gut/gut-v1/source-datasets/")
    assert (plan["version"], plan["atlas_folder"]) == ("v1.0", "gut-v1")
    assert (plan["environment"], plan["profile"], plan["force"]) == ("dev", "team-profile", False)
    assert plan["profile_source"].endswith(".hca-smart-sync/config.yaml")
    assert plan["transfer_tool"] == "s5cmd"
    assert [(f["name"], f["size_bytes"], f["reason"]) for f in plan["files"]] == [
        ("a.h5ad", 20_000, "new"),
        ("b.h5ad", 30_000, "new"),
    ]
    assert all(len(f["sha256"]) == 64 for f in plan["files"])
    assert (plan["total_bytes"], plan["total_size"], plan["up_to_date"]) == (50_000, "50.0 KB", [])
    assert "no_files_found" not in plan
    assert not list(fake_s3.rglob("*.h5ad")), "a plan uploads nothing"
    assert not list(staged.glob("manifest-*.json")), "a plan writes no manifest"
    assert "s3://" in json.dumps(plan) and "AKIA" not in json.dumps(plan)

    # One file already in the bucket, unchanged: it is up to date; forced, it is planned again.
    stored = fake_s3 / "hca-atlas-tracker-data-dev" / "gut/gut-v1/source-datasets" / "a.h5ad"
    stored.parent.mkdir(parents=True)
    stored.write_bytes((staged / "a.h5ad").read_bytes())
    Path(f"{stored}.sha256").write_text(plan["files"][0]["sha256"])
    plan = uploads.plan("gut", "gut", "source-datasets", str(staged))
    assert ([f["name"] for f in plan["files"]], plan["up_to_date"]) == (["b.h5ad"], ["a.h5ad"])
    forced = uploads.plan("gut", "gut", "source-datasets", str(staged), force=True)
    assert [(f["name"], f["reason"]) for f in forced["files"]] == [("a.h5ad", "forced"), ("b.h5ad", "forced")]

    # Changed locally: planned again as changed.
    make_file(staged / "a.h5ad", 20_001)
    plan = uploads.plan("gut", "gut", "source-datasets", str(staged))
    assert [(f["name"], f["reason"]) for f in plan["files"]] == [("a.h5ad", "changed"), ("b.h5ad", "new")]


def test_plan_refusals(uploads, staged, fake_s3, tmp_path):
    (fake_s3 / "hca-atlas-tracker-data-dev" / "DENIED").touch()
    with pytest.raises(
        CheckError,
        match=r"The AWS profile 'team-profile' cannot list s3://hca-atlas-tracker-data-dev/"
        r"gut/gut-v1/source-datasets/ .*Nothing was uploaded",
    ):
        uploads.plan("gut", "gut", "source-datasets", str(staged))
    (fake_s3 / "hca-atlas-tracker-data-dev" / "DENIED").unlink()

    with pytest.raises(CheckError, match="local_path must be a folder, not a file.*Put a.h5ad in a folder of its own"):
        uploads.plan("gut", "gut", "source-datasets", str(staged / "a.h5ad"))
    with pytest.raises(CheckError, match="is not a folder"):
        uploads.plan("gut", "gut", "source-datasets", str(tmp_path / "nowhere"))
    with pytest.raises(CheckError, match="local_path must name the folder to upload from"):
        uploads.plan("gut", "gut", "source-datasets", "  ")

    empty = tmp_path / "empty"
    empty.mkdir()
    plan = uploads.plan("gut", "gut", "source-datasets", str(empty))
    assert (plan["files"], plan["no_files_found"]) == ([], True)


def test_plan_needs_a_profile(uploads, staged, monkeypatch):
    (Path.home() / ".hca-smart-sync" / "config.yaml").unlink()
    with pytest.raises(ConfigError, match="No AWS profile for uploads"):
        uploads.plan("gut", "gut", "source-datasets", str(staged))


def test_real_engine_refuses_an_unknown_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))  # no ~/.aws at all
    with pytest.raises(ConfigError, match="The AWS profile 'nope' is not in ~/.aws/config"):
        module.make_engine("nope")


# --- start and status --------------------------------------------------------------


def test_upload_end_to_end(uploads, staged, fake_s3):
    started = uploads.start("gut", "gut", "source-datasets", str(staged))
    assert started["state"] in ("queued", "uploading")
    assert started["job_id"] and started["target"] == "s3://hca-atlas-tracker-data-dev/gut/gut-v1/source-datasets/"
    assert [f["name"] for f in started["files"]] == ["a.h5ad", "b.h5ad"], "the response carries the plan being run"
    assert (started["files_total"], started["bytes_total"], started["up_to_date"]) == (2, 50_000, [])
    plan = uploads.plan("gut", "gut", "source-datasets", str(staged))
    assert set(plan) - set(started) == {"total_bytes", "total_size"}, "start carries every key of the plan"
    assert (started["atlas_folder"], started["prefix"], started["profile_source"]) == (
        plan["atlas_folder"],
        plan["prefix"],
        plan["profile_source"],
    )

    done = wait_for(uploads, started["job_id"], UPLOAD_ENDED, timeout=30)
    assert done["state"] == "done", done
    assert (done["files_done"], done["bytes_done"], done["uploaded"]) == (2, 50_000, ["a.h5ad", "b.h5ad"])
    assert done["message"] == "2 files uploaded and the manifest written"
    assert Path(done["manifest_path"]).parent == staged
    assert json.loads(Path(done["manifest_path"]).read_text())["files"] == ["a.h5ad", "b.h5ad"]
    prefix = fake_s3 / "hca-atlas-tracker-data-dev" / "gut/gut-v1/source-datasets"
    assert (prefix / "b.h5ad").read_bytes() == (staged / "b.h5ad").read_bytes()
    assert (prefix / "a.h5ad.sha256").read_text() == started["files"][0]["sha256"]
    assert list((fake_s3 / "hca-atlas-tracker-data-dev" / "gut/gut-v1/manifests").glob("manifest-*.json"))
    log = Path(done["log_path"]).read_text()
    assert "Successfully uploaded: b.h5ad" in log
    assert "current_file" not in done and "progress" not in done

    # Up to date now: nothing is started.
    again = uploads.start("gut", "gut", "source-datasets", str(staged))
    assert (again["job_id"], again["state"]) == (None, None)
    assert again["message"].startswith("Every .h5ad in") and "force=true" in again["message"]
    assert uploads.status()["jobs"][0]["job_id"] == started["job_id"]
    assert len(uploads.status()["jobs"]) == 1

    forced = uploads.start("gut", "gut", "source-datasets", str(staged), force=True)
    assert forced["job_id"] != started["job_id"]
    assert wait_for(uploads, forced["job_id"], UPLOAD_ENDED, timeout=30)["state"] == "done"
    assert [j["job_id"] for j in uploads.status()["jobs"]] == [forced["job_id"], started["job_id"]], "newest first"


def test_upload_in_flight_and_already_uploading(uploads, staged, monkeypatch):
    monkeypatch.setenv("HCA_TRACKER_FAKE_S3_DELAY", "0.6")
    started = uploads.start("gut", "gut", "source-datasets", str(staged))
    live = wait_for(uploads, started["job_id"], ("uploading",), timeout=30)
    assert live["current_file"] == "a.h5ad"
    assert live["progress"] == "a.h5ad 0%", "the transfer tool's own last line, from the log"
    assert "elapsed" in live
    duplicate = uploads.start("gut", "gut", "source-datasets", str(staged))
    assert (duplicate["job_id"], duplicate["message"]) == (started["job_id"], f"Already uploading from {staged}")
    assert wait_for(uploads, started["job_id"], UPLOAD_ENDED, timeout=30)["state"] == "done"


def test_partial_failure(uploads, staged, fake_s3):
    make_file(staged / "fail-c.h5ad", 1_000)
    started = uploads.start("gut", "gut", "source-datasets", str(staged))
    failed = wait_for(uploads, started["job_id"], UPLOAD_ENDED, timeout=30)
    assert failed["state"] == "failed"
    assert failed["message"].startswith("2 of 3 files uploaded; not uploaded: fail-c.h5ad.")
    assert (failed["files_done"], failed["uploaded"]) == (2, ["a.h5ad", "b.h5ad"])
    assert "manifest_path" in failed
    # Running again plans only what is missing.
    plan = uploads.plan("gut", "gut", "source-datasets", str(staged))
    assert ([f["name"] for f in plan["files"]], plan["up_to_date"]) == (["fail-c.h5ad"], ["a.h5ad", "b.h5ad"])


def test_interrupted_worker(uploads, staged, monkeypatch):
    monkeypatch.setenv("HCA_TRACKER_FAKE_S3_DELAY", "5")
    started = uploads.start("gut", "gut", "source-datasets", str(staged))
    wait_for(uploads, started["job_id"], ("uploading",), timeout=30)
    job = uploads.store.load(started["job_id"])
    assert job is not None and job.pid
    os.kill(job.pid, signal.SIGKILL)
    deadline = time.monotonic() + 10
    while worker_alive(job) and time.monotonic() < deadline:
        time.sleep(0.05)
    status = uploads.status(started["job_id"])
    assert status["state"] == "interrupted"
    assert status["message"].startswith(f"The upload worker (pid {job.pid}) stopped without finishing: 0 of 2 files")
    assert "start_upload again" in status["message"]
    # A record survives the Uploads instance: a new one (a new MCP process) sees the same job.
    fresh = Uploads(uploads.config)
    assert fresh.status(started["job_id"])["state"] == "interrupted"
    with pytest.raises(JobError, match="No upload job 'nope'"):
        fresh.status("nope")


def test_interrupted_job_does_not_block_its_folder(uploads, staged, monkeypatch):
    """A folder whose last job died is restarted, not reported as still uploading."""
    monkeypatch.setenv("HCA_TRACKER_FAKE_S3_DELAY", "5")
    started = uploads.start("gut", "gut", "source-datasets", str(staged))
    wait_for(uploads, started["job_id"], ("uploading",), timeout=30)
    job = uploads.store.load(started["job_id"])
    assert job is not None and job.pid
    os.kill(job.pid, signal.SIGKILL)
    deadline = time.monotonic() + 10
    while worker_alive(job) and time.monotonic() < deadline:
        time.sleep(0.05)
    monkeypatch.setenv("HCA_TRACKER_FAKE_S3_DELAY", "0")
    again = uploads.start("gut", "gut", "source-datasets", str(staged))
    assert again["job_id"] != started["job_id"] and again["state"] in ("queued", "uploading")
    assert uploads.status(started["job_id"])["state"] == "interrupted"
    assert wait_for(uploads, again["job_id"], UPLOAD_ENDED, timeout=30)["state"] == "done"


def test_start_refuses_without_a_transfer_tool(uploads, staged, monkeypatch):
    monkeypatch.setattr("hca_tracker_client.uploads.transfer_tool", lambda: None)
    plan = uploads.plan("gut", "gut", "source-datasets", str(staged))
    assert (plan["transfer_tool"], plan["warnings"]) == (
        None,
        ["Neither s5cmd nor aws is on PATH, so nothing can be transferred; install one"],
    )
    with pytest.raises(CheckError, match="Neither s5cmd nor aws is on PATH"):
        uploads.start("gut", "gut", "source-datasets", str(staged))
    assert uploads.status() == {"jobs": []}


def test_spawn_failure_is_recorded(uploads, staged, monkeypatch):
    def broken(*args, **kwargs):
        raise NotImplementedError("posix_spawn: unavailable")

    with monkeypatch.context() as patched:
        patched.setattr(os, "posix_spawn", broken)
        with pytest.raises(
            CheckError, match="The upload worker could not be started: NotImplementedError: posix_spawn"
        ):
            uploads.start("gut", "gut", "source-datasets", str(staged))
    (job,) = uploads.status()["jobs"]
    assert job["state"] == "failed"
    assert uploads.start("gut", "gut", "source-datasets", str(staged))["state"] in ("queued", "uploading")


def test_record_without_a_pid_is_retired_after_the_grace_period(uploads, staged):
    started = uploads.start("gut", "gut", "source-datasets", str(staged))
    wait_for(uploads, started["job_id"], UPLOAD_ENDED, timeout=30)
    job = uploads.store.load(started["job_id"])
    assert job is not None
    job.state, job.pid, job.created_at = "queued", None, time.time()
    uploads.store._write(job)  # a record whose spawn never completed, as a crash between create and update leaves it
    assert uploads.status(started["job_id"])["state"] == "queued"  # a fresh one is still within the grace period
    job.created_at = time.time() - 120
    uploads.store._write(job)
    assert uploads.status(started["job_id"])["message"] == "The upload worker was never started; run start_upload again"
    assert uploads.status(started["job_id"])["state"] == "interrupted"


def test_worker_holds_the_plan_it_was_given(uploads, staged, fake_s3):
    """The worker refuses a folder that changed since the plan, and reports files uploaded meanwhile as done."""
    from hca_tracker_client import upload_worker

    started = uploads.start("gut", "gut", "source-datasets", str(staged))
    wait_for(uploads, started["job_id"], UPLOAD_ENDED, timeout=30)
    job = uploads.store.load(started["job_id"])
    assert job is not None and job.state == "done"

    # Everything already in the bucket when the worker runs: done, not "0 of 2 uploaded".
    job.state, job.files_done, job.bytes_done, job.finished_at, job.manifest_path = "queued", [], 0, None, None
    uploads.store._write(job)
    assert upload_worker.run(job.job_id, uploads.config.cache_dir) == 0
    done = uploads.status(job.job_id)
    assert (done["state"], done["message"]) == (
        "done",
        "Every file was already in the bucket with the same SHA-256; nothing to upload",
    )
    assert (done["files_done"], done["bytes_done"]) == (2, 50_000), "the planned files count as done"

    # A file added, one rewritten (same size, new mtime) and one removed after the plan: refused, nothing uploaded.
    make_file(staged / "c.h5ad", 1_000)
    make_file(staged / "a.h5ad", 20_000)
    (staged / "b.h5ad").unlink()
    job.state, job.finished_at = "queued", None
    uploads.store._write(job)
    assert upload_worker.run(job.job_id, uploads.config.cache_dir) == 1
    failed = uploads.status(job.job_id)
    assert failed["state"] == "failed"
    assert failed["message"] == (
        "The folder changed since the plan: new c.h5ad; changed a.h5ad; missing b.h5ad; nothing was uploaded. "
        "Run start_upload again"
    )
    assert not (fake_s3 / "hca-atlas-tracker-data-dev" / "gut/gut-v1/source-datasets" / "c.h5ad").exists()
    assert "snapshot" not in failed and "snapshot" not in uploads.plan("gut", "gut", "source-datasets", str(staged))


def test_worker_outlives_the_caller(uploads, staged, monkeypatch, fake_s3):
    """The worker is in its own session: killing the process group of the caller does not reach it."""
    monkeypatch.setenv("HCA_TRACKER_FAKE_S3_DELAY", "0.5")
    started = uploads.start("gut", "gut", "source-datasets", str(staged))
    wait_for(uploads, started["job_id"], ("uploading",), timeout=30)  # the worker is up, so it has called setsid
    job = uploads.store.load(started["job_id"])
    assert job is not None and job.pid and os.getsid(job.pid) == job.pid, "the worker leads its own session"
    assert os.getsid(job.pid) != os.getsid(os.getpid())
    assert wait_for(uploads, started["job_id"], UPLOAD_ENDED, timeout=30)["state"] == "done"


def test_last_progress_line(tmp_path):
    """s5cmd appends frames with no separator when its output is a file; the AWS CLI uses carriage returns."""
    from hca_tracker_client.uploads import last_progress_line

    log = tmp_path / "job.log"
    assert last_progress_line(str(log)) is None
    log.write_text(
        "0.78%  ━─────  163.84 kB / 20.97 MB ? p/s ? (0/1)9.69%  ━━━───  2.03 MB / 20.97 MB ? p/s ? (0/1)"
        "42.81%  ━━━━──  8.98 MB / 20.97 MB (6.74 MB/s) 1s left (0/1)"
    )
    assert last_progress_line(str(log)) == "42.81%  ━━━━──  8.98 MB / 20.97 MB (6.74 MB/s) 1s left (0/1)"
    log.write_text(
        "Completed 1.0 MiB/4.8 GiB (6.1 MiB/s) with 1 file(s) remaining\r"
        "Completed 2.0 MiB/4.8 GiB (6.2 MiB/s) with 1 file(s) remaining\r"
    )
    assert last_progress_line(str(log)) == "Completed 2.0 MiB/4.8 GiB (6.2 MiB/s) with 1 file(s) remaining"
    log.write_text("\x1b[2Kfirst\x1b[Gsecond\n\n")
    assert last_progress_line(str(log)) == "second"
    log.write_bytes(b"x" * 10_000)
    assert len(last_progress_line(str(log)) or "") == 200


def test_upload_records_are_not_downloads(uploads, staged):
    """list_downloads and delete_download leave the upload store's records and logs alone."""
    from hca_tracker_client import Downloads

    started = uploads.start("gut", "gut", "source-datasets", str(staged))
    wait_for(uploads, started["job_id"], UPLOAD_ENDED, timeout=30)
    downloads = Downloads(uploads.config)
    assert downloads.list_files()["files"] == []
    with pytest.raises(JobError, match="is not in the download cache"):
        downloads.delete(started["log_path"])
    assert Path(started["log_path"]).exists()
    assert uploads.status(started["job_id"])["state"] == "done"


def test_worker_environment_has_no_token(monkeypatch):
    monkeypatch.setenv("HCA_TRACKER_API_TOKEN", "secret")
    monkeypatch.setenv("HCA_TRACKER_FAKE_S3", "/s3")
    env = module.worker_environment()
    assert "HCA_TRACKER_API_TOKEN" not in env and env["HCA_TRACKER_FAKE_S3"] == "/s3"


def test_job_stays_active_while_the_transfer_outlives_the_worker(uploads):
    """A killed worker's group still holds its transfer subprocess; the job is not retired under it."""
    from hca_tracker_client.daemon import group_commands
    from hca_tracker_client.uploads import UploadJob

    leader = os.posix_spawn(
        sys.executable,
        [
            sys.executable,
            "-c",
            "import os,subprocess,time; os.setsid(); subprocess.Popen(['sleep', '30']); time.sleep(30)",
        ],
        os.environ,
    )
    try:
        deadline = time.monotonic() + 10
        while not any("sleep 30" in command for command in group_commands(leader)) and time.monotonic() < deadline:
            time.sleep(0.05)
        os.kill(leader, signal.SIGKILL)
        os.waitpid(leader, 0)
        assert [command for command in group_commands(leader) if "sleep 30" in command]
        job = UploadJob(
            "x",
            "gut",
            "gut",
            "v1.0",
            "gut-v1",
            "source-datasets",
            "dev",
            "s3://b/p/",
            "/d",
            "p",
            "s5cmd",
            False,
            [],
            "/l",
        )
        job.pid = leader
        assert worker_alive(job) is True, "the transfer is still running"
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(leader, signal.SIGKILL)
    deadline = time.monotonic() + 10
    while group_commands(leader) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert worker_alive(job) is False


def test_store_never_rewrites_a_finished_record(cache_dir):
    store = UploadStore(cache_dir)
    assert store.update("nope", lambda job: None) is None
    assert store.end("nope", "done", "x") is None


def test_store_skips_a_record_from_an_older_version(uploads, cache_dir):
    """A record missing a field the dataclass now requires is unreadable, like a corrupt one, not fatal."""
    store = UploadStore(cache_dir)
    store.directory.mkdir(parents=True)
    (store.directory / "abc123.json").write_text(json.dumps({"job_id": "abc123", "state": "done", "created_at": 1.0}))
    (store.directory / "zzz999.json").write_text("{not json")
    assert store.load("abc123") is None
    assert store.all() == []
    assert uploads.status() == {"jobs": []}
    with pytest.raises(JobError, match="No upload job 'abc123'"):
        uploads.status("abc123")


# --- check_environment ---------------------------------------------------------


def test_environment_report(uploads, fake_s3, profile, monkeypatch):
    monkeypatch.setattr(module, "transfer_tool", REAL_TRANSFER_TOOL)  # CI has neither tool, a laptop usually has one
    report = environment_report(uploads.config)["upload"]
    assert report["smart_sync"]["ok"] is True and report["smart_sync"]["version"].startswith("0.4.")
    assert set(report["transfer_tools"]) == {"s5cmd", "aws", "selected"}
    selected = report["transfer_tools"]["selected"]
    for tool in ("s5cmd", "aws"):  # every installed tool is reported with its path and version (#738)
        entry = report["transfer_tools"][tool]
        assert set(entry) == ({"ok", "path", "version"} if entry["ok"] else {"ok"})
    assert selected == next((tool for tool in ("s5cmd", "aws") if report["transfer_tools"][tool]["ok"]), None)
    assert report["profile"] == {
        "ok": True,
        "name": "team-profile",
        "source": str(Path.home() / ".hca-smart-sync/config.yaml"),
    }
    assert report["bucket"] == {"ok": True, "environment": "dev", "name": "hca-atlas-tracker-data-dev"}
    assert report["can_upload"] is (selected is not None)

    (fake_s3 / "hca-atlas-tracker-data-dev" / "DENIED").touch()
    report = environment_report(uploads.config)["upload"]
    assert (
        report["bucket"]["ok"] is False and "cannot list s3://hca-atlas-tracker-data-dev/" in report["bucket"]["error"]
    )
    assert report["can_upload"] is False


def test_environment_report_without_profile_or_known_tracker(cache_dir, tracker, fake_s3, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("HCA_AWS_PROFILE", raising=False)
    config = make_config(cache_dir, tracker, upload_engine=FAKE_ENGINE)
    report = environment_report(config)["upload"]
    assert report["profile"]["ok"] is False and "No AWS profile" in report["profile"]["error"]
    assert report["bucket"]["ok"] is False and "HCA_TRACKER_ENVIRONMENT" in report["bucket"]["error"]
    assert report["can_upload"] is False
