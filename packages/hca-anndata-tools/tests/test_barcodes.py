"""Tests for the barcode check (#679).

Every fixture is an obs index written through anndata's own writer from a
list of IDs, so the reader under test never builds its own fixture. Barcodes
are random 16-mers (or 14-mers for the Chromium v1 cases) — the check does
no whitelist lookup, so any ``ACGT`` run of the right length is a barcode.
"""

from __future__ import annotations

import json

import anndata as ad
import numpy as np
import pandas as pd

from hca_anndata_tools.barcodes import check_barcodes
from hca_anndata_tools.qc import SAMPLE_ID_LIMIT
from hca_anndata_tools.testing import make_nullable_index

RNG = np.random.default_rng(679)


def _barcode(length: int = 16) -> str:
    return "".join(RNG.choice(list("ACGT"), length))


def _write(path, ids: list[str]):
    ad.AnnData(obs=pd.DataFrame(index=pd.Index(ids, name="cellID"))).write_h5ad(path)  # pyright: ignore[reportArgumentType]
    return path


def _ok(result: dict) -> dict:
    assert "error" not in result, result
    return result


# --- AC4 / AC5 / AC6: every cell, no cell, some cells ---------------------


def test_every_cell_has_a_barcode(tmp_path):
    ids = [f"Kong2023_N{i}_L1-{_barcode()}" for i in range(12)]
    result = _ok(check_barcodes(_write(tmp_path / "a.h5ad", ids)))
    assert result["n_obs"] == 12
    assert result["structure"] == {"with_barcode": 12, "fraction": 1.0, "by_length": {"16": 12}}
    assert result["findings"] == []


def test_no_cell_has_a_barcode(tmp_path):
    n = SAMPLE_ID_LIMIT + 5
    ids = [f"cell_{i}" for i in range(n)]
    result = _ok(check_barcodes(_write(tmp_path / "a.h5ad", ids)))
    assert result["structure"] == {"with_barcode": 0, "fraction": 0.0, "by_length": {"0": n}}
    assert [f["code"] for f in result["findings"]] == ["no_barcode_in_index"]
    f = result["findings"][0]
    assert f["count"] == n
    assert f["sample_ids"] == ids[:SAMPLE_ID_LIMIT]
    assert f["element"] == "obs/cellID"


def test_some_cells_have_no_barcode(tmp_path):
    with_bc = [f"S{i}_{_barcode()}-1" for i in range(6)]
    without = [f"blood_qc-{5000000 + i}" for i in range(4)]
    ids = with_bc[:3] + without[:2] + with_bc[3:] + without[2:]
    result = _ok(check_barcodes(_write(tmp_path / "a.h5ad", ids)))
    assert result["structure"]["with_barcode"] == 6
    assert result["structure"]["fraction"] == 0.6
    f = result["findings"][0]
    assert f["count"] == 4
    assert f["sample_ids"] == without  # only the barcode-less cells, in file order


# --- AC7: lengths -------------------------------------------------------------


def test_legacy_v1_barcodes_are_counted_by_length(tmp_path):
    ids = [f"N1B_epi_{_barcode(14)}-1" for _ in range(3)] + [f"N1B_epi_{_barcode(16)}-1" for _ in range(5)]
    result = _ok(check_barcodes(_write(tmp_path / "a.h5ad", ids)))
    assert result["structure"]["by_length"] == {"16": 5, "14": 3}
    assert result["structure"]["fraction"] == 1.0
    assert result["findings"] == []


def test_every_run_is_counted_at_its_own_length(tmp_path):
    # A 20-base run is not a 10x barcode; filing it under 16 would hide exactly
    # what the length count exists to show. An 11-base run is below Lattice's floor.
    ids = [f"a_{_barcode(20)}", f"b_{_barcode(12)}", f"c_{_barcode(13)}", f"d_{_barcode(11)}"]
    result = _ok(check_barcodes(_write(tmp_path / "a.h5ad", ids)))
    assert result["structure"]["by_length"] == {"20": 1, "13": 1, "12": 1, "0": 1}
    assert result["findings"][0]["sample_ids"] == [ids[3]]


def test_only_the_first_run_sets_the_length(tmp_path):
    # A multiome ID carries a GEX and an ATAC barcode; the cell has a barcode, counted once.
    ids = [f"{_barcode()}_{_barcode()}-1" for _ in range(6)]
    result = _ok(check_barcodes(_write(tmp_path / "a.h5ad", ids)))
    assert result["structure"] == {"with_barcode": 6, "fraction": 1.0, "by_length": {"16": 6}}


# --- AC8: fixed result, no verdict --------------------------------------------


def test_result_is_fixed_and_serializable(tmp_path):
    ids = [f"S_{_barcode()}", "cell_1"]
    result = _ok(check_barcodes(_write(tmp_path / "a.h5ad", ids)))
    assert set(result) == {"filename", "n_obs", "structure", "findings"}
    assert set(result["structure"]) == {"with_barcode", "fraction", "by_length"}
    assert set(result["findings"][0]) == {"code", "count", "sample_ids", "element"}
    assert result["filename"] == "a.h5ad"
    json.dumps(result)  # no numpy scalars


def test_empty_obs_is_a_clean_result(tmp_path):
    result = _ok(check_barcodes(_write(tmp_path / "a.h5ad", [])))
    assert result["structure"] == {"with_barcode": 0, "fraction": 0.0, "by_length": {}}
    assert result["findings"] == []


# --- AC2: refusals ------------------------------------------------------------


def test_masked_index_refuses_by_name(tmp_path):
    path = _write(tmp_path / "a.h5ad", [f"S_{_barcode()}" for _ in range(3)])
    make_nullable_index(path, masked=1)
    result = check_barcodes(path)
    assert "obs index" in result["error"] and "missing value" in result["error"]
    assert "traceback" not in result


def test_missing_file(tmp_path):
    result = check_barcodes(str(tmp_path / "nope.h5ad"))
    assert result["error"].startswith("File not found")
