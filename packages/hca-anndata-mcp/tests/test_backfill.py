"""Unit tests for the backfill_obs_from_source MCP wrapper."""

import anndata as ad
import numpy as np
import pandas as pd

from hca_anndata_mcp.tools.backfill import backfill_obs_from_source


def _write_h5ad(path, ids, lib_values):
    obs = pd.DataFrame({"library_id": pd.Categorical(lib_values)}, index=pd.Index(ids, name="cellID"))
    ad.AnnData(X=np.zeros((len(ids), 2), dtype=np.float32), obs=obs).write_h5ad(path)
    return str(path)


def test_backfill_missing_file():
    result = backfill_obs_from_source("/nonexistent/t.h5ad", "/nonexistent/s.h5ad", columns=["library_id"])
    assert "error" in result
    assert "not found" in result["error"]


def test_backfill_through_wrapper(tmp_path):
    """Happy path through the wrapper: pins the wiring only — result keys and
    one cheap observable. Backfill semantics are the tools layer's tests."""
    target = _write_h5ad(tmp_path / "target.h5ad", ["c1", "c2"], ["unknown", "L2"])
    source = _write_h5ad(tmp_path / "source.h5ad", ["c1", "c2"], ["L1", "L2"])

    result = backfill_obs_from_source(target, source, columns=["library_id"])

    assert "error" not in result
    assert result["total_filled"] == 1
    assert result["per_column"]["library_id"]["pct_full_after"] == 100.0
    assert list(ad.read_h5ad(result["output_path"]).obs["library_id"]) == ["L1", "L2"]
