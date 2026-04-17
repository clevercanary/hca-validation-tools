"""HDF5 storage details for an AnnData file."""

import os

import h5py

from .write import resolve_latest


def _dataset_info(ds: h5py.Dataset) -> dict:
    """Extract storage info from an HDF5 dataset."""
    return {
        "dtype": str(ds.dtype),
        "shape": list(ds.shape),
        "compression": ds.compression,
        "compression_opts": ds.compression_opts,
        "chunks": list(ds.chunks) if ds.chunks else None,
        "size_bytes": ds.id.get_storage_size(),
    }


def _group_info(group: h5py.Group) -> dict:
    """Extract storage info from an HDF5 group (e.g. sparse matrix)."""
    result = {"format": group.attrs.get("encoding-type", "unknown")}
    for key in sorted(group.keys()):
        item = group[key]
        if isinstance(item, h5py.Dataset):
            result[key] = _dataset_info(item)
    return result


def _inspect_item(f: h5py.File, name: str) -> dict | None:
    """Inspect a top-level item, handling both datasets and groups."""
    if name not in f:
        return None
    item = f[name]
    if isinstance(item, h5py.Dataset):
        return _dataset_info(item)
    elif isinstance(item, h5py.Group):
        return _group_info(item)
    return None


def get_storage_info(path: str) -> dict:
    """Get HDF5 storage details for an AnnData .h5ad file.

    Returns file size, compression settings, chunk sizes, and sparse format
    for X, raw/X, and all layers.

    Args:
        path: Absolute path to an .h5ad file.
    """
    try:
        if not path.endswith(".h5ad"):
            return {"error": "Only .h5ad files supported (not zarr)"}

        path = resolve_latest(path)
        file_bytes = os.path.getsize(path)
        result = {
            "file_size_bytes": file_bytes,
            "file_size_mb": round(file_bytes / (1024 * 1024), 1),
        }

        with h5py.File(path, "r") as f:
            result["X"] = _inspect_item(f, "X")
            result["raw_X"] = _inspect_item(f, "raw/X")

            layers = {}
            if "layers" in f and isinstance(f["layers"], h5py.Group):
                for layer_name in f["layers"]:
                    layers[layer_name] = _inspect_item(f, f"layers/{layer_name}")
            result["layers"] = layers if layers else None

        return result
    except Exception as e:
        return {"error": str(e)}
