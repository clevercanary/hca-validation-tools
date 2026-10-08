"""A local stand-in for the tracker API and its S3 bucket, for tests.

Serves ``/api/atlases`` and friends with the tracker's field names, issues
presigned-style links that can be expired, and serves file bytes with Range
support and the ``x-amz-meta-source-sha256`` header, as S3 does for files
uploaded with hca-smart-sync.
"""

import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .api import SHA256_HEADER


@dataclass
class _Blob:
    file_id: str
    name: str
    path: Path
    sha256: str | None


@dataclass
class FakeTracker:
    """Run with ``with FakeTracker() as tracker:``; ``tracker.url`` is the base URL."""

    token: str = "test-token"
    atlases: list[dict] = field(default_factory=list)
    files: dict[str, dict[str, list[dict]]] = field(default_factory=dict)
    blobs: dict[str, _Blob] = field(default_factory=dict)
    links: set[str] = field(default_factory=set)
    rate_bps: int = 0
    served_bytes: int = 0

    def add_atlas(self, network: str, slug: str, generation: int, revision: int, published: bool = False) -> str:
        atlas_id = f"atlas-{len(self.atlases) + 1}"
        self.atlases.append(
            {
                "id": atlas_id,
                "bioNetwork": network,
                "shortNameSlug": slug,
                "generation": generation,
                "revision": revision,
                "publishedAt": "2026-01-01T00:00:00Z" if published else None,
            }
        )
        for a in self.atlases:
            same = [
                b
                for b in self.atlases
                if (b["bioNetwork"], b["shortNameSlug"], b["generation"])
                == (a["bioNetwork"], a["shortNameSlug"], a["generation"])
            ]
            a["isLatest"] = a["revision"] == max(b["revision"] for b in same)
        self.files[atlas_id] = {"integrated": [], "source": []}
        return atlas_id

    def add_file(
        self,
        atlas_id: str,
        name: str,
        path: Path,
        kind: str = "integrated",
        sha256: str | None | bool = True,
        integrity: str = "valid",
        listed_size: int | None = None,
    ) -> str:
        """Link a file to an atlas version.

        ``sha256=True`` serves the file's real checksum, a string serves that
        value (to force a mismatch), and None serves no checksum header.
        """
        file_id = f"file-{len(self.blobs) + 1}"
        if sha256 is True:
            sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        self.blobs[file_id] = _Blob(file_id, name, path, sha256 or None)
        size = path.stat().st_size if listed_size is None else listed_size
        self.files[atlas_id][kind].append(
            {"fileId": file_id, "fileName": name, "sizeBytes": size, "integrityStatus": integrity}
        )
        return file_id

    def expire_links(self) -> None:
        """Make every presigned link issued so far answer 403."""
        self.links.clear()

    # -- server --------------------------------------------------------------

    def __enter__(self) -> "FakeTracker":
        tracker = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _json(self, code: int, body) -> None:
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _authorized(self) -> bool:
                if self.headers.get("Authorization") == f"Bearer {tracker.token}":
                    return True
                self._json(401, {"message": "Unauthorized"})
                return False

            def do_POST(self):
                parts = urlparse(self.path).path.strip("/").split("/")
                if not self._authorized():
                    return None
                # api/atlases/<id>/files/<file_id>/presigned-url
                if len(parts) == 6 and parts[:2] == ["api", "atlases"] and parts[5] == "presigned-url":
                    blob = tracker.blobs.get(parts[4])
                    if blob is None:
                        return self._json(404, {})
                    signature = secrets.token_hex(8)
                    tracker.links.add(signature)
                    url = f"{tracker.url}/s3/{blob.file_id}?X-Amz-Signature={signature}"
                    return self._json(200, {"url": url, "filename": blob.name})
                return self._json(404, {})

            def do_GET(self):
                parsed = urlparse(self.path)
                parts = parsed.path.strip("/").split("/")
                if parts[0] == "s3":
                    return self._object(parts[1], parse_qs(parsed.query).get("X-Amz-Signature", [""])[0])
                if not self._authorized():
                    return None
                if parts == ["api", "atlases"]:
                    return self._json(200, tracker.atlases)
                if len(parts) == 4 and parts[:2] == ["api", "atlases"] and parts[2] in tracker.files:
                    kind = {"component-atlases": "integrated", "source-datasets": "source"}.get(parts[3])
                    if kind:
                        return self._json(200, tracker.files[parts[2]][kind])
                return self._json(404, {})

            def _object(self, file_id: str, signature: str) -> None:
                blob = tracker.blobs.get(file_id)
                if blob is None or signature not in tracker.links:
                    body = b"<Error><Code>AccessDenied</Code><Message>Request has expired</Message></Error>"
                    self.send_response(403)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                total = blob.path.stat().st_size
                start, end = 0, total - 1
                requested = self.headers.get("Range")
                if requested:
                    first, _, last = requested.split("=", 1)[1].partition("-")
                    start, end = int(first), int(last) if last else total - 1
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
                else:
                    self.send_response(200)
                self.send_header("Content-Length", str(end - start + 1))
                self.send_header("Accept-Ranges", "bytes")
                if blob.sha256:
                    self.send_header(SHA256_HEADER, blob.sha256)
                self.end_headers()
                with blob.path.open("rb") as handle:
                    handle.seek(start)
                    left = end - start + 1
                    while left > 0:
                        chunk = handle.read(min(65536, left))
                        if not chunk:
                            break
                        try:
                            self.wfile.write(chunk)
                        except (BrokenPipeError, ConnectionResetError):
                            return
                        tracker.served_bytes += len(chunk)
                        left -= len(chunk)
                        if tracker.rate_bps:
                            time.sleep(len(chunk) / tracker.rate_bps)

        class Server(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                pass  # clients (aria2) drop connections mid-transfer on cancel

        self._server = Server(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()
