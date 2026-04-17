"""Tests for compress_h5ad."""

import json

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp
from hca_anndata_tools.compress import compress_h5ad


def _write_uncompressed(path) -> None:
    """Write a small h5ad with no compression on any chunked dataset."""
    rng = np.random.default_rng(7)
    X = sp.random(40, 15, density=0.3, format="csr", dtype=np.float32, random_state=rng)  # pyright: ignore[reportCallIssue]
    obs = pd.DataFrame(
        {"cell_type": pd.Categorical(rng.choice(["A", "B"], 40))},
        index=[f"c{i}" for i in range(40)],  # pyright: ignore[reportArgumentType]
    )
    var = pd.DataFrame(index=[f"g{i}" for i in range(15)])  # pyright: ignore[reportArgumentType]
    adata = ad.AnnData(X=X, obs=obs, var=var)
    adata.obsm["X_umap"] = rng.standard_normal((40, 2)).astype(np.float32)
    adata.uns["title"] = "Uncompressed test"
    adata.write_h5ad(path, compression=None)


@pytest.fixture
def uncompressed_h5ad(tmp_path):
    path = tmp_path / "uncompressed.h5ad"
    _write_uncompressed(path)
    return path


@pytest.fixture
def compressed_h5ad(tmp_path):
    """An h5ad that was written with gzip compression."""
    path = tmp_path / "compressed.h5ad"
    _write_uncompressed(path)
    adata = ad.read_h5ad(path)
    adata.write_h5ad(path, compression="gzip")
    return path


def _dataset_filter(path, dataset_path) -> tuple[str | None, tuple | None]:
    """Return (compression, compression_opts) for an HDF5 dataset."""
    with h5py.File(path, "r") as f:
        ds = f[dataset_path]
        return getattr(ds, "compression", None), getattr(ds, "compression_opts", None)


def _x_compression(path) -> str | None:
    with h5py.File(path, "r") as f:
        x = f["X"]
        target = x["data"] if isinstance(x, h5py.Group) and "data" in x else x
        return getattr(target, "compression", None)


def test_compress_h5ad_writes_compressed_output(uncompressed_h5ad):
    assert _x_compression(uncompressed_h5ad) is None

    result = compress_h5ad(str(uncompressed_h5ad))

    assert "error" not in result
    assert "output_path" in result
    assert _x_compression(result["output_path"]) == "gzip"
    assert result["compression"] == "gzip:4"
    assert result["size_before_bytes"] > 0
    assert result["size_after_bytes"] > 0


def test_compress_h5ad_applies_filter_to_obsm(uncompressed_h5ad):
    result = compress_h5ad(str(uncompressed_h5ad))
    compression, _ = _dataset_filter(result["output_path"], "obsm/X_umap")
    assert compression == "gzip"


def test_compress_h5ad_custom_level(uncompressed_h5ad):
    result = compress_h5ad(str(uncompressed_h5ad), compression_level=9)
    assert "error" not in result
    assert result["compression"] == "gzip:9"
    _, opts = _dataset_filter(result["output_path"], "X/data")
    assert opts == 9


def test_compress_h5ad_skips_when_already_compressed(compressed_h5ad):
    result = compress_h5ad(str(compressed_h5ad))
    assert result.get("skipped") is True
    assert "already" in result["reason"].lower()
    assert result["current_compression"] == "gzip"


def test_compress_h5ad_force_rewrites_compressed(compressed_h5ad):
    result = compress_h5ad(str(compressed_h5ad), force=True)
    assert "error" not in result
    assert result.get("skipped") is not True
    assert _x_compression(result["output_path"]) == "gzip"


def test_compress_h5ad_edit_log_written(uncompressed_h5ad):
    result = compress_h5ad(str(uncompressed_h5ad))
    assert "error" not in result

    with h5py.File(result["output_path"], "r") as f:
        log_raw = f["uns/provenance/edit_history"][()]
    log = json.loads(log_raw.decode("utf-8") if isinstance(log_raw, bytes) else log_raw)
    assert len(log) == 1
    entry = log[0]
    assert entry["operation"] == "compress_h5ad"
    assert entry["details"]["compression"] == "gzip"
    assert entry["details"]["compression_level"] == 4
    assert entry["details"]["size_before_bytes"] == result["size_before_bytes"]
    assert entry["details"]["size_after_bytes"] == result["size_after_bytes"]
    assert entry["details"]["ratio"] == result["ratio"]
    assert "source_sha256" in entry


def test_compress_h5ad_data_roundtrip(uncompressed_h5ad):
    original = ad.read_h5ad(uncompressed_h5ad)
    result = compress_h5ad(str(uncompressed_h5ad))
    assert "error" not in result

    compressed = ad.read_h5ad(result["output_path"])
    np.testing.assert_array_equal(original.X.toarray(), compressed.X.toarray())  # pyright: ignore[reportAttributeAccessIssue]
    pd.testing.assert_frame_equal(original.obs, compressed.obs)
    pd.testing.assert_frame_equal(original.var, compressed.var)
    np.testing.assert_array_equal(original.obsm["X_umap"], compressed.obsm["X_umap"])
    assert compressed.uns["title"] == original.uns["title"]


def test_compress_h5ad_invalid_compression(uncompressed_h5ad):
    result = compress_h5ad(str(uncompressed_h5ad), compression="lzf")  # pyright: ignore[reportArgumentType]
    assert "error" in result
    assert "gzip" in result["error"]


def test_compress_h5ad_invalid_level(uncompressed_h5ad):
    result = compress_h5ad(str(uncompressed_h5ad), compression_level=42)
    assert "error" in result
    assert "0-9" in result["error"]


def test_compress_h5ad_missing_file(tmp_path):
    result = compress_h5ad(str(tmp_path / "does-not-exist.h5ad"))
    assert "error" in result


def test_compress_h5ad_non_h5ad_extension(tmp_path):
    path = tmp_path / "foo.txt"
    path.write_text("not an h5ad")
    result = compress_h5ad(str(path))
    assert "error" in result


def test_compress_h5ad_appends_to_existing_edit_log(uncompressed_h5ad):
    # Seed an existing edit log entry via h5py
    with h5py.File(uncompressed_h5ad, "a") as f:
        prov = f.require_group("uns/provenance")
        prov.attrs.setdefault("encoding-type", "dict")
        prov.attrs.setdefault("encoding-version", "0.1.0")
        existing = json.dumps([{
            "timestamp": "2026-01-01T00:00:00+00:00",
            "tool": "hca-anndata-tools",
            "tool_version": "0.0.0",
            "operation": "fake_prior",
            "description": "seeded prior entry",
            "source_file": "uncompressed.h5ad",
            "source_sha256": "0" * 64,
        }])
        ds = prov.create_dataset("edit_history", data=existing)
        ds.attrs["encoding-type"] = "string"
        ds.attrs["encoding-version"] = "0.2.0"

    result = compress_h5ad(str(uncompressed_h5ad))
    assert "error" not in result

    with h5py.File(result["output_path"], "r") as f:
        log_raw = f["uns/provenance/edit_history"][()]
    log = json.loads(log_raw.decode("utf-8") if isinstance(log_raw, bytes) else log_raw)
    assert len(log) == 2
    assert log[0]["operation"] == "fake_prior"
    assert log[1]["operation"] == "compress_h5ad"
