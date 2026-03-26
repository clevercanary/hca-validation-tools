"""Internal I/O utilities for AnnData file access."""

import gc
from contextlib import contextmanager

import anndata as ad


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
