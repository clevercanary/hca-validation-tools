"""Rewrite an h5ad file with HDF5 compression applied to all chunked datasets."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Literal

import h5py

from . import __version__
from ._io import open_h5ad
from .write import resolve_latest, write_h5ad


def _detect_x_compression(path: str) -> str | None:
    """Return the h5py filter name on X/data (or dense X), or None if uncompressed."""
    with h5py.File(path, "r") as f:
        x = f.get("X")
        if x is None:
            return None
        target = x["data"] if isinstance(x, h5py.Group) and "data" in x else x
        return getattr(target, "compression", None)


def compress_h5ad(
    path: str,
    compression: Literal["gzip"] = "gzip",
    compression_level: int = 4,
    force: bool = False,
) -> dict:
    """Rewrite an h5ad file with HDF5 compression applied to chunked datasets.

    Uses anndata to read the source and write a new file with the requested
    compression filter applied to all chunked datasets (X, layers, obsm,
    obsp, varm, varp, and categorical codes in obs/var). The output is
    written as an edit snapshot (`<stem>-edit-<ts>.h5ad`) and the operation
    is logged in `uns['provenance']['edit_history']`.

    Skips by default if X/data already has a compression filter; pass
    force=True to rewrite anyway (e.g. to change the level).

    Args:
        path: Path to an .h5ad file.
        compression: Compression filter. Only 'gzip' is supported.
        compression_level: gzip level 0-9 (0 = no compression). Defaults to 4.
        force: Rewrite even if the file is already compressed.

    Returns:
        Dict with 'output_path', 'size_before_bytes', 'size_after_bytes',
        'ratio', 'compression' on success; {'skipped': True, 'reason': ...}
        if already compressed; or {'error': ...} on failure.
    """
    try:
        path = resolve_latest(path)

        # Reachable via MCP/JSON where the Literal type narrowing doesn't apply at runtime.
        if compression != "gzip":  # pyright: ignore[reportUnnecessaryComparison, reportUnreachable]
            return {"error": f"Unsupported compression '{compression}' (only 'gzip' is supported)"}  # pyright: ignore[reportUnreachable]
        if not 0 <= compression_level <= 9:
            return {"error": f"compression_level must be 0-9, got {compression_level}"}

        current_filter = _detect_x_compression(path)
        if current_filter and not force:
            return {
                "skipped": True,
                "reason": (
                    f"X/data already uses '{current_filter}' filter "
                    f"(pass force=True to rewrite anyway)"
                ),
                "current_compression": current_filter,
            }

        size_before = os.path.getsize(path)

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool": "hca-anndata-tools",
            "tool_version": __version__,
            "operation": "compress_h5ad",
            "description": f"Rewrote file with {compression}:{compression_level} compression",
            "details": {
                "compression": compression,
                "compression_level": compression_level,
                "previous_compression": current_filter,
                "size_before_bytes": size_before,
            },
        }

        with open_h5ad(path, backed="r") as adata:
            result = write_h5ad(
                adata, path, [entry],
                compression=compression,
                compression_opts=compression_level,
            )

        if "error" in result:
            return result

        size_after = os.path.getsize(result["output_path"])

        return {
            "output_path": result["output_path"],
            "size_before_bytes": size_before,
            "size_after_bytes": size_after,
            "ratio": round(size_before / size_after, 2) if size_after else None,
            "compression": f"{compression}:{compression_level}",
        }

    except Exception as e:
        return {"error": str(e)}
