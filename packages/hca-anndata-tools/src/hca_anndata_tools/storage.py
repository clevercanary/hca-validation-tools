"""HDF5 storage details for an AnnData file."""

from pathlib import Path

import h5py

from ._io import SUPPORTED_STRING_ENCODINGS, encoding_of, obs_index_name
from .write import resolve_latest

# The dataframe groups worth reporting encodings for, as (result key, HDF5 path).
# ``raw.var`` is spelled with a dot in the result and a slash on disk, matching
# how the rest of this module reports ``raw_X``.
_DATAFRAMES = (("obs", "obs"), ("var", "var"), ("raw.var", "raw/var"))

# A file written entirely in an unsupported encoding flags every categorical
# it has — 66 paths on the liver object that motivated this. The exact count
# is the actionable number; an unbounded path list is noise that crowds out
# the rest of the report, so the paths are a sample and the count is whole.
# Mirrors the _MAX_REPORTED cap guards.py uses for the same reason.
_MAX_UNSUPPORTED_PATHS = 10


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
    if isinstance(item, h5py.Group):
        return _group_info(item)
    return None


def _mask_count(item: h5py.Group | h5py.Dataset | h5py.Datatype) -> int | None:
    """Number of masked (null) entries in a nullable array, or None.

    Only nullable encodings carry a ``mask``; anything else has no notion of
    a null and returns None rather than 0, so callers can tell "no nulls"
    apart from "cannot have nulls".
    """
    if isinstance(item, h5py.Group) and "mask" in item:
        mask = item["mask"]
        if isinstance(mask, h5py.Dataset):
            return int(mask[:].sum())
    return None


def _is_unreadable(item: h5py.Group | h5py.Dataset | h5py.Datatype, encoding: str | None) -> bool:
    """True if this package's raw-h5py readers cannot slice ``item``.

    The operative test is the container, not the encoding name: every reader
    here does ``item[:]``, which a Dataset answers and a Group refuses. So a
    numeric categorical whose categories are an ``array`` Dataset is fine,
    while a ``nullable-string-array`` Group is not — judging by encoding name
    alone would flag the former as broken when it reads perfectly well.

    The encoding is still consulted so that widening
    :data:`~hca_anndata_tools._io.SUPPORTED_STRING_ENCODINGS` (see
    hca-validation-tools#637) clears these reports in the same commit that
    makes the readers cope.
    """
    if not isinstance(item, h5py.Group):
        return False
    return encoding not in SUPPORTED_STRING_ENCODINGS


def _dataframe_encodings(df: h5py.Group, key: str, index_name: str) -> tuple[dict, list[str]]:
    """Encodings of a dataframe's index and its categoricals' categories.

    Returns the per-dataframe report and the paths whose encoding this
    package's raw-h5py readers cannot handle. Categorical ``categories`` are
    reported because they break readers exactly as an index does — in the
    files that motivated this (hca-validation-tools#638) a categorical's
    categories were themselves a nullable group.
    """
    unsupported: list[str] = []

    index_enc = None
    index_masked = None
    if index_name in df:
        index = df[index_name]
        index_enc = encoding_of(index)
        index_masked = _mask_count(index)
        if _is_unreadable(index, index_enc):
            unsupported.append(f"{key}/{index_name}")

    categoricals: dict[str, int] = {}
    for name in df:
        if name == index_name:
            continue
        column = df[name]
        if not isinstance(column, h5py.Group) or "categories" not in column:
            continue
        categories = column["categories"]
        enc = encoding_of(categories)
        categoricals[enc or "unstamped"] = categoricals.get(enc or "unstamped", 0) + 1
        if _is_unreadable(categories, enc):
            unsupported.append(f"{key}/{name}/categories")

    return {
        "index": index_enc,
        "index_masked": index_masked,
        "categoricals": categoricals,
    }, unsupported


def _encodings_info(f: h5py.File) -> dict:
    """Report string encodings across obs, var and raw.var.

    Attribute reads and (for nullable indexes) one mask read only — the cost
    does not scale with the size of the expression matrix, so this is as
    cheap on a 29 GB atlas as on a small file.
    """
    result: dict = {}
    unsupported: list[str] = []
    for key, path in _DATAFRAMES:
        df = f.get(path)
        if not isinstance(df, h5py.Group):
            result[key] = None
            continue
        report, bad = _dataframe_encodings(df, key, obs_index_name(df))
        result[key] = report
        unsupported.extend(bad)
    result["unsupported_count"] = len(unsupported)
    result["unsupported"] = unsupported[:_MAX_UNSUPPORTED_PATHS]
    result["unsupported_truncated"] = len(unsupported) > _MAX_UNSUPPORTED_PATHS
    return result


def get_storage_info(path: str) -> dict:
    """Get HDF5 storage details for an AnnData .h5ad file.

    Returns file size, compression settings, chunk sizes, and sparse format
    for X, raw/X, and all layers, plus the string encodings used by the
    ``obs``, ``var`` and ``raw.var`` indexes and categoricals.

    The ``encodings`` block exists so an incompatible on-disk representation
    surfaces during inspection rather than as an opaque HDF5 error partway
    through a curation run on a multi-gigabyte file. Its ``unsupported`` list
    names the paths this package's raw-h5py readers cannot handle, judged
    against :data:`~hca_anndata_tools._io.SUPPORTED_STRING_ENCODINGS`.

    Args:
        path: Absolute path to an .h5ad file.
    """
    try:
        if not path.endswith(".h5ad"):
            return {"error": "Only .h5ad files supported (not zarr)"}

        path = resolve_latest(path)
        file_bytes = Path(path).stat().st_size
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
            result["encodings"] = _encodings_info(f)

        return result
    except Exception as e:
        return {"error": str(e)}
