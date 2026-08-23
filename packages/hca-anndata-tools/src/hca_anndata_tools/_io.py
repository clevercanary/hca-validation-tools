"""Internal I/O utilities for AnnData file access."""

# pyright: reportArgumentType=none, reportReturnType=none
# h5py stubs return Group | Dataset | Datatype from __getitem__; runtime is always
# narrower (Group or Dataset). Asserting/casting at every site would add heavy
# churn without catching real bugs — this module is the narrowing boundary.

from __future__ import annotations

import gc
from collections.abc import Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING, Literal

import anndata as ad
import h5py
import pandas as pd
from anndata.io import write_elem

if TYPE_CHECKING:
    import numpy as np

# The HCA placeholder vocabulary (case-insensitive): obs values that mean
# "no data". replace_placeholder_values blanks exact (lowercased) matches of
# these; backfill_obs_from_source additionally treats empty/whitespace values
# as missing, via is_missing_value below.
DEFAULT_PLACEHOLDERS = [
    "unknown",
    "na",
    "n/a",
    "none",
    "not available",
    "not applicable",
    "tbd",
    "todo",
    "null",
    "undefined",
]


def is_missing_value(value: str, placeholders: set[str]) -> bool:
    """True if a string value means "no data": empty/whitespace or a
    placeholder (compare against a pre-lowercased set)."""
    s = value.strip()
    return not s or s.lower() in placeholders


@contextmanager
def open_h5ad(path: str, backed: Literal["r", "r+"] | None = "r"):
    """Open an h5ad file with automatic cleanup.

    Args:
        path: Absolute path to an .h5ad file.
        backed: Backing mode. Use "r" for read-only (default), None for full in-memory read.

    Yields:
        An AnnData object.
    """
    adata = ad.read_h5ad(path, backed=backed)
    try:
        yield adata
    finally:
        if hasattr(adata, "file") and adata.file is not None:
            adata.file.close()
        del adata
        gc.collect()


def _decode_bytes(val):
    """Decode bytes to str, pass through anything else."""
    if isinstance(val, bytes):
        return val.decode("utf-8")
    return val


def _strip_ensembl_version(eid: str) -> str:
    """Strip version suffix from Ensembl ID: ENSG00000173947.7 -> ENSG00000173947."""
    if eid.startswith("ENSG") and "." in eid:
        return eid.rsplit(".", 1)[0]
    return eid


def obs_index_name(obs: h5py.Group) -> str:
    """The name of the obs index dataset, from ``obs.attrs['_index']``.

    A reader, not a guard — the same lookup obsm DataFrames need for their
    own sub-index.
    """
    return _decode_bytes(obs.attrs.get("_index", "_index"))


def read_obs_index(path: str) -> list[str]:
    """Read the obs index (cell IDs) from an h5ad file via h5py."""
    with h5py.File(path, "r") as f:
        idx_key = obs_index_name(f["obs"])  # pyright: ignore[reportArgumentType]
        return [_decode_bytes(v) for v in f["obs"][idx_key][:]]


def read_column_order(obs: h5py.Group | h5py.Dataset | h5py.Datatype) -> list[str]:
    """Decode a dataframe group's ``column-order`` attribute to str names.

    The group-level core for callers already holding an open handle;
    :func:`read_obs_column_names` is the path-based wrapper. Accepts the
    ``Group | Dataset | Datatype`` union ``f["obs"]`` is typed as, so call
    sites need neither an isinstance dance nor a pyright suppression.
    """
    return [_decode_bytes(c) for c in obs.attrs["column-order"]]


def read_obs_column_names(path: str) -> list[str]:
    """Read obs column names from an h5ad file via h5py (no AnnData load)."""
    with h5py.File(path, "r") as f:
        return read_column_order(f["obs"])


def read_obs_categorical_values(path: str, column: str) -> set[str]:
    """Read the unique category values for a categorical obs column.

    For categorical columns, HDF5 stores a small 'categories' array
    separately from the per-cell 'codes' array. This reads only the
    categories, avoiding the expensive full-column materialization.

    Note: returns all declared categories, which may include unused values
    if the file was subsetted without removing unused categories. This is
    acceptable because callers operate on full integrated objects, not subsets.

    Falls back to reading the full dataset for non-categorical columns.
    """
    with h5py.File(path, "r") as f:
        item = f["obs"][column]
        if isinstance(item, h5py.Group) and "categories" in item:
            return {_decode_bytes(v) for v in item["categories"][:]}
        # Non-categorical: read full dataset
        return {_decode_bytes(v) for v in item[:]}


def read_var_gene_names(path: str) -> tuple[set[str], dict[str, str]]:
    """Read gene names and Ensembl ID mapping from var via h5py.

    Returns:
        gene_names: Set of all gene symbols in var
        eid_to_var_name: Dict mapping Ensembl ID (stripped of version) to gene symbol
    """
    with h5py.File(path, "r") as f:
        var = f["var"]
        idx_key = _decode_bytes(var.attrs.get("_index", "_index"))
        raw_index = var[idx_key][:]
        index = [_decode_bytes(v) for v in raw_index]

        # Find gene name column
        name_col = None
        for col in ("feature_name", "gene_name"):
            if col in var:
                name_col = col
                break

        if name_col is None:
            # Fallback: index IS the gene names
            return set(index), {}

        item = var[name_col]
        if isinstance(item, h5py.Group) and "categories" in item:
            categories, codes = read_categorical_data(item)
            names = [categories[c] if c >= 0 else "" for c in codes]
        else:
            names = [_decode_bytes(v) for v in item[:]]

        gene_names = set(names)

        eid_to_var_name = {_strip_ensembl_version(eid): name for eid, name in zip(index, names, strict=True)}

        return gene_names, eid_to_var_name


def require_stamped_group(f: h5py.File, path: str) -> h5py.Group:
    """``require_group`` plus the dict encoding attrs anndata expects.

    ``require_group`` leaves a group it creates bare, and anndata reads a group
    with no encoding metadata under an OldFormatWarning — so every site that
    may create a group stamps it here, at the creation, rather than relying on
    some later call to do it as a side effect. ``setdefault`` leaves the attrs
    of an existing group untouched.
    """
    group = f.require_group(path)
    group.attrs.setdefault("encoding-type", "dict")
    group.attrs.setdefault("encoding-version", "0.1.0")
    return group


def ensure_provenance_group(f: h5py.File) -> h5py.Group:
    """Get or create the uns/provenance group with correct encoding attrs.

    Stamps ``uns`` itself as well as the provenance group: ``require_group``
    creates a missing parent implicitly, so ``uns`` may be born here too.
    """
    require_stamped_group(f, "uns")
    return require_stamped_group(f, "uns/provenance")


def read_group(parent: h5py.File | h5py.Group, name: str) -> h5py.Group | None:
    """``parent[name]`` as a group, or None when absent or not a group.

    ``get`` can hand back a Dataset on a malformed file, and callers treat
    these nodes as mappings — where h5py's answers on a Dataset range from
    AttributeError to a silently wrong ``in`` (#617). Narrowing here, once,
    is what keeps the call sites honest; :func:`read_uns` and
    :func:`read_provenance` are its two named shorthands.
    """
    node = parent.get(name)
    return node if isinstance(node, h5py.Group) else None


def read_uns(f: h5py.File) -> h5py.Group | None:
    """The file's uns group, or None when it is absent or not a group."""
    return read_group(f, "uns")


def read_batch_condition(uns: h5py.Group | None) -> list[str]:
    """Read ``uns['batch_condition']`` as a list of obs column names.

    The HCA schema types it ``element_type: match_obs_columns``, so every entry
    must name an obs column. Returns an empty list when absent or unreadable —
    an unreadable value is the validator's problem to report, not a reason for
    a mutating tool to refuse.
    """
    if uns is None or "batch_condition" not in uns:
        return []
    try:
        raw = uns["batch_condition"][()]
    except (OSError, TypeError, ValueError):
        return []
    if isinstance(raw, bytes | str):
        return [_decode_bytes(raw)]
    try:
        return [_decode_bytes(v) for v in raw]
    except TypeError:
        return []


def read_provenance(uns: h5py.Group | None) -> h5py.Group | None:
    """``uns['provenance']`` as a group, or None when absent or not a group."""
    if uns is None:
        return None
    return read_group(uns, "provenance")


def read_edit_log_h5py(f: h5py.File) -> str:
    """Read the edit log JSON string from an open h5py File.

    Returns "[]" if no edit log exists.
    """
    prov = read_provenance(read_uns(f))
    log = prov.get("edit_history") if prov is not None else None
    if isinstance(log, h5py.Dataset):
        raw = log[()]
        if isinstance(raw, bytes | str):
            return _decode_bytes(raw)
    return "[]"


def write_edit_log_h5py(f: h5py.File, log_json: str) -> None:
    """Write the edit log JSON string into an open h5py File.

    Through anndata's ``write_elem``, per the rule below: the edit log is a
    plain string element with no storage layout to preserve, so anndata owns
    its encoding. ``write_elem`` overwrites the key itself.
    """
    write_elem(ensure_provenance_group(f), "edit_history", log_json)


def read_categorical_data(item: h5py.Group) -> tuple[pd.Index, np.ndarray]:
    """Read categories and codes from a categorical h5py group.

    Args:
        item: An h5py Group with 'categories' and 'codes' datasets.

    Returns:
        (categories, codes) — pandas Index of decoded category strings and numpy codes array.
    """
    categories = [_decode_bytes(v) for v in item["categories"][:]]
    codes = item["codes"][:]
    return pd.Index(categories), codes


def update_column_order(
    f_out: h5py.File,
    new_columns: list[str],
    deleted: set[str] | None = None,
) -> None:
    """Update the obs column-order attribute: remove deleted, append new.

    Columns that are both deleted and re-added preserve their original
    position. Only columns deleted but not re-added are removed. Truly
    new columns are appended at the end.

    Args:
        f_out: Open h5py File in append mode.
        new_columns: Column names to append (or replace in-place).
        deleted: Column names that were removed (if any).
    """
    current = [_decode_bytes(c) for c in f_out["obs"].attrs["column-order"]]
    if deleted:
        new_set = set(new_columns)
        # Only remove columns that were deleted and NOT re-added
        current = [c for c in current if c not in (deleted - new_set)]
    to_add = [c for c in new_columns if c not in current]
    f_out["obs"].attrs["column-order"] = current + to_add


def transplant_obs_columns(
    f_temp: h5py.File,
    f_out: h5py.File,
    columns: list[str],
    overwrite: bool = False,
) -> set[str]:
    """Copy obs columns from temp file to output file via h5py.copy().

    Optionally deletes existing columns first (overwrite mode).
    Updates column-order attribute.

    Args:
        f_temp: Source h5py File (read mode) with columns in obs.
        f_out: Target h5py File (append mode).
        columns: Column names to transplant.
        overwrite: If True, delete existing columns before copying.

    Returns:
        Set of column names that were deleted (empty if not overwriting).
    """
    deleted = set()
    copied = []
    for col in columns:
        if col not in f_temp["obs"]:
            continue
        if col in f_out["obs"]:
            if overwrite:
                del f_out["obs"][col]
                deleted.add(col)
            else:
                continue
        f_temp.copy(f"obs/{col}", f_out["obs"])
        copied.append(col)

    update_column_order(f_out, copied, deleted)
    return deleted


def check_duplicate_ids(index, label: str) -> str | None:
    """Return an error message if index has duplicates, else None.

    Accepts anything pd.Index accepts (list, ndarray, or an existing Index,
    which passes through without a copy); the check runs in pandas' C
    hashtable rather than a per-element Python loop.
    """
    idx = pd.Index(index)
    if not idx.has_duplicates:
        return None
    dupes = idx[idx.duplicated()].unique()[:5].tolist()
    return f"{label} have duplicate IDs (first 5): {dupes}"


def read_string_dataset(group: h5py.Group, name: str) -> np.ndarray:
    """Read a string dataset as an object array of str.

    asstr() decodes in C (vlen and fixed-width alike); dtype=object matters —
    a fixed-width unicode dtype would silently clip longer values assigned
    into the array later (see rename_cell_ids).
    """
    import numpy as np

    return np.asarray(group[name].asstr()[:], dtype=object)


# The rule for the two encoders below, and for anything added beside them:
# use anndata's ``write_elem`` where there is no storage layout to preserve
# (see write_edit_log_h5py, and batch_condition in rename_column); hand-roll
# only where there is. These two carry the original dataset's compression,
# chunks and maxshape — and, for a categorical, the narrowed codes dtype —
# forward across a delete-and-recreate, which write_elem would discard.
def replace_string_dataset(parent: h5py.Group, name: str, data: np.ndarray) -> None:
    """Delete and recreate a string dataset, preserving its attrs and storage
    properties (compression, chunks, shuffle, fletcher32, maxshape)."""
    ds = parent[name]
    attrs = dict(ds.attrs)
    storage = {
        "compression": ds.compression,
        "compression_opts": ds.compression_opts,
        "chunks": ds.chunks,
        "shuffle": ds.shuffle,
        "fletcher32": ds.fletcher32,
        # A contiguous dataset reports maxshape == shape; passing any
        # non-None maxshape to create_dataset forces chunked layout, so
        # only carry it when the dataset is actually resizable.
        "maxshape": ds.maxshape if ds.maxshape != ds.shape else None,
    }
    del parent[name]
    new_ds = parent.create_dataset(name, data=data, dtype=h5py.string_dtype(encoding="utf-8"), **storage)
    for key, attr_value in attrs.items():
        new_ds.attrs[key] = attr_value


def compact_categories(categories: list[str], codes: np.ndarray) -> tuple[list[str], np.ndarray, list[int]]:
    """Drop categories no code references and remap the codes accordingly.

    Codes below 0 (NaN) stay -1. Returns the kept categories, the remapped
    codes as int64 (:func:`replace_categorical_column` sizes the on-disk dtype
    itself), and the *positions* the kept categories held before — which
    :func:`remap_palette` needs to keep a per-category palette aligned.
    """
    import numpy as np

    valid = codes >= 0
    # Range-check before bincount: one corrupt out-of-range code would
    # otherwise size the bincount allocation to max(code)+1 entries.
    if valid.any() and int(codes[valid].max()) >= len(categories):
        raise ValueError(
            f"categorical codes reference category {int(codes[valid].max())} "
            f"but only {len(categories)} categories exist — the column is corrupt"
        )
    used = np.flatnonzero(np.bincount(codes[valid], minlength=len(categories)))
    kept = [categories[i] for i in used]
    lookup = np.full(len(categories), -1, dtype=np.int64)
    lookup[used] = np.arange(len(used))
    new_codes = np.full(codes.shape, -1, dtype=np.int64)
    new_codes[valid] = lookup[codes[valid]]
    return kept, new_codes, [int(i) for i in used]


def direct_members(group: h5py.Group) -> set[str]:
    """A group's direct children, for membership tests.

    Membership against this set, not ``name in group`` — h5py's
    ``__contains__`` resolves link paths, so it accepts names that point
    outside the group entirely (the ``/`` trap :func:`is_malformed_name`
    rejects). True of any group, which is why uns lookups use it too.
    """
    return set(group.keys())


def remap_palette(uns: h5py.Group | None, key: str | None, kept: Sequence[int], n_before: int) -> bool:
    """Keep only the colours of the categories that survived, by position.

    ``uns['<column>_colors']`` is positionally aligned to the column's
    categories, so removing a category shifts every colour after it — and the
    HCA validator checks only the palette's *length*, so a file whose lengths
    happen to still agree is simply mis-coloured with nothing reported. Every
    tool that removes a category owes this remap (#624).

    Takes the surviving positions rather than calling
    :func:`compact_categories` itself, because not every caller may use that
    function: ``merge_obs_categories`` must not, since it drops every
    unreferenced category and would discard one left empty for its own reasons.

    Does nothing, and returns False, when there is no palette to remap or when
    its length already disagrees with ``n_before`` — an already-broken palette
    is the validator's to report, not this function's to guess at.
    """
    import numpy as np

    if uns is None or key is None or key not in direct_members(uns):
        return False
    colors = list(read_string_dataset(uns, key))
    if len(colors) != n_before:
        return False
    write_elem(uns, key, np.array([colors[i] for i in kept], dtype=object))
    return True


def _codes_dtype(n_categories: int, original: np.dtype) -> np.dtype:
    """Smallest signed dtype holding the category count, never narrower than
    the original codes dtype (extending categories can overflow int8)."""
    import numpy as np

    for dt in (np.int8, np.int16, np.int32, np.int64):
        if np.iinfo(dt).max >= n_categories - 1 and np.dtype(dt).itemsize >= original.itemsize:
            return np.dtype(dt)
    return np.dtype(np.int64)


def replace_categorical_column(parent: h5py.Group, col: str, categories: list[str], codes: np.ndarray) -> None:
    """Delete and recreate a categorical column group, preserving its encoding
    attrs and the codes dataset's storage settings (compression, chunks).

    The codes are written at the smallest dtype that holds the new category
    count without narrowing the original — a caller that extended the
    categories does not have to know about int8 overflow.
    """
    import numpy as np

    item = parent[col]
    encoding_type = item.attrs["encoding-type"]
    encoding_version = item.attrs["encoding-version"]
    ordered = bool(item.attrs["ordered"])
    codes_compression = item["codes"].compression
    codes_compression_opts = item["codes"].compression_opts
    codes_chunks = item["codes"].chunks
    codes = codes.astype(_codes_dtype(len(categories), item["codes"].dtype))

    del parent[col]
    grp = parent.create_group(col)
    grp.attrs["encoding-type"] = encoding_type
    grp.attrs["encoding-version"] = encoding_version
    grp.attrs["ordered"] = ordered
    cat_data = np.array(categories, dtype=object) if categories else np.array([], dtype=h5py.string_dtype())
    cat_ds = grp.create_dataset("categories", data=cat_data)
    cat_ds.attrs["encoding-type"] = "string-array"
    cat_ds.attrs["encoding-version"] = "0.2.0"
    codes_ds = grp.create_dataset(
        "codes",
        data=codes,
        compression=codes_compression,
        compression_opts=codes_compression_opts,
        chunks=codes_chunks,
    )
    codes_ds.attrs["encoding-type"] = "array"
    codes_ds.attrs["encoding-version"] = "0.2.0"


def verify_categorical_integrity(
    f: h5py.File,
    columns: list[str],
    expected_valid_counts: dict[str, int] | None = None,
) -> str | None:
    """Check categorical obs columns for data corruption.

    Verifies: codes length matches obs count, all codes in range,
    no codes below -1. Optionally checks that the number of non-NaN
    values matches expected counts (catches NaN→valid corruption).

    Args:
        f: Open h5py File.
        columns: Column names to check.
        expected_valid_counts: If provided, {col: expected_non_nan_count}.

    Returns:
        None if all columns pass, or an error message string.
    """
    obs = f["obs"]
    idx_key = _decode_bytes(obs.attrs.get("_index", "_index"))
    n_obs = len(obs[idx_key])

    for col in columns:
        item = obs[col]
        if not (isinstance(item, h5py.Group) and "categories" in item):
            continue
        cats = item["categories"][:]
        codes = item["codes"][:]

        if len(codes) != n_obs:
            return f"Column '{col}': codes length {len(codes)} != n_obs {n_obs}"
        if (codes < -1).any():
            return f"Column '{col}': found codes below -1"
        valid = codes[codes >= 0]
        if len(valid) > 0 and len(cats) > 0 and int(valid.max()) >= len(cats):
            return f"Column '{col}': max code {valid.max()} >= n_categories {len(cats)}"
        if expected_valid_counts and col in expected_valid_counts:
            actual = int((codes >= 0).sum())
            expected = expected_valid_counts[col]
            if actual != expected:
                return f"Column '{col}': expected {expected} valid values, got {actual}"

    return None


def verify_obs_transplant(
    temp_path: str,
    output_path: str,
    columns: list[str],
) -> str | None:
    """Verify obs columns were transplanted correctly via full-column comparison.

    Compares raw HDF5 data (categories + codes for categoricals, or full
    dataset for non-categoricals) between temp and output for each column.

    Returns:
        None if all columns match, or an error message string on mismatch.
    """
    import numpy as np

    with h5py.File(temp_path, "r") as f_temp, h5py.File(output_path, "r") as f_out:
        for col in columns:
            temp_item = f_temp["obs"][col]
            out_item = f_out["obs"][col]

            if isinstance(temp_item, h5py.Group) and "categories" in temp_item:
                if not np.array_equal(temp_item["categories"][:], out_item["categories"][:]):
                    return f"Verification failed: categories mismatch for column '{col}'"
                if not np.array_equal(temp_item["codes"][:], out_item["codes"][:]):
                    return f"Verification failed: codes mismatch for column '{col}'"
            else:
                if not np.array_equal(temp_item[:], out_item[:]):
                    return f"Verification failed: data mismatch for column '{col}'"

    return None
