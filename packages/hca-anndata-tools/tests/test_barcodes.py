"""Tests for the barcode structure report (#679).

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
import pytest

from hca_anndata_tools.barcodes import DEFAULT_SHAPES, check_barcodes
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


def _codes(result: dict) -> list[str]:
    return [f["code"] for f in result["findings"]]


# --- AC4 / AC5 / AC6: every cell, no cell, some cells ---------------------


def test_every_cell_has_a_barcode(tmp_path):
    ids = [f"Kong2023_N{i}_L1-{_barcode()}" for i in range(12)]
    result = _ok(check_barcodes(_write(tmp_path / "a.h5ad", ids)))
    assert result["n_obs"] == 12
    assert result["structure"]["cells"] == 12
    assert result["structure"]["with_barcode"] == 12
    assert result["structure"]["fraction"] == 1.0
    assert result["structure"]["by_length"] == {"16": 12}
    assert result["findings"] == []


def test_no_cell_has_a_barcode(tmp_path):
    n = SAMPLE_ID_LIMIT + 5
    ids = [f"cell_{i}" for i in range(n)]
    result = _ok(check_barcodes(_write(tmp_path / "a.h5ad", ids)))
    assert result["structure"]["with_barcode"] == 0
    assert result["structure"]["fraction"] == 0.0
    assert result["structure"]["by_length"] == {"0": n}
    assert _codes(result) == ["no_barcode_in_index"]
    f = result["findings"][0]
    assert f["count"] == n
    assert f["sample_ids"] == ids[:SAMPLE_ID_LIMIT]
    assert f["matrix"] == "obs/cellID"
    assert f["shapes"] == [{"shape": "cell_#", "cells": n}]


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
    assert f["shapes"] == [{"shape": "blood_qc-#", "cells": 4}]


# --- AC7 / AC8: shapes ------------------------------------------------------


def test_shapes_name_the_id_families_most_common_first(tmp_path):
    ids = (
        [f"Kong2023_N{i}_L{i % 2}-{_barcode()}" for i in range(5)]
        + [f"BasuGCARNA_HA{i}TI_{_barcode()}-1" for i in range(3)]
        + [f"Krzak2023_{119779 + i}" for i in range(4)]
    )
    result = _ok(check_barcodes(_write(tmp_path / "a.h5ad", ids)))
    assert result["structure"]["shapes"] == [
        {"shape": "Kong#_N#_L#-<16nt>", "cells": 5},
        {"shape": "Krzak#_#", "cells": 4},
        {"shape": "BasuGCARNA_HA#TI_<16nt>-#", "cells": 3},
    ]
    # AC8: the finding says which family lacks barcodes
    assert result["findings"][0]["shapes"] == [{"shape": "Krzak#_#", "cells": 4}]
    assert result["findings"][0]["count"] == 4


def test_shape_of_the_breast_example(tmp_path):
    result = _ok(check_barcodes(_write(tmp_path / "a.h5ad", ["MH0023_mix_ACGTACGTACGTACGT-1"])))
    assert result["structure"]["shapes"] == [{"shape": "MH#_mix_<16nt>-#", "cells": 1}]


# --- AC9: lengths -----------------------------------------------------------


def test_legacy_v1_barcodes_are_counted_by_length(tmp_path):
    ids = [f"N1B_epi_{_barcode(14)}-1" for _ in range(3)] + [f"N1B_epi_{_barcode(16)}-1" for _ in range(5)]
    result = _ok(check_barcodes(_write(tmp_path / "a.h5ad", ids)))
    assert result["structure"]["by_length"] == {"16": 5, "14": 3}
    assert result["structure"]["fraction"] == 1.0
    assert {s["shape"] for s in result["structure"]["shapes"]} == {"N#B_epi_<14nt>-#", "N#B_epi_<16nt>-#"}
    assert result["findings"] == []


def test_run_longer_than_a_barcode_counts_as_sixteen_and_short_runs_at_their_length(tmp_path):
    ids = [f"a_{_barcode(20)}", f"b_{_barcode(12)}", f"c_{_barcode(13)}", f"d_{_barcode(11)}"]
    result = _ok(check_barcodes(_write(tmp_path / "a.h5ad", ids)))
    assert result["structure"]["by_length"] == {"16": 1, "13": 1, "12": 1, "0": 1}
    assert result["findings"][0]["sample_ids"] == [ids[3]]


# --- AC10: the list is bounded -----------------------------------------------


def test_shapes_list_is_capped(tmp_path):
    ids = [f"{chr(65 + i)}_{_barcode()}" for i in range(DEFAULT_SHAPES + 5)]  # 25 distinct prefixes
    default = _ok(check_barcodes(_write(tmp_path / "a.h5ad", ids)))
    assert len(default["structure"]["shapes"]) == DEFAULT_SHAPES
    three = _ok(check_barcodes(tmp_path / "a.h5ad", shapes=3))
    assert len(three["structure"]["shapes"]) == 3
    assert three["structure"]["with_barcode"] == len(ids)  # the cap trims the list, not the counts


def test_finding_shapes_are_capped_too(tmp_path):
    ids = [f"{chr(65 + i)}_{i}" for i in range(5)]
    result = _ok(check_barcodes(_write(tmp_path / "a.h5ad", ids), shapes=2))
    assert len(result["findings"][0]["shapes"]) == 2
    assert result["findings"][0]["count"] == 5


@pytest.mark.parametrize("shapes", [0, -1, 2.5, "20"])
def test_shapes_must_be_a_positive_int(tmp_path, shapes):
    result = check_barcodes(_write(tmp_path / "a.h5ad", ["cell_0"]), shapes=shapes)
    assert result == {"error": f"shapes must be a positive int, got {shapes!r}"}


# --- AC11: fixed result, no verdict -------------------------------------------


def test_result_is_fixed_and_serializable(tmp_path):
    ids = [f"S_{_barcode()}", "cell_1"]
    result = _ok(check_barcodes(_write(tmp_path / "a.h5ad", ids)))
    assert set(result) == {"filename", "n_obs", "structure", "findings"}
    assert set(result["structure"]) == {"cells", "with_barcode", "fraction", "by_length", "shapes"}
    assert set(result["findings"][0]) == {"code", "count", "sample_ids", "matrix", "shapes"}
    assert result["filename"] == "a.h5ad"
    json.dumps(result)  # no numpy scalars
    assert not any(k in result for k in ("is_valid", "verdict", "passed"))


def test_empty_obs_is_a_clean_result(tmp_path):
    result = _ok(check_barcodes(_write(tmp_path / "a.h5ad", [])))
    assert result["structure"] == {"cells": 0, "with_barcode": 0, "fraction": 0.0, "by_length": {}, "shapes": []}
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
