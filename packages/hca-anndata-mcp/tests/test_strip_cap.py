"""Unit tests for the strip_cap_annotations MCP wrapper."""

import json

import anndata as ad
import numpy as np
import pandas as pd

from hca_anndata_mcp.tools.strip_cap import strip_cap_annotations


def test_strip_cap_missing_file():
    result = strip_cap_annotations("/nonexistent/file.h5ad")
    assert "error" in result
    assert "File not found" in result["error"]


def test_strip_cap_through_wrapper(tmp_path):
    """Happy path through the wrapper: pins the wiring only — result keys and
    one cheap observable. Strip semantics are the tools layer's tests."""
    obs = pd.DataFrame(
        {"set--cell_fullname": pd.Categorical(["T cell", "B cell"])},
        index=pd.Index(["c1", "c2"], name="cellID"),
    )
    adata = ad.AnnData(X=np.zeros((2, 2), dtype=np.float32), obs=obs)
    adata.uns["cellannotation_metadata"] = {"set": {}}
    adata.uns["cellannotation_schema_version"] = "1.0.0"
    # The provenance gate strips CAP uns metadata only when our own import
    # put it there.
    adata.uns["provenance"] = {
        "edit_history": json.dumps(
            [
                {
                    "timestamp": "2026-05-27T00:00:00Z",
                    "tool": "hca-anndata-tools",
                    "tool_version": "0.0.1",
                    "operation": "import_cap_annotations",
                    "description": "test import",
                }
            ]
        )
    }
    adata.write_h5ad(tmp_path / "test.h5ad")

    result = strip_cap_annotations(str(tmp_path / "test.h5ad"))

    assert "error" not in result
    assert result["obs_columns_removed"] == ["set--cell_fullname"]
    out = ad.read_h5ad(result["output_path"])
    assert "cellannotation_metadata" not in out.uns
    assert list(out.obs.columns) == []
