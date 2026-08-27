"""Tests for rename_cell_ids.

The fixture (``create_hca_h5ad`` / ``HCA_TEST_ROWS`` in ``testing.py``)
mirrors the defect the tool was built for (#533): two ID families that share
a prefix because one family lost its distinguishing segment, with the
surviving distinction held only in an obs column. The index is deliberately
named ``cellID`` — the breast integrated object's name — so the
default-``_index`` assumption can't creep back in; one test covers the
default name.
"""

import json
from pathlib import Path

import anndata as ad
import h5py
import numpy as np
import pytest

from hca_anndata_tools import rename_cell_ids
from hca_anndata_tools._io import obs_index_name, read_obs_index
from hca_anndata_tools.testing import (
    HCA_TEST_ROWS,
    assert_no_snapshot_written,
    create_hca_h5ad,
    make_fixed_width_byte_array,
    make_nullable_index,
    make_nullable_string_array,
    make_plain_string_column,
)

B1_IDS = [cell_id for cell_id, sample in HCA_TEST_ROWS if sample == "B1_0023"]


@pytest.fixture
def hca_path(tmp_path) -> Path:
    return create_hca_h5ad(tmp_path / "test.h5ad")


def test_rename_happy_path(hca_path):
    before = ad.read_h5ad(hca_path)

    result = rename_cell_ids(
        str(hca_path),
        column="sample_id",
        value="B1_0023",
        prefix_from="MH_mix_",
        prefix_to="MH_mix_BR1_",
    )

    assert "error" not in result
    assert result["n_selected"] == len(B1_IDS)
    assert result["n_renamed"] == result["n_selected"]
    assert result["examples"][0] == ["MH_mix_AAA", "MH_mix_BR1_AAA"]

    after = ad.read_h5ad(result["output_path"])
    # Selected rows renamed, everything else untouched, order preserved.
    expected = [
        "MH_mix_BR1_" + cell_id[len("MH_mix_") :] if sample == "B1_0023" else cell_id
        for cell_id, sample in HCA_TEST_ROWS
    ]
    assert list(after.obs_names) == expected
    # No rows moved: per-row data still aligns by position.
    assert list(after.obs["sample_id"]) == list(before.obs["sample_id"])
    np.testing.assert_array_equal(after.X, before.X)
    np.testing.assert_array_equal(after.obsm["X_umap"], before.obsm["X_umap"])
    # The original file was not modified.
    assert list(ad.read_h5ad(hca_path).obs_names) == list(before.obs_names)


def test_rename_preserves_index_attr_name(hca_path):
    result = rename_cell_ids(
        str(hca_path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )
    with h5py.File(result["output_path"], "r") as f:
        assert f["obs"].attrs["_index"] == "cellID"
        assert "cellID" in f["obs"]


def test_rename_writes_edit_log(hca_path):
    result = rename_cell_ids(
        str(hca_path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )
    after = ad.read_h5ad(result["output_path"])

    log = json.loads(after.uns["provenance"]["edit_history"])
    (entry,) = [e for e in log if e["operation"] == "rename_cell_ids"]
    assert entry["details"]["column"] == "sample_id"
    assert entry["details"]["value"] == "B1_0023"
    assert entry["details"]["n_renamed"] == len(B1_IDS)


def test_rename_default_index_name(tmp_path):
    """A file whose obs index uses anndata's default ``_index`` name works too."""
    path = create_hca_h5ad(tmp_path / "test.h5ad", index_name=None)
    result = rename_cell_ids(str(path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="X_")
    assert "error" not in result
    assert result["n_renamed"] == len(B1_IDS)


def test_rename_non_categorical_selector(tmp_path):
    """The selector column read must handle plain string datasets, not just
    categoricals."""
    path = create_hca_h5ad(tmp_path / "test.h5ad", categorical_sample=False)
    result = rename_cell_ids(
        str(path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )
    assert "error" not in result
    assert result["n_selected"] == len(B1_IDS)


def test_rename_refuses_zero_matches(hca_path):
    result = rename_cell_ids(str(hca_path), column="sample_id", value="nope", prefix_from="MH_mix_", prefix_to="X_")
    assert "no rows match" in result["error"]


def test_rename_refuses_missing_column(hca_path):
    result = rename_cell_ids(str(hca_path), column="donor", value="B1_0023", prefix_from="MH_mix_", prefix_to="X_")
    assert "not present" in result["error"]


def test_rename_refuses_index_as_selector(hca_path):
    result = rename_cell_ids(str(hca_path), column="cellID", value="MH_mix_AAA", prefix_from="MH_mix_", prefix_to="X_")
    assert "obs index" in result["error"]


def test_rename_refuses_prefix_disagreement(hca_path):
    """Selected rows that don't carry prefix_from mean the two witnesses —
    selector and substitution — disagree; nothing may be written."""
    result = rename_cell_ids(str(hca_path), column="sample_id", value="N_0123", prefix_from="MH_mix_", prefix_to="X_")
    assert "do not start with" in result["error"]
    assert "2 of 4" in result["error"]  # the two N1105_epi_* cells
    assert_no_snapshot_written(hca_path)


def test_rename_refuses_collision(tmp_path):
    """A rename that would produce a duplicate ID is refused and the file left
    untouched — introducing collisions is the defect the tool exists to fix."""
    path = create_hca_h5ad(tmp_path / "test.h5ad", extra_rows=[("MH_mix_BR1_AAA", "N_0123")])
    before = list(ad.read_h5ad(path).obs_names)

    result = rename_cell_ids(
        str(path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )

    assert "duplicate cell IDs" in result["error"]
    assert "MH_mix_BR1_AAA" in result["error"]
    assert list(ad.read_h5ad(path).obs_names) == before
    assert_no_snapshot_written(path)


def test_rename_refuses_cellxgene_layout(sample_h5ad):
    """CellxGENE-layout files (e.g. CAP exports) are refused outright: the
    export's source system is the record of truth, and a local rename forks
    it. Read-only, so the session-scoped fixture is safe to share."""
    result = rename_cell_ids(str(sample_h5ad), column="tissue", value="brain", prefix_from="cell_", prefix_to="c_")
    assert "CellxGENE" in result["error"]


def test_rename_updates_obsm_dataframe_index(tmp_path):
    """A DataFrame in obsm carries a duplicate copy of the cell IDs; renaming
    only the obs index would leave a file anndata refuses to read."""
    path = create_hca_h5ad(tmp_path / "test.h5ad", obsm_dataframe=True)

    result = rename_cell_ids(
        str(path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )

    assert "error" not in result
    after = ad.read_h5ad(result["output_path"])  # raises if the copies diverged
    assert list(after.obsm["per_cell_scores"].index) == list(after.obs_names)
    assert "MH_mix_BR1_AAA" in after.obsm["per_cell_scores"].index


def test_rename_refuses_mismatched_obsm_dataframe_index(tmp_path):
    """An obsm DataFrame index that already disagrees with the obs index marks
    a broken file — refuse rather than paper over it."""
    path = create_hca_h5ad(tmp_path / "test.h5ad", obsm_dataframe=True)
    with h5py.File(path, "a") as f:
        sub = f["obsm"]["per_cell_scores"]
        index_name = sub.attrs["_index"]
        broken = sub[index_name].asstr()[:]
        broken[0] = "someone_else_entirely"
        del sub[index_name]
        # Stamp the encoding metadata a real AnnData writer would leave: an
        # unstamped element is a different defect from the one under test, and
        # reading one warns.
        rebuilt = f["obsm"]["per_cell_scores"].create_dataset(index_name, data=broken.astype(object))
        rebuilt.attrs["encoding-type"] = "string-array"
        rebuilt.attrs["encoding-version"] = "0.2.0"

    result = rename_cell_ids(
        str(path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )

    assert "internally inconsistent" in result["error"]
    assert_no_snapshot_written(path)


def test_rename_same_second_collision_resolves_after_waiting(tmp_path, pin_snapshot_names):
    """The common case since #597: a name taken this second is resolved by
    waiting out the boundary, not by failing a run the caller must re-issue."""
    path = create_hca_h5ad(tmp_path / "test.h5ad")
    first = rename_cell_ids(
        str(path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )
    snapshot = Path(first["output_path"])
    pin_snapshot_names(str(snapshot), str(tmp_path / "test-edit-2026-08-24-00-00-01.h5ad"))

    result = rename_cell_ids(
        str(snapshot), column="sample_id", value="B1_0023", prefix_from="MH_mix_BR1_", prefix_to="Z_"
    )

    assert "error" not in result
    assert Path(result["output_path"]).name == "test-edit-2026-08-24-00-00-01.h5ad"


def test_rename_same_second_snapshot_refused(tmp_path, pin_snapshot_names):
    """A collision that survives the boundary wait is refused before anything
    is touched — the source snapshot must not be unlinked (#598)."""
    path = create_hca_h5ad(tmp_path / "test.h5ad")
    first = rename_cell_ids(
        str(path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )
    snapshot = Path(first["output_path"])

    pin_snapshot_names()

    result = rename_cell_ids(
        str(snapshot), column="sample_id", value="B1_0023", prefix_from="MH_mix_BR1_", prefix_to="Z_"
    )

    assert "already exists" in result["error"]
    assert snapshot.is_file()  # the source snapshot survived


def test_rename_refuses_pre_existing_duplicates(tmp_path):
    """Duplicates the file already had are named as such — the remedy (repair
    the file) differs from the remedy for a collision the rename would cause."""
    with pytest.warns(UserWarning, match="Observation names are not unique"):
        path = create_hca_h5ad(tmp_path / "test.h5ad", extra_rows=[("N1105_epi_AAA", "N_0123")])

    result = rename_cell_ids(
        str(path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )

    assert "before any rename" in result["error"]
    assert "N1105_epi_AAA" in result["error"]
    assert_no_snapshot_written(path)


def test_rename_refuses_pre_existing_duplicates_the_rename_would_resolve(tmp_path):
    """The pre-existing gate fires even when the rename would make the index
    unique — resolving a collision by renaming one side of it is a curation
    decision, not a side effect this tool may write."""
    with pytest.warns(UserWarning, match="Observation names are not unique"):
        # Duplicate of a selected B1 ID: renaming the B1 copy would de-collide.
        path = create_hca_h5ad(tmp_path / "test.h5ad", extra_rows=[("MH_mix_AAA", "N_0123")])

    result = rename_cell_ids(
        str(path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )

    assert "before any rename" in result["error"]
    assert "MH_mix_AAA" in result["error"]
    assert_no_snapshot_written(path)


def test_rename_refuses_legacy_cap_layout(tmp_path):
    """The deprecated top-level CAP layout marks a CAP export even when
    uns['schema_version'] is absent — parity with drop.py / copy_cap.py (#552)."""
    path = create_hca_h5ad(tmp_path / "legacy.h5ad")
    adata = ad.read_h5ad(path)
    adata.uns["cellannotation_schema_version"] = "1.0.0"
    adata.write_h5ad(path)

    result = rename_cell_ids(
        str(path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )

    assert "deprecated top-level CAP layout" in result["error"]
    assert_no_snapshot_written(path)


def test_rename_nullable_dtype_selector_selects_nothing(tmp_path):
    """A pandas nullable-dtype column (values+mask group, no categories) can
    never equal a string value; it must refuse cleanly, not crash on .dtype."""
    import pandas as pd

    path = create_hca_h5ad(tmp_path / "nullable.h5ad")
    adata = ad.read_h5ad(path)
    adata.obs["qc_flag"] = pd.array([True, False] * (adata.n_obs // 2) + [True] * (adata.n_obs % 2), dtype="boolean")
    adata.write_h5ad(path)

    result = rename_cell_ids(str(path), column="qc_flag", value="True", prefix_from="MH_mix_", prefix_to="X_")

    assert "no rows match" in result["error"]


def test_rename_missing_file():
    result = rename_cell_ids("/nonexistent/file.h5ad", column="a", value="b", prefix_from="x_", prefix_to="y_")
    assert "File not found" in result["error"]


@pytest.mark.parametrize(
    ("column", "value", "prefix_from", "prefix_to", "expected"),
    [
        (7, "B1_0023", "MH_mix_", "X_", "must be strings"),
        ("sample_id", None, "MH_mix_", "X_", "must be strings"),
        ("obs/sample_id", "B1_0023", "MH_mix_", "X_", "cannot contain '/'"),
        ("  ", "B1_0023", "MH_mix_", "X_", "be blank"),
        ("sample_id", "B1_0023", "", "X_", "non-empty"),
        ("sample_id", "B1_0023", "MH_mix_", "MH_mix_", "identical"),
        ("sample_id", "B1_0023", "MH_mix_", 3, "must be a string"),
    ],
)
def test_rename_refuses_malformed_arguments(hca_path, column, value, prefix_from, prefix_to, expected):
    """Argument shape is checked before any file is opened, and every problem
    is reported — MCP callers arrive as decoded JSON with no type checking."""
    result = rename_cell_ids(str(hca_path), column=column, value=value, prefix_from=prefix_from, prefix_to=prefix_to)
    assert expected in result["error"]
    assert_no_snapshot_written(hca_path)


def test_rename_normalizes_a_nullable_index_as_it_rewrites(tmp_path):
    """Every write fixes the format in its own path (#641): rename on a
    nullable-index file just works — replace_string_dataset writes the
    renamed IDs as a plain string-array, no refusal, no other tool."""
    path = create_hca_h5ad(tmp_path / "test.h5ad")
    make_nullable_index(path)

    result = rename_cell_ids(
        str(path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )

    assert "error" not in result, result.get("error")
    assert result["n_renamed"] == len(B1_IDS)
    with h5py.File(result["output_path"], "r") as f:
        obs = f["obs"]
        idx = obs[obs_index_name(obs)]
        assert isinstance(idx, h5py.Dataset)  # normalized, not a values+mask group
        assert "MH_mix_BR1_AAA" in idx.asstr()[:]


def test_rename_refuses_a_masked_index_before_taking_a_snapshot(tmp_path):
    """The one remaining encoding-adjacent refusal is a data problem: a
    masked index has cells with no ID, refused by read_index before the
    snapshot."""
    path = create_hca_h5ad(tmp_path / "test.h5ad")
    make_nullable_index(path, masked=1)

    before = set(tmp_path.iterdir())
    result = rename_cell_ids(
        str(path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )

    assert "error" in result
    assert "missing value" in result["error"]
    assert set(tmp_path.iterdir()) == before


def test_rename_accepts_a_fixed_width_byte_index(tmp_path):
    """The writable guard must judge the container, not the encoding name.

    anndata stamps a fixed-width byte array ``array``, not ``string-array``.
    It is still a plain Dataset, so replace_string_dataset handles it — an
    encoding-name check refused a file that renames perfectly well, while
    get_storage_info reported the same file clean (hca-validation-tools#637
    review).
    """
    path = create_hca_h5ad(tmp_path / "fixed.h5ad")
    with h5py.File(path, "r+") as f:
        obs = f["obs"]
        make_fixed_width_byte_array(obs, obs_index_name(obs))

    result = rename_cell_ids(
        str(path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )

    assert "error" not in result
    assert result["n_renamed"] == 3
    # Not just a status: the renamed IDs must survive the round trip. The
    # source dtype is fixed-width, so a rewrite that kept it would clip the
    # longer prefix silently.
    ids = read_obs_index(result["output_path"])
    assert "MH_mix_BR1_AAA" in ids
    assert "MH_mix_TTT" in ids


def test_rename_selects_rows_from_a_nullable_string_selector(tmp_path):
    """A nullable-string selector column holds real values the readers read
    (#637) — selecting nothing would report the false diagnosis "no rows
    match" on the liver shape. A masked row equals nothing and never matches.

    anndata converts string obs columns to categoricals on write
    (strings_to_categoricals), so the plain string dataset is built directly
    before conversion to the nullable group.
    """
    path = create_hca_h5ad(tmp_path / "nullable_sel.h5ad")
    samples = [sample for _, sample in HCA_TEST_ROWS]
    with h5py.File(path, "r+") as f:
        obs = f["obs"]
        make_plain_string_column(obs, "sample_id", samples)
        # Masks row 0 (MH_mix_AAA, B1_0023): a masked row must not match.
        make_nullable_string_array(obs, "sample_id", masked=1)

    result = rename_cell_ids(
        str(path), column="sample_id", value="B1_0023", prefix_from="MH_mix_", prefix_to="MH_mix_BR1_"
    )

    assert "error" not in result, result.get("error")
    assert result["n_selected"] == len(B1_IDS) - 1  # the masked row did not match
    assert result["n_selector_masked"] == 1  # ...and the skip is reported
    after = ad.read_h5ad(result["output_path"])
    assert "MH_mix_AAA" in after.obs_names  # masked selector row: untouched
    assert "MH_mix_BR1_CCC" in after.obs_names
    assert "MH_mix_BR1_GGG" in after.obs_names
