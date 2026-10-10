"""Configuration from the environment, falling back to a .env file."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .api import TrackerClient
from .errors import ConfigError

PREFIX = "HCA_TRACKER_"
DEFAULT_CACHE_DIR = Path("~/.cache/hca-tracker")
DEFAULT_MAX_CONCURRENT = 2
DEFAULT_UPLOAD_ENGINE = "hca_tracker_client.uploads:make_engine"
# The only engine factories HCA_TRACKER_UPLOAD_ENGINE may name: the value is imported, and it can
# come from a checked-out .env, so an arbitrary import target would be code execution by a repo.
UPLOAD_ENGINES = (DEFAULT_UPLOAD_ENGINE, "hca_tracker_client.testing:FakeSmartSync")
ENVIRONMENTS = ("dev", "prod")


@dataclass(frozen=True)
class Config:
    """Settings for the tracker and the download cache.

    ``api_token`` is kept out of ``repr`` so a logged or printed config never
    shows it.
    """

    tracker_url: str | None
    api_token: str | None = field(repr=False)
    cache_dir: Path
    max_concurrent: int
    # Which environment the tracker is (dev or prod), when its host is not one of the two known
    # ones; decides the bucket uploads may go to. None: decide from the host.
    tracker_environment: str | None = None
    # ``module:attribute`` of the upload engine factory, one of UPLOAD_ENGINES; tests point it at the fake.
    upload_engine: str = DEFAULT_UPLOAD_ENGINE

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

    def tracker_client(self) -> TrackerClient:
        """A tracker API client for this config; raises if the URL or token is unset."""
        return TrackerClient(*self.require_tracker())


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
    values = {**file_values, **{k: v for k, v in environ.items() if k.startswith(PREFIX)}}

    cache_dir = Path(values.get("HCA_TRACKER_CACHE_DIR") or DEFAULT_CACHE_DIR).expanduser().resolve()
    max_concurrent = int(_number(values, "HCA_TRACKER_MAX_CONCURRENT", DEFAULT_MAX_CONCURRENT, int))
    environment = values.get("HCA_TRACKER_ENVIRONMENT") or None
    if environment is not None and environment not in ENVIRONMENTS:
        raise ConfigError(f"HCA_TRACKER_ENVIRONMENT must be one of {', '.join(ENVIRONMENTS)}, got {environment!r}")
    engine = values.get("HCA_TRACKER_UPLOAD_ENGINE") or DEFAULT_UPLOAD_ENGINE
    if engine not in UPLOAD_ENGINES:
        raise ConfigError(f"HCA_TRACKER_UPLOAD_ENGINE must be one of {', '.join(UPLOAD_ENGINES)}, got {engine!r}")
    return Config(
        tracker_url=values.get("HCA_TRACKER_URL"),
        api_token=values.get("HCA_TRACKER_API_TOKEN"),
        cache_dir=cache_dir,
        max_concurrent=max_concurrent,
        tracker_environment=environment,
        upload_engine=engine,
    )
