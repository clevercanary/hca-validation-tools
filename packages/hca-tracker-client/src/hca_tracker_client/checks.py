"""Checks run before a download starts. Each fails with a message that says what to do."""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .errors import CheckError

MIN_ARIA2_VERSION = (1, 35, 0)
INSTALL_HINT = (
    "install aria2: `brew install aria2` (macOS), `apt install aria2` (Debian/Ubuntu), "
    "`dnf install aria2` (Fedora; RHEL and Amazon Linux 2 need EPEL), "
    "or `conda install -c conda-forge aria2`"
)
GB = 1_000_000_000
MIN_MARGIN = 5 * GB
MARGIN_FRACTION = 0.10


def human_size(size: float) -> str:
    """Format a byte count in decimal units, e.g. ``63.1 GB``."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(value) < 1000:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1000
    return f"{value:.1f} TB"


def human_duration(seconds: float) -> str:
    """Format a duration, e.g. ``1h 05m`` or ``4m 10s``."""
    seconds = round(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def parse_aria2_version(output: str) -> tuple[int, int, int] | None:
    match = re.search(r"aria2 version (\d+)\.(\d+)\.(\d+)", output)
    if not match:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def find_aria2c() -> tuple[str, str]:
    """Return (path, version) of a working aria2c of at least MIN_ARIA2_VERSION."""
    path = shutil.which("aria2c")
    if not path:
        raise CheckError(f"aria2c not found on PATH; {INSTALL_HINT}")
    try:
        result = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as error:
        raise CheckError(f"aria2c at {path} does not run ({error}); {INSTALL_HINT}") from None
    version = parse_aria2_version(result.stdout)
    if result.returncode != 0 or version is None:
        raise CheckError(f"aria2c at {path} does not report a version; {INSTALL_HINT}")
    if version < MIN_ARIA2_VERSION:
        found = ".".join(map(str, version))
        needed = ".".join(map(str, MIN_ARIA2_VERSION))
        raise CheckError(f"aria2c {found} at {path} is older than the minimum {needed}; {INSTALL_HINT}")
    return path, ".".join(map(str, version))


def check_writable(directory: Path) -> None:
    """Create the directory if needed and prove it is writable with a test file."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        # An unpredictable name created exclusively, so a planted symlink is never followed.
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".hca-tracker-write-test-"):
            pass
    except OSError as error:
        raise CheckError(f"Folder {directory} is not writable: {error.strerror or error}") from None


def existing_ancestor(path: Path) -> Path:
    """The path itself or its nearest existing parent."""
    path = path.absolute()
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def free_bytes(path: Path) -> int:
    """Free space on the filesystem holding path (or would hold it, once created)."""
    return shutil.disk_usage(existing_ancestor(path)).free


def margin(size: int) -> int:
    """Headroom kept free beyond what downloads need: 10% of the file or 5 GB, whichever is larger."""
    return max(int(size * MARGIN_FRACTION), MIN_MARGIN)


def check_space(directory: Path, remaining: int, size: int, reserved: int) -> int:
    """Fail unless free space covers this download, other downloads' reservations, and the margin.

    ``remaining`` is what this download still has to fetch; ``size`` is the
    whole file, which sets the margin. Returns the free byte count.
    """
    free = free_bytes(directory)
    needed = remaining + reserved + margin(size)
    if needed > free:
        detail = f" (including {human_size(reserved)} reserved for other downloads)" if reserved else ""
        raise CheckError(
            f"Not enough space: needs {human_size(needed)}{detail}, "
            f"{human_size(free)} free on {existing_ancestor(directory)}"
        )
    return free
