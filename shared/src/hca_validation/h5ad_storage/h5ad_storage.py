"""Lightweight HDF5 storage introspection for h5ad matrices.

Reports per-matrix facts (shape, nnz, dtype, on-disk and in-memory size) for
``X``, ``raw.X`` and every layer by reading **only the HDF5 header** — it never
materializes a matrix. This is intentionally pure ``h5py`` + ``numpy`` (no
anndata / scanpy load) so it stays cheap and can run inside the lean Batch
validator without pulling a scientific stack.

Why this exists: anndata's ``read_h5ad(path, backed="r")`` eagerly reads
``layers`` and ``raw`` (backed mode is X-only), which on files with
multi-billion-nonzero matrices spikes to tens of GB. Callers that only need
*metadata about* the matrices should use this instead. See
hca-validation-tools#447.
"""

from __future__ import annotations

from typing import Any, Optional, cast

import h5py
import numpy as np

_SPARSE_ENCODINGS = ("csr_matrix", "csc_matrix")


def _decode(value: Any) -> Any:
    return value.decode() if isinstance(value, bytes) else value


def _storage_size(dataset: h5py.Dataset) -> int:
    """On-disk (post-compression) size of an HDF5 dataset, in bytes."""
    return int(dataset.id.get_storage_size())


def _matrix_info(node: Any) -> Optional[dict]:
    """Storage facts for one matrix node (sparse group or dense dataset).

    Returns ``None`` for anything that isn't a recognizable matrix.
    """
    encoding = _decode(node.attrs.get("encoding-type", ""))

    if isinstance(node, h5py.Group) and encoding in _SPARSE_ENCODINGS:
        data = cast(h5py.Dataset, node["data"])
        indices = cast(h5py.Dataset, node["indices"])
        indptr = cast(h5py.Dataset, node["indptr"])
        shape = tuple(int(x) for x in node.attrs.get("shape", ()))
        nnz = int(data.shape[0])
        data_itemsize = np.dtype(data.dtype).itemsize
        index_itemsize = np.dtype(indices.dtype).itemsize
        indptr_itemsize = np.dtype(indptr.dtype).itemsize
        resident = nnz * (data_itemsize + index_itemsize) + int(indptr.shape[0]) * indptr_itemsize
        on_disk = _storage_size(data) + _storage_size(indices) + _storage_size(indptr)
        return {
            "format": encoding,
            "n_obs": shape[0] if len(shape) == 2 else None,
            "n_vars": shape[1] if len(shape) == 2 else None,
            "nnz": nnz,
            "data_dtype": str(np.dtype(data.dtype)),
            "index_dtype": str(np.dtype(indices.dtype)),
            "on_disk_bytes": int(on_disk),
            "resident_bytes": int(resident),
        }

    if isinstance(node, h5py.Dataset):
        shape = tuple(int(x) for x in node.shape)
        itemsize = np.dtype(node.dtype).itemsize
        n_elements = int(np.prod(shape)) if shape else 0
        return {
            "format": "dense",
            "n_obs": shape[0] if len(shape) >= 1 else None,
            "n_vars": shape[1] if len(shape) >= 2 else None,
            "nnz": None,
            "data_dtype": str(np.dtype(node.dtype)),
            "index_dtype": None,
            "on_disk_bytes": _storage_size(node),
            "resident_bytes": int(n_elements * itemsize),
        }

    return None


def get_matrix_storage(path: str) -> dict:
    """Per-matrix storage facts for ``X``, ``raw.X`` and each layer.

    Reads only HDF5 metadata — does not load matrix data. Each value carries
    ``format``, ``n_obs``/``n_vars``, ``nnz`` (None for dense), ``data_dtype``,
    ``index_dtype`` (None for dense), ``on_disk_bytes`` and ``resident_bytes``
    (the estimated in-memory footprint of a full, non-backed load).

    Args:
        path: Path to an ``.h5ad`` file.

    Returns:
        ``{"X": {...} | None, "raw_X": {...} | None, "layers": {name: {...}} | None}``.
    """
    result: dict = {"X": None, "raw_X": None, "layers": None}
    with h5py.File(path, "r") as f:
        if "X" in f:
            result["X"] = _matrix_info(f["X"])
        raw = f["raw"] if "raw" in f else None
        if isinstance(raw, h5py.Group) and "X" in raw:
            result["raw_X"] = _matrix_info(raw["X"])
        layers_group = f["layers"] if "layers" in f else None
        if isinstance(layers_group, h5py.Group) and len(layers_group):
            layers = {}
            for name in layers_group:
                layers[name] = _matrix_info(layers_group[name])
            result["layers"] = layers
    return result
