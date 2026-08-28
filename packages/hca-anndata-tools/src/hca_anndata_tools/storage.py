"""HDF5 storage details for an AnnData file."""

from pathlib import Path

import h5py

from ._io import (
    direct_members,
    encoding_of,
    holds_string_values,
    is_writable_element,
    mask_count,
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


def _dataframe_encodings(df: h5py.Group, path: str, index_name: str) -> tuple[dict, dict[str, int]]:
    """Encodings of a dataframe's index, its columns, and its categoricals' categories.

    Returns the per-dataframe report and the flagged nullable-string paths —
    indexes, plain columns, and categorical ``categories`` alike — each
    mapped to its count of masked values (0 for the ordinary mask-0 case).
    One mapping rather than parallel collections, so a future flagged shape
    cannot report the path and silently skip its masked verdict. The two
    verdicts differ (#651): a mask-0 flagged element is informational —
    every write normalizes it as it touches it (#641) — while a *masked*
    one refuses the writes that would rewrite it, so the report must let a
    reader tell them apart.
    Categorical ``categories`` are reported just like indexes and plain
    columns — in the files that motivated this
    (hca-validation-tools#638) a categorical's categories were themselves a
    nullable group; since #641 the tools normalize that shape as they
    rewrite it, and only *masked* categories refuse.

    Members are read through :func:`~hca_anndata_tools._io.direct_members`
    because ``index_name`` comes from the file rather than the caller, and
    h5py's ``__contains__`` resolves link paths — so a malformed name with a
    ``/`` would otherwise be looked up outside this group. Sorting keeps the
    truncated path sample deterministic between runs.
    """
    flagged: dict[str, int] = {}
    members = direct_members(df)

    index_enc = None
    index_masked = None
    if index_name in members:
        index = df[index_name]
        # "unstamped" matches the categoricals path below: older AnnData wrote
        # string arrays with no encoding-type, and that is a real encoding
        # state. None is reserved for "the group has no index dataset at all".
        index_enc = encoding_of(index) or "unstamped"
        index_masked = mask_count(index)
        # Nullable-string only, like the column and categories rules below:
        # a categorical or nullable-numeric index group is in-profile and
        # nothing refuses it (rename flattens a categorical index as it
        # rewrites it). A categorical index can still hide the nullable
        # dtype in its *categories* child — flagged like a column's, so the
        # report and the funnel agree (principle 10).
        if holds_string_values(index) and not is_writable_element(index):
            flagged[f"{path}/{index_name}"] = index_masked or 0
        elif (
            isinstance(index, h5py.Group)
            and "categories" in index
            and holds_string_values(index["categories"])
            and not is_writable_element(index["categories"])
        ):
            flagged[f"{path}/{index_name}/categories"] = mask_count(index["categories"]) or 0

    categoricals: dict[str, int] = {}
    for name in sorted(members):
        if name == index_name:
            continue
        column = df[name]
        if not isinstance(column, h5py.Group):
            continue
        if "categories" not in column:
            # Only nullable *strings* are flagged: they are what writes
            # normalize. Nullable-integer/boolean columns pass through
            # every tool untouched (anndata writes them ungated), so
            # flagging them would be noise nothing acts on.
            if holds_string_values(column):
                flagged[f"{path}/{name}"] = mask_count(column) or 0
            continue
        categories = column["categories"]
        label = encoding_of(categories) or "unstamped"
        categoricals[label] = categoricals.get(label, 0) + 1
        # Nullable-string only, like the plain-column rule above:
        # nullable-*numeric* categories are inside the profile (anndata
        # writes them ungated), and a full rewrite would emit them again —
        # flagging them would send a curator on the remedy loop forever.
        if holds_string_values(categories) and not is_writable_element(categories):
            flagged[f"{path}/{name}/categories"] = mask_count(categories) or 0

    return {
        "index": index_enc,
        "index_masked": index_masked,
        "categoricals": categoricals,
    }, flagged


def _encodings_info(f: h5py.File) -> dict:
    """Report string encodings across obs, var, raw.var and obsm DataFrames.

    Attribute reads, plus one mask read per nullable element — bounded by
    the nullable-element count times the cell count, never by the matrix —
    so this is as cheap on a 29 GB atlas as on a small file. A file with
    no nullable elements reads no data at all.

    Scope is the listed dataframes' indexes, plain nullable-string
    columns, and categorical ``categories``. ``varm`` and ``uns`` frames
    are the write funnel's alone, and nullable-integer/boolean columns are
    not flagged: every tool accepts them. The ``masked`` dict separates
    the two verdicts a flagged path can carry (#651): absent from it,
    the element normalizes on the next write that touches it; present,
    the writes that would rewrite it refuse — the in-repo remedies are a
    backfill that fills the masked values (residuals still refuse) or
    dropping the column; otherwise repair upstream. ``masked`` shares
    this block's inspection scope: a masked element in ``varm`` or
    ``uns`` still refuses writes even though it is not reported here.
    ``masked_count`` counts flagged *paths* (like ``unsupported_count``),
    not masked values — the per-path value counts are the dict's values.
    """
    result: dict = {}
    flagged: dict[str, int] = {}
    for key, path in _DATAFRAMES:
        df = read_group(f, path)
        if df is None:
            result[key] = None
            continue
        report, frame_flagged = _dataframe_encodings(df, path, obs_index_name(df))
        result[key] = report
        flagged.update(frame_flagged)

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
            report, frame_flagged = _dataframe_encodings(member, f"obsm/{name}", obs_index_name(member))
            obsm_frames[name] = report
            flagged.update(frame_flagged)
    result["obsm"] = obsm_frames
    # Both report views derive from the one flagged mapping, here and
    # nowhere else — a path cannot appear in one and drift out of the other.
    masked = {p: n for p, n in flagged.items() if n}
    result["unsupported_count"] = len(flagged)
    result["unsupported"] = list(flagged)[:_MAX_UNSUPPORTED_PATHS]
    result["unsupported_truncated"] = len(flagged) > _MAX_UNSUPPORTED_PATHS
    result["masked_count"] = len(masked)
    result["masked"] = dict(list(masked.items())[:_MAX_UNSUPPORTED_PATHS])
    result["masked_truncated"] = len(masked) > _MAX_UNSUPPORTED_PATHS
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
    names the nullable-string paths in the file, and its ``masked`` dict
    (path → count) separates the two verdicts those paths carry (#651): a
    path absent from ``masked`` is informational — every write normalizes it
    as it touches it (#641), so the flag clears as writes happen — while a
    path in ``masked`` holds masked string values, the one hard stop: the
    writes that would rewrite it refuse by name. The in-repo remedies are
    a backfill that fills the masked values (residuals still refuse) or
    dropping the column; otherwise the data must be repaired upstream.

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
