"""HCA Tracker Client — find and download atlas files from the HCA Atlas Tracker."""

from .api import TrackerClient
from .catalog import INTEGRATED, SOURCE, list_atlases, list_files
from .config import Config, load_config
from .downloads import Downloads, environment_report
from .errors import AuthError, CheckError, ConfigError, JobError, SelectionError, TrackerError, redact
from .selection import atlas_version, find_file, select_atlas

__version__ = "0.1.0"

__all__ = [
    "INTEGRATED",
    "SOURCE",
    "AuthError",
    "CheckError",
    "Config",
    "ConfigError",
    "Downloads",
    "JobError",
    "SelectionError",
    "TrackerClient",
    "TrackerError",
    "atlas_version",
    "environment_report",
    "find_file",
    "list_atlases",
    "list_files",
    "load_config",
    "redact",
    "select_atlas",
]
