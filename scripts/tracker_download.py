#!/usr/bin/env python3
"""Download the latest files of an atlas from the HCA Atlas Tracker.

Reads HCA_TRACKER_URL and HCA_TRACKER_API_TOKEN from the repo-root .env (or the
environment). Never prints the token or presigned URLs; output is file names,
sizes and paths only.

Usage:
    scripts/tracker_download.py --list-atlases
    scripts/tracker_download.py <short-name-slug> [--generation N] [--network NAME] [--published]
                                [--type integrated|source|all] [--out DIR] [--list] [--match SUBSTRING]

Picks the newest revision of the requested generation (default: newest generation),
e.g. `brain --generation 1` -> v1.0 even though v3.5 exists.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHUNK_SIZE = 1024 * 1024


def load_env() -> tuple[str, str]:
    """Return (tracker URL, token) from the environment, falling back to .env."""
    env_file = REPO_ROOT / ".env"
    file_values: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            file_values[key.strip()] = value.strip().strip("'\"")
    url = os.environ.get("HCA_TRACKER_URL") or file_values.get("HCA_TRACKER_URL")
    token = os.environ.get("HCA_TRACKER_API_TOKEN") or file_values.get("HCA_TRACKER_API_TOKEN")
    if not url or not token:
        sys.exit("HCA_TRACKER_URL and HCA_TRACKER_API_TOKEN must be set in .env")
    return url.rstrip("/"), token


def api(base: str, token: str, path: str, method: str = "GET"):
    """Call the tracker API and return parsed JSON; exit with a clear message on auth errors."""
    request = urllib.request.Request(
        f"{base}{path}",
        method=method,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 401:
            sys.exit(
                f"Token expired or invalid; create a new one at {base}/api-token "
                "and update HCA_TRACKER_API_TOKEN in .env"
            )
        if error.code == 403:
            sys.exit(f"Forbidden: {method} {path} (tokens are read-only)")
        sys.exit(f"Tracker API error {error.code} on {method} {path}")


def pick_atlas(
    atlases: list,
    slug: str,
    network: str | None,
    generation: int | None,
    published: bool,
) -> dict:
    """Pick the newest revision of the requested generation (default: newest generation).

    The tracker's isLatest marks the newest revision within each generation, so
    with --generation N this is the isLatest version of generation N. With
    --published, only published versions are considered.
    """
    versions = [a for a in atlases if a.get("shortNameSlug") == slug]
    if not versions:
        known = sorted({a.get("shortNameSlug") for a in atlases if a.get("shortNameSlug")})
        sys.exit(f"No atlas with slug {slug!r}. Known slugs: {', '.join(known)}")
    if network:
        versions = [a for a in versions if a.get("bioNetwork") == network]
        if not versions:
            sys.exit(f"No atlas {slug!r} in network {network!r}")
    networks = sorted({a.get("bioNetwork") for a in versions})
    if len(networks) > 1:
        sys.exit(f"Atlas slug {slug!r} exists in several networks ({', '.join(networks)}); pass --network")
    if generation is not None:
        versions = [a for a in versions if a["generation"] == generation]
        if not versions:
            sys.exit(f"Atlas {slug!r} has no generation {generation}")
    if published:
        versions = [a for a in versions if a.get("publishedAt")]
        if not versions:
            sys.exit(f"Atlas {slug!r} has no published version matching that request")
    return max(versions, key=lambda a: (a["generation"], a["revision"]))


def human_size(size: int) -> str:
    """Format a byte count for display."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def download(url: str, dest: Path, expected_size: int) -> None:
    """Stream a presigned URL to dest via a .part file, checking the size."""
    part = dest.with_name(dest.name + ".part")
    try:
        with urllib.request.urlopen(url) as response, part.open("wb") as out:
            while chunk := response.read(CHUNK_SIZE):
                out.write(chunk)
    except urllib.error.URLError as error:
        part.unlink(missing_ok=True)
        sys.exit(f"Download failed for {dest.name}: {error}")
    actual = part.stat().st_size
    if expected_size and actual != expected_size:
        part.unlink()
        sys.exit(f"Size mismatch for {dest.name}: expected {expected_size}, got {actual}")
    part.rename(dest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("slug", nargs="?", help="Atlas short name slug, e.g. gut")
    parser.add_argument("--list-atlases", action="store_true", help="List atlas slugs and versions")
    parser.add_argument("--generation", type=int, help="Atlas generation (e.g. 1 for v1.x); default: newest")
    parser.add_argument("--network", help="Bionetwork, needed only if the slug exists in several networks")
    parser.add_argument("--published", action="store_true", help="Only consider published versions")
    parser.add_argument("--type", choices=["integrated", "source", "all"], default="integrated")
    parser.add_argument("--match", help="Only files whose name contains this substring")
    parser.add_argument("--list", action="store_true", help="List files without downloading")
    parser.add_argument("--out", type=Path, default=Path("downloads"), help="Output directory")
    args = parser.parse_args()

    base, token = load_env()
    atlases = api(base, token, "/api/atlases")

    if args.list_atlases:
        for a in sorted(atlases, key=lambda a: (a.get("shortNameSlug") or "", a["generation"], a["revision"])):
            flags = " ".join(f for f, on in (("latest", a.get("isLatest")), ("published", a.get("publishedAt"))) if on)
            print(f"{a.get('shortNameSlug')}\t{a.get('bioNetwork')}\tv{a['generation']}.{a['revision']}\t{flags}")
        return
    if not args.slug:
        parser.error("slug is required unless --list-atlases is given")

    atlas = pick_atlas(atlases, args.slug, args.network, args.generation, args.published)
    version = f"v{atlas['generation']}.{atlas['revision']}"
    print(f"Atlas {args.slug} {version} ({'published' if atlas.get('publishedAt') else 'unpublished'})")

    files = []
    if args.type in ("integrated", "all"):
        files += api(base, token, f"/api/atlases/{atlas['id']}/component-atlases")
    if args.type in ("source", "all"):
        files += api(base, token, f"/api/atlases/{atlas['id']}/source-datasets")
    files = [f for f in files if f.get("fileId")]
    if args.match:
        files = [f for f in files if args.match in (f.get("fileName") or "")]
    if not files:
        print("No matching files")
        return

    out_dir = args.out / f"{args.slug}_{version}"
    for f in files:
        size = int(f.get("sizeBytes") or 0)
        if args.list:
            print(f"  {f.get('fileName')}\t{human_size(size)}")
            continue
        info = api(base, token, f"/api/atlases/{atlas['id']}/files/{f['fileId']}/presigned-url", "POST")
        dest = out_dir / info["filename"]
        if dest.exists() and dest.stat().st_size == size:
            print(f"  skip  {dest} (already downloaded)")
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"  get   {info['filename']} ({human_size(size)})", flush=True)
        download(info["url"], dest, size)
        print(f"  saved {dest}")


if __name__ == "__main__":
    main()
