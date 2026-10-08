from pathlib import Path

import pytest

from hca_tracker_client import ConfigError, load_config


def test_defaults(tmp_path):
    config = load_config(env={}, env_file=tmp_path / ".env")
    assert config.cache_dir == Path("~/.cache/hca-tracker").expanduser()
    assert config.max_concurrent == 2
    with pytest.raises(ConfigError, match="HCA_TRACKER_URL and HCA_TRACKER_API_TOKEN must be set"):
        config.require_tracker()


def test_env_file_supplies_only_tracker_keys(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GOOGLE_SERVICE_ACCOUNT='{\"secret\": 1}'\n"
        "# comment\n"
        "HCA_TRACKER_URL=https://tracker.example/\n"
        "export HCA_TRACKER_API_TOKEN='from-file'\n"
        "HCA_TRACKER_MAX_CONCURRENT=3\n"
    )
    config = load_config(env={"HCA_TRACKER_API_TOKEN": "from-env"}, env_file=env_file)
    assert config.require_tracker() == ("https://tracker.example", "from-env")
    assert config.max_concurrent == 3


def test_token_not_in_repr(tmp_path):
    config = load_config(env={"HCA_TRACKER_API_TOKEN": "s3cret"}, env_file=tmp_path / ".env")
    assert "s3cret" not in repr(config)


def test_bad_number(tmp_path):
    with pytest.raises(ConfigError, match="HCA_TRACKER_MAX_CONCURRENT must be a number"):
        load_config(env={"HCA_TRACKER_MAX_CONCURRENT": "two"}, env_file=tmp_path / ".env")
