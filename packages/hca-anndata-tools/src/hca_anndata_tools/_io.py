"""Internal I/O utilities for AnnData file access."""

import gc
from contextlib import contextmanager

import anndata as ad
import h5py


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
            # Categorical: need to decode codes -> categories
            categories = [_decode_bytes(v) for v in item["categories"][:]]
            codes = item["codes"][:]
            names = [categories[c] if c >= 0 else "" for c in codes]
        else:
            names = [_decode_bytes(v) for v in item[:]]

        gene_names = set(names)

        eid_to_var_name = {
            _strip_ensembl_version(eid): name for eid, name in zip(index, names)
        }

        return gene_names, eid_to_var_name
