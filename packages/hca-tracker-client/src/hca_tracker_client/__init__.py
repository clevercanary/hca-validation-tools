"""HCA Tracker Client — find and download atlas files from the HCA Atlas Tracker.

This library exists to back hca-tracker-mcp, so its error messages name the
MCP tools to call next (``start_download``, ``delete_download``, ...). Each
maps to a ``Downloads`` method of the same purpose.
"""

from .api import TrackerClient
from .catalog import MAX_MESSAGES, get_atlas, list_atlases, list_files, validation_report
from .config import Config, load_config
from .downloads import Downloads, environment_report
from .errors import AuthError, CheckError, ConfigError, JobError, SelectionError, TrackerError, redact
from .selection import INTEGRATED, SOURCE, atlas_version, find_file, select_atlas
from .status import cap_status, tier1_status

__version__ = "0.2.0"

__all__ = [
    "INTEGRATED",
    "MAX_MESSAGES",
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
    "cap_status",
    "environment_report",
    "find_file",
    "get_atlas",
    "list_atlases",
    "list_files",
    "load_config",
    "redact",
    "select_atlas",
    "tier1_status",
    "validation_report",
]
