"""Lightweight HDF5 storage introspection for h5ad matrices.

Reports shape/nnz/dtype/size for X, raw.X and layers from the HDF5 header
without loading matrices. Pure h5py + numpy. See hca-validation-tools#447.
"""

from .h5ad_storage import get_matrix_storage

__all__ = ["get_matrix_storage"]
