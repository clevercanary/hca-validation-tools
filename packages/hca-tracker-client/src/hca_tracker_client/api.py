"""HCA Atlas Tracker API calls, and the probe of a presigned download URL."""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .errors import AuthError, CheckError, TrackerError, redact

SHA256_HEADER = "x-amz-meta-source-sha256"


@dataclass(frozen=True)
class Presigned:
    """A presigned download URL and the versioned file name to save it as.

    ``url`` carries its own credentials. It is passed to aria2 over RPC and
    never returned, logged, or put in an error message.
    """

    url: str
    filename: str

    def __repr__(self) -> str:
        return f"Presigned(filename={self.filename!r})"


@dataclass(frozen=True)
class Probe:
    """What a 1-byte ranged GET of a presigned URL reports."""

    size: int | None
    sha256: str | None


class TrackerClient:
    """Read-only client for the tracker API, authenticated with an API token."""

    def __init__(self, base_url: str, token: str, timeout: float = 60):
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout = timeout

    def _request(self, path: str, method: str = "GET") -> Any:
        request = urllib.request.Request(
            f"{self.base_url}{path}", method=method, headers={"Accept": "application/json"}
        )
        # Unredirected, so urllib never forwards the token if the tracker redirects to another host.
        request.add_unredirected_header("Authorization", f"Bearer {self._token}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 401:
                raise AuthError(
                    f"Tracker token expired or invalid; create a new one at {self.base_url}/api-token "
                    "and update HCA_TRACKER_API_TOKEN"
                ) from None
            if error.code == 403:
                raise AuthError(f"Forbidden: {method} {path} (tracker API tokens are read-only)") from None
            raise TrackerError(f"Tracker API error {error.code} on {method} {path}", status=error.code) from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise TrackerError(redact(f"Tracker not reachable at {self.base_url}: {reason}", self._token)) from None

    def list_atlases(self) -> list[dict]:
        """Every atlas version the token can see."""
        return self._request("/api/atlases")

    def component_atlases(self, atlas_id: str) -> list[dict]:
        """The integrated-object file revisions linked to one atlas version."""
        return self._request(f"/api/atlases/{atlas_id}/component-atlases")

    def source_datasets(self, atlas_id: str) -> list[dict]:
        """The source-dataset file revisions linked to one atlas version."""
        return self._request(f"/api/atlases/{atlas_id}/source-datasets")

    def component_atlas(self, atlas_id: str, component_atlas_id: str) -> dict:
        """One integrated object with its ``validationReports``; the id is the entry's ``id``, not its ``fileId``."""
        return self._request(f"/api/atlases/{atlas_id}/component-atlases/{component_atlas_id}")

    def source_dataset(self, atlas_id: str, source_dataset_id: str) -> dict:
        """One source dataset with its ``validationReports``; the id is the entry's ``id``, not its ``fileId``."""
        return self._request(f"/api/atlases/{atlas_id}/source-datasets/{source_dataset_id}")

    def users(self) -> list[dict]:
        """Every tracker user (readable by any READ-group role, so by an API token)."""
        return self._request("/api/users")

    def presigned_url(self, atlas_id: str, file_id: str) -> Presigned:
        """A fresh presigned download URL for one file (valid for 48 hours)."""
        info = self._request(f"/api/atlases/{atlas_id}/files/{file_id}/presigned-url", method="POST")
        return Presigned(url=info["url"], filename=info["filename"])


def probe(presigned: Presigned, timeout: float = 60) -> Probe:
    """Fetch the first byte of a presigned URL to confirm access.

    Reads the object's total size from ``Content-Range`` and the checksum that
    hca-smart-sync attaches on upload from ``x-amz-meta-source-sha256``.
    """
    request = urllib.request.Request(presigned.url, headers={"Range": "bytes=0-0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read(1)
            headers = response.headers
    except urllib.error.HTTPError as error:
        reason = {
            404: "is not in storage (still uploading?)",
            416: "is empty on the server",
        }.get(error.code, f"was refused (HTTP {error.code})")
        raise CheckError(f"The file {presigned.filename} {reason}; nothing was downloaded") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        reason = redact(str(getattr(error, "reason", error)))
        raise CheckError(f"Could not reach the download link for {presigned.filename}: {reason}") from None

    size = None
    content_range = headers.get("Content-Range")
    if content_range and "/" in content_range:
        total = content_range.rsplit("/", 1)[1]
        if total.isdigit():
            size = int(total)
    sha256 = (headers.get(SHA256_HEADER) or "").strip().lower() or None
    return Probe(size=size, sha256=sha256)
