"""Configuration from the environment, falling back to a .env file."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigError

PREFIX = "HCA_TRACKER_"
DEFAULT_CACHE_DIR = Path("~/.cache/hca-tracker")
DEFAULT_CONFIRM_GB = 5.0
DEFAULT_MAX_CONCURRENT = 2


@dataclass(frozen=True)
class Config:
    """Settings for the tracker and the download cache.

    ``api_token`` is kept out of ``repr`` so a logged or printed config never
    shows it.
    """

    tracker_url: str | None
    api_token: str | None = field(repr=False)
    cache_dir: Path
    confirm_bytes: int
    max_concurrent: int

    def require_tracker(self) -> tuple[str, str]:
        """Return (tracker URL, token), or raise if either is unset."""
        missing = [
            name
            for name, value in (("HCA_TRACKER_URL", self.tracker_url), ("HCA_TRACKER_API_TOKEN", self.api_token))
            if not value
        ]
        if missing:
            raise ConfigError(
                f"{' and '.join(missing)} must be set, in the MCP server's environment or in a .env file "
                "in its working directory"
            )
        assert self.tracker_url and self.api_token
        return self.tracker_url.rstrip("/"), self.api_token


def read_env_file(path: Path) -> dict[str, str]:
    """Read HCA_TRACKER_* keys from a .env file, ignoring every other key.

    The repo .env also holds unrelated credentials (the Google service
    account), which this package has no reason to load.
    """
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        if key.startswith(PREFIX):
            values[key] = value.strip().strip("'\"")
    return values


def _number(values: Mapping[str, str], key: str, default: float, cast: type) -> float:
    raw = values.get(key)
    if raw is None or raw == "":
        return default
    try:
        number = cast(raw)
    except ValueError:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from None
    if number <= 0:
        raise ConfigError(f"{key} must be greater than 0, got {raw!r}")
    return number


def load_config(env: Mapping[str, str] | None = None, env_file: Path | None = None) -> Config:
    """Build the config from the environment, with a .env file as fallback.

    Values in the environment win over the file. ``env_file`` defaults to
    ``.env`` in the working directory, which for a project MCP server is the
    repo root.
    """
    environ = os.environ if env is None else env
    file_values = read_env_file(env_file if env_file is not None else Path.cwd() / ".env")
    values = {**file_values, **{k: v for k, v in environ.items() if k.startswith(PREFIX) and v}}

    cache_dir = Path(values.get("HCA_TRACKER_CACHE_DIR") or DEFAULT_CACHE_DIR).expanduser()
    confirm_gb = _number(values, "HCA_TRACKER_CONFIRM_GB", DEFAULT_CONFIRM_GB, float)
    max_concurrent = int(_number(values, "HCA_TRACKER_MAX_CONCURRENT", DEFAULT_MAX_CONCURRENT, int))
    return Config(
        tracker_url=values.get("HCA_TRACKER_URL"),
        api_token=values.get("HCA_TRACKER_API_TOKEN"),
        cache_dir=cache_dir,
        confirm_bytes=int(confirm_gb * 1e9),
        max_concurrent=max_concurrent,
    )
