"""HDF5 storage details for an AnnData file."""

from pathlib import Path

import h5py
import numpy as np

from ._io import (
    direct_members,
    encoding_of,
    holds_string_values,
    is_writable_element,
    obs_index_name,
    read_group,
)
from .write import resolve_latest

# The dataframe groups worth reporting encodings for, as (result key, HDF5 path).
# The key is the AnnData spelling a reader recognises (``raw.var``); the path is
# where it lives on disk (``raw/var``). Reported paths use the on-disk form so
# they can be pasted straight into h5py or grep.
_DATAFRAMES = (("obs", "obs"), ("var", "var"), ("raw.var", "raw/var"))

# A file written entirely in an unsupported encoding flags every categorical
# it has — 64 paths on the liver object that motivated this. The exact count
# is the actionable number; an unbounded path list is noise that crowds out
# the rest of the report, so the paths are a sample and the count is whole.
# Same tactic as guards._MAX_REPORTED, deliberately not the same number: that
# one caps names inside a one-line refusal message, this one caps a sample in
# a JSON payload a reader can scroll.
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
    result: dict = {"format": encoding_of(group) or "unknown"}
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
    if isinstance(item, h5py.Group) and isinstance(mask := item.get("mask"), h5py.Dataset):
        # count_nonzero is a dedicated popcount path; ndarray.sum() on bools
        # goes through a generic int64 add-reduce and measures ~13x slower.
        return int(np.count_nonzero(mask[:]))
    return None


def _dataframe_encodings(df: h5py.Group, path: str, index_name: str) -> tuple[dict, list[str]]:
    """Encodings of a dataframe's index, its columns, and its categoricals' categories.

    Returns the per-dataframe report and the nullable-string paths —
    indexes, plain columns, and categorical ``categories`` alike.
    Informational: every write normalizes the flagged elements it touches
    (#641); nothing refuses them, and only masked string *values* refuse
    anywhere.
    Categorical ``categories`` are reported because they block a write exactly
    as an index does — in the files that motivated this
    (hca-validation-tools#638) a categorical's categories were themselves a
    nullable group; since #641 the tools normalize that shape as they
    rewrite it, and only *masked* categories refuse.

    Members are read through :func:`~hca_anndata_tools._io.direct_members`
    because ``index_name`` comes from the file rather than the caller, and
    h5py's ``__contains__`` resolves link paths — so a malformed name with a
    ``/`` would otherwise be looked up outside this group. Sorting keeps the
    truncated path sample deterministic between runs.
    """
    unsupported: list[str] = []
    members = direct_members(df)

    index_enc = None
    index_masked = None
    if index_name in members:
        index = df[index_name]
        # "unstamped" matches the categoricals path below: older AnnData wrote
        # string arrays with no encoding-type, and that is a real encoding
        # state. None is reserved for "the group has no index dataset at all".
        index_enc = encoding_of(index) or "unstamped"
        index_masked = _mask_count(index)
        # Nullable-string only, like the column and categories rules below:
        # a categorical or nullable-numeric index group is in-profile and
        # nothing refuses it (rename flattens a categorical index as it
        # rewrites it).
        if holds_string_values(index) and not is_writable_element(index):
            unsupported.append(f"{path}/{index_name}")

    categoricals: dict[str, int] = {}
    for name in sorted(members):
        if name == index_name:
            continue
        column = df[name]
        if not isinstance(column, h5py.Group):
            continue
        if "categories" not in column:
            # Only nullable *strings* are flagged: they are what the write
            # funnel refuses. Nullable-integer/boolean columns pass through
            # every tool (anndata writes them ungated), so flagging them
            # would hard-stop curation on files nothing refuses.
            if holds_string_values(column):
                unsupported.append(f"{path}/{name}")
            continue
        categories = column["categories"]
        label = encoding_of(categories) or "unstamped"
        categoricals[label] = categoricals.get(label, 0) + 1
        # Nullable-string only, like the plain-column rule above:
        # nullable-*numeric* categories are inside the profile (anndata
        # writes them ungated), and a full rewrite would emit them again —
        # flagging them would send a curator on the remedy loop forever.
        if holds_string_values(categories) and not is_writable_element(categories):
            unsupported.append(f"{path}/{name}/categories")

    return {
        "index": index_enc,
        "index_masked": index_masked,
        "categoricals": categoricals,
    }, unsupported


def _encodings_info(f: h5py.File) -> dict:
    """Report string encodings across obs, var, raw.var and obsm DataFrames.

    Attribute reads, plus one mask read per nullable index — bounded by the
    cell count, never by the matrix — so this is as cheap on a 29 GB atlas as
    on a small file. A file with no nullable index reads no data at all.

    Scope is the listed dataframes' indexes, plain nullable-string
    columns, and categorical ``categories`` — everything a tool would
    actually refuse. ``varm`` and ``uns`` frames are the write funnel's
    alone, and nullable-integer/boolean columns are not flagged: every
    tool accepts them.
    """
    result: dict = {}
    unsupported: list[str] = []
    for key, path in _DATAFRAMES:
        df = read_group(f, path)
        if df is None:
            result[key] = None
            continue
        report, bad = _dataframe_encodings(df, path, obs_index_name(df))
        result[key] = report
        unsupported.extend(bad)

    # obsm DataFrames carry their own index, which rename_cell_ids reads the
    # same way it reads obs (rename.py). Omitting them would let a file report
    # a clean bill of health and still fail mid-rename — the exact late,
    # opaque failure this block exists to pre-empt.
    obsm_frames: dict = {}
    obsm = read_group(f, "obsm")
    if obsm is not None:
        for name in sorted(direct_members(obsm)):
            member = obsm[name]
            if not isinstance(member, h5py.Group) or encoding_of(member) != "dataframe":
                continue
            report, bad = _dataframe_encodings(member, f"obsm/{name}", obs_index_name(member))
            obsm_frames[name] = report
            unsupported.extend(bad)
    result["obsm"] = obsm_frames
    result["unsupported_count"] = len(unsupported)
    result["unsupported"] = unsupported[:_MAX_UNSUPPORTED_PATHS]
    result["unsupported_truncated"] = len(unsupported) > _MAX_UNSUPPORTED_PATHS
    return result


def get_storage_info(path: str) -> dict:
    """Get HDF5 storage details for an AnnData .h5ad file.

    Returns file size, compression settings, chunk sizes, and sparse format
    for X, raw/X, and all layers, plus the string encodings used by the
    ``obs``, ``var``, ``raw.var`` and obsm dataframes — indexes, plain
    nullable-string columns, and categoricals.

    The ``encodings`` block exists so an incompatible on-disk representation
    surfaces during inspection rather than as an opaque HDF5 error partway
    through a curation run on a multi-gigabyte file. Its ``unsupported`` list
    names the nullable-string paths in the file — informational: since #641
    nothing refuses them, every write normalizes the ones it touches, and
    the flags clear as writes happen.
    Informational since #641: no tool refuses these encodings any more —
    every write normalizes what it touches (a full rewrite normalizes
    everything; an in-place rewrite normalizes the elements it replaces), so
    the flags describe the file as it is, and clear as writes happen. Masked
    string values are the one hard stop — no rewrite may flatten them.

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
            # Best-effort: this block walks obs/var/raw.var/obsm, which the rest
            # of this function never touches, so a structural surprise there
            # (a dangling link, an array-valued _index attr) must not discard
            # the size and compression report callers already relied on.
            try:
                result["encodings"] = _encodings_info(f)
            except Exception as e:
                result["encodings"] = {"error": str(e)}

        return result
    except Exception as e:
        return {"error": str(e)}
