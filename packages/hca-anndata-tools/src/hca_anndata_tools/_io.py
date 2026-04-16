"""Internal I/O utilities for AnnData file access."""

from __future__ import annotations

import gc
from contextlib import contextmanager
from typing import TYPE_CHECKING

import anndata as ad
import h5py

if TYPE_CHECKING:
    import numpy as np


@contextmanager
def open_h5ad(path: str, backed: str | None = "r"):
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


def read_obs_index(path: str) -> list[str]:
    """Read the obs index (cell IDs) from an h5ad file via h5py."""
    with h5py.File(path, "r") as f:
        idx_key = _decode_bytes(f["obs"].attrs.get("_index", "_index"))
        return [_decode_bytes(v) for v in f["obs"][idx_key][:]]


def read_obs_column_names(path: str) -> list[str]:
    """Read obs column names from an h5ad file via h5py (no AnnData load)."""
    with h5py.File(path, "r") as f:
        return [_decode_bytes(c) for c in f["obs"].attrs["column-order"]]


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

        eid_to_var_name = {
            _strip_ensembl_version(eid): name for eid, name in zip(index, names)
        }

        return gene_names, eid_to_var_name


def ensure_provenance_group(f: h5py.File) -> h5py.Group:
    """Get or create the uns/provenance group with correct encoding attrs."""
    group = f.require_group("uns/provenance")
    group.attrs.setdefault("encoding-type", "dict")
    group.attrs.setdefault("encoding-version", "0.1.0")
    return group


def read_edit_log_h5py(f: h5py.File) -> str:
    """Read the edit log JSON string from an open h5py File.

    Returns "[]" if no edit log exists.
    """
    uns = f.get("uns")
    if uns:
        prov = uns.get("provenance")
        if prov and isinstance(prov, h5py.Group) and "edit_history" in prov:
            return _decode_bytes(prov["edit_history"][()])
    return "[]"


def write_edit_log_h5py(f: h5py.File, log_json: str) -> None:
    """Write the edit log JSON string into an open h5py File."""
    prov = ensure_provenance_group(f)
    if "edit_history" in prov:
        del prov["edit_history"]
    ds = prov.create_dataset("edit_history", data=log_json)
    ds.attrs["encoding-type"] = "string"
    ds.attrs["encoding-version"] = "0.2.0"


def read_categorical_data(item: h5py.Group) -> tuple[list[str], "np.ndarray"]:
    """Read categories and codes from a categorical h5py group.

    Args:
        item: An h5py Group with 'categories' and 'codes' datasets.

    Returns:
        (categories, codes) — list of decoded category strings and numpy codes array.
    """
    categories = [_decode_bytes(v) for v in item["categories"][:]]
    codes = item["codes"][:]
    return categories, codes


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
                return (
                    f"Column '{col}': expected {expected} valid values, "
                    f"got {actual}"
                )

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

    with h5py.File(temp_path, "r") as f_temp, \
         h5py.File(output_path, "r") as f_out:
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
