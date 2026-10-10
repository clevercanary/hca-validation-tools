"""HCA Tracker Client — find and download atlas files from the HCA Atlas Tracker.

This library exists to back hca-tracker-mcp, so its error messages name the
MCP tools to call next (``start_download``, ``delete_download``, ...). Each
maps to a ``Downloads`` method of the same purpose; the upload tools
(``plan_upload``, ``start_upload``, ``upload_status``) to ``Uploads`` methods.
"""

from .api import TrackerClient
from .catalog import MAX_MESSAGES, get_atlas, list_atlases, list_files, validation_report
from .config import Config, load_config
from .downloads import Downloads, environment_report
from .errors import AuthError, CheckError, ConfigError, JobError, SelectionError, TrackerError, redact
from .selection import INTEGRATED, SOURCE, atlas_version, find_file, select_atlas
from .status import cap_status, tier1_status
from .uploads import INTEGRATED_OBJECTS, SOURCE_DATASETS, Uploads

__version__ = "0.3.0"

__all__ = [
    "INTEGRATED",
    "INTEGRATED_OBJECTS",
    "MAX_MESSAGES",
    "SOURCE",
    "SOURCE_DATASETS",
    "AuthError",
    "CheckError",
    "Config",
    "ConfigError",
    "Downloads",
    "JobError",
    "SelectionError",
    "TrackerClient",
    "TrackerError",
    "Uploads",
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
