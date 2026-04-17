"""Tests for check_schema_type."""

import anndata as ad
import numpy as np
import pandas as pd
import scipy.sparse as sp
from hca_anndata_tools.inspect import check_schema_type


def _write_h5ad(path, *, schema_version=None):
    X = sp.csr_matrix(np.zeros((5, 5), dtype=np.float32))
    adata = ad.AnnData(
        X=X,
        obs=pd.DataFrame(index=[f"c{i}" for i in range(5)]),  # pyright: ignore[reportArgumentType]
        var=pd.DataFrame(index=[f"g{i}" for i in range(5)]),  # pyright: ignore[reportArgumentType]
    )
    if schema_version is not None:
        adata.uns["schema_version"] = schema_version
    adata.write_h5ad(path)
    return path


def test_check_schema_type_cellxgene(tmp_path):
    path = _write_h5ad(tmp_path / "cxg.h5ad", schema_version="6.0.0")

    result = check_schema_type(str(path))
    assert "error" not in result
    assert result["schema"] == "cellxgene"
    assert result["schema_version"] == "6.0.0"
    assert result["filename"] == "cxg.h5ad"


def test_check_schema_type_hca_when_no_schema_version(tmp_path):
    path = _write_h5ad(tmp_path / "hca.h5ad")

    result = check_schema_type(str(path))
    assert "error" not in result
    assert result["schema"] == "hca"
    assert result["schema_version"] is None


def test_check_schema_type_empty_schema_version_treated_as_hca(tmp_path):
    """An empty/whitespace schema_version is not a usable CellxGENE marker."""
    path = _write_h5ad(tmp_path / "empty_ver.h5ad", schema_version="   ")

    result = check_schema_type(str(path))
    assert result["schema"] == "hca"
    assert result["schema_version"] is None


def test_check_schema_type_missing_file():
    result = check_schema_type("/nonexistent/does-not-exist.h5ad")
    assert "error" in result


def test_check_schema_type_return_shape_is_fixed(tmp_path):
    path = _write_h5ad(tmp_path / "shape.h5ad", schema_version="6.0.0")

    expected = {"filename", "schema", "schema_version"}
    assert set(check_schema_type(str(path)).keys()) == expected


def test_check_schema_type_hca_when_cellxgene_in_provenance_only(tmp_path):
    """After convert_cellxgene_to_hca, the CellxGENE fields live in
    uns/provenance/cellxgene and the top-level schema_version is gone —
    the file must classify as HCA, not CellxGENE."""
    X = sp.csr_matrix(np.zeros((5, 5), dtype=np.float32))
    adata = ad.AnnData(
        X=X,
        obs=pd.DataFrame(index=[f"c{i}" for i in range(5)]),  # pyright: ignore[reportArgumentType]
        var=pd.DataFrame(index=[f"g{i}" for i in range(5)]),  # pyright: ignore[reportArgumentType]
    )
    # Matches what convert_cellxgene_to_hca produces: CellxGENE fields
    # relocated under provenance, no top-level schema_version.
    adata.uns["provenance"] = {
        "cellxgene": {
            "schema_version": "6.0.0",
            "schema_reference": "https://github.com/chanzuckerberg/single-cell-curation/...",
        }
    }
    path = tmp_path / "converted.h5ad"
    adata.write_h5ad(path)

    result = check_schema_type(str(path))
    assert result["schema"] == "hca"
    assert result["schema_version"] is None
