"""Unit tests for the check_cosmetic_labels_h5ad MCP wrapper (#377)."""

import anndata as ad
import numpy as np
import pandas as pd
from hca_anndata_mcp.tools.check_cosmetic import check_cosmetic_labels_h5ad
from hca_schema_validator.testing import create_labelable_h5ad


def test_clean_file_is_clean(tmp_path):
    path = create_labelable_h5ad(tmp_path / "clean.h5ad")
    result = check_cosmetic_labels_h5ad(str(path))
    assert "error" not in result, result
    assert result["is_clean"] is True
    assert result["warning_count"] == 0
    assert result["error_count"] == 0


def test_warning_when_cosmetic_present_and_matches(tmp_path):
    path = create_labelable_h5ad(tmp_path / "matches.h5ad")
    adata = ad.read_h5ad(path)
    adata.obs["tissue"] = "lung"  # canonical for UBERON:0002048
    adata.write_h5ad(path)

    result = check_cosmetic_labels_h5ad(str(path))
    assert "error" not in result, result
    assert result["is_clean"] is False
    assert result["warning_count"] == 1
    assert "obs['tissue']" in result["warnings"][0]
    assert result["error_count"] == 0


def test_error_on_mismatch(tmp_path):
    path = create_labelable_h5ad(tmp_path / "mismatch.h5ad")
    adata = ad.read_h5ad(path)
    adata.obs["tissue"] = "WRONG"
    adata.write_h5ad(path)

    result = check_cosmetic_labels_h5ad(str(path))
    assert any("'WRONG'" in e and "UBERON:0002048" in e for e in result["errors"])
    assert any("Either delete the cosmetic column" in e for e in result["errors"])


def test_error_on_value_with_nan_term_id(tmp_path):
    path = create_labelable_h5ad(tmp_path / "nan_id.h5ad")
    adata = ad.read_h5ad(path)
    adata.obs["cell_type"] = pd.Series(["PRODUCER_LABEL"] * adata.n_obs, index=adata.obs.index)
    adata.obs["cell_type_ontology_term_id"] = adata.obs["cell_type_ontology_term_id"].astype(object)
    adata.obs.loc[adata.obs.index[0], "cell_type_ontology_term_id"] = np.nan
    adata.write_h5ad(path)

    result = check_cosmetic_labels_h5ad(str(path))
    assert any(
        "have NaN in cell_type_ontology_term_id" in e and "PRODUCER_LABEL" in e
        for e in result["errors"]
    )


def test_missing_file():
    result = check_cosmetic_labels_h5ad("/nonexistent/file.h5ad")
    assert "error" in result
