"""Tests for backfill_obs_from_source."""

import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import pytest

from hca_anndata_tools._io import _codes_dtype
from hca_anndata_tools.backfill import backfill_obs_from_source
from hca_anndata_tools.testing import create_sample_h5ad, make_nullable_index

# The canonical scenario, one row per case the tool must handle:
#
#   cell  target lib   source lib   expectation
#   c1    NaN          L1           filled (from NaN)
#   c2    "unknown"    L2           filled (from placeholder)
#   c3    L9           "unknown"    already_set (source missing — no conflict)
#   c4    L1           L2           already_set + conflict (reported, not written)
#   c5    NaN          (absent)     unmatched
#   c6    ""           (absent)     unmatched (empty string counts as missing)
#   c7    NaN          "na"         source_missing (both sides empty)
#   x1    (absent)     L5           source cell skipped silently
TARGET_IDS = ["c1", "c2", "c3", "c4", "c5", "c6", "c7"]
TARGET_LIB = [None, "unknown", "L9", "L1", None, "", None]
SOURCE_IDS = ["c1", "c2", "c3", "c4", "c7", "x1"]
SOURCE_LIB = ["L1", "L2", "unknown", "L2", "na", "L5"]


def _make_h5ad(path, ids, columns, categorical=True, uns=None):
    """Write a minimal h5ad with the given obs columns (index named cellID).

    Categorical columns represent NaN as None; string columns cannot hold
    NaN, so string variants substitute "" (which the tool treats as missing).
    """
    obs = pd.DataFrame(index=pd.Index(ids, name="cellID"))
    for name, values in columns.items():
        if categorical:
            obs[name] = pd.Categorical(values)
        else:
            obs[name] = ["" if v is None else v for v in values]
    adata = ad.AnnData(X=np.zeros((len(ids), 2), dtype=np.float32), obs=obs)
    if uns:
        adata.uns.update(uns)
    adata.write_h5ad(path)
    return str(path)


@pytest.fixture
def target_source(tmp_path):
    target = _make_h5ad(tmp_path / "target.h5ad", TARGET_IDS, {"library_id": TARGET_LIB})
    source = _make_h5ad(tmp_path / "source.h5ad", SOURCE_IDS, {"library_id": SOURCE_LIB})
    return target, source


def test_backfill_categorical(target_source):
    target, source = target_source
    result = backfill_obs_from_source(target, source, columns=["library_id"])

    assert "error" not in result
    assert result["n_source_cells"] == 6
    assert result["n_target_cells"] == 7
    assert result["n_matched"] == 5
    assert result["total_filled"] == 2

    stats = result["per_column"]["library_id"]
    assert stats["filled"] == 2
    assert stats["already_set"] == 2
    assert stats["conflicts"] == 1
    assert stats["conflict_examples"] == [["c4", "L1", "L2"]]
    assert stats["source_missing"] == 1
    assert stats["unmatched"] == 2
    assert stats["missing_before"] == 5
    assert stats["missing_after"] == 3
    assert stats["pct_full_after"] == round(100 * 4 / 7, 1)

    out = ad.read_h5ad(result["output_path"])
    lib = out.obs["library_id"]
    assert lib["c1"] == "L1"  # filled from NaN
    assert lib["c2"] == "L2"  # filled over placeholder
    assert lib["c3"] == "L9"  # source missing — left alone
    assert lib["c4"] == "L1"  # conflict — left alone, not overwritten
    assert pd.isna(lib["c5"])  # unmatched — still NaN
    assert lib["c6"] == ""  # unmatched — untouched
    assert pd.isna(lib["c7"])  # source had only a placeholder
    # c2 was the only "unknown"; the fill left the category unused
    assert "unknown" not in lib.cat.categories
    assert set(lib.cat.categories) == {"L1", "L2", "L9", ""}


def test_backfill_records_edit_log(target_source):
    target, source = target_source
    result = backfill_obs_from_source(target, source, columns=["library_id"])

    out = ad.read_h5ad(result["output_path"])
    entries = json.loads(out.uns["provenance"]["edit_history"])
    assert len(entries) == 1
    entry = entries[0]
    assert entry["operation"] == "backfill_obs_from_source"
    assert entry["details"]["backfill_source_file"] == "source.h5ad"
    assert entry["details"]["per_column"]["library_id"]["filled"] == 2
    assert entry["source_file"] == "target.h5ad"


def test_backfill_string_columns(tmp_path):
    target = _make_h5ad(tmp_path / "target.h5ad", TARGET_IDS, {"library_id": TARGET_LIB}, categorical=False)
    source = _make_h5ad(tmp_path / "source.h5ad", SOURCE_IDS, {"library_id": SOURCE_LIB}, categorical=False)

    result = backfill_obs_from_source(target, source, columns=["library_id"])

    assert "error" not in result
    stats = result["per_column"]["library_id"]
    assert stats["filled"] == 2
    assert stats["conflicts"] == 1
    assert stats["missing_after"] == 3

    out = ad.read_h5ad(result["output_path"])
    lib = out.obs["library_id"]
    assert lib["c1"] == "L1"
    assert lib["c2"] == "L2"
    assert lib["c4"] == "L1"
    assert lib["c7"] == ""  # source had only a placeholder — untouched


def test_backfill_multiple_columns_reported_separately(tmp_path):
    # run_id has nothing to fill (all set); library_id fills — per-column
    # stats must keep the two apart (the issue's library_preparation_batch case).
    target = _make_h5ad(
        tmp_path / "target.h5ad",
        TARGET_IDS,
        {"library_id": TARGET_LIB, "run_id": ["R1", "R2", "R3", "R4", "R5", "R6", "R7"]},
    )
    source = _make_h5ad(
        tmp_path / "source.h5ad",
        SOURCE_IDS,
        {"library_id": SOURCE_LIB, "run_id": ["R1", "R2", "R3", "R4", "R5", "R9"]},
    )

    result = backfill_obs_from_source(target, source, columns=["library_id", "run_id"])

    assert "error" not in result
    assert result["per_column"]["library_id"]["filled"] == 2
    assert result["per_column"]["run_id"]["filled"] == 0
    assert result["per_column"]["run_id"]["already_set"] == 5
    assert result["per_column"]["run_id"]["pct_full_after"] == 100.0
    assert result["total_filled"] == 2


def test_backfill_nothing_to_fill_writes_nothing(tmp_path):
    target = _make_h5ad(tmp_path / "target.h5ad", ["c1", "c2"], {"library_id": ["L1", "L2"]})
    source = _make_h5ad(tmp_path / "source.h5ad", ["c1", "c2"], {"library_id": ["L1", "L9"]})

    result = backfill_obs_from_source(target, source, columns=["library_id"])

    assert "error" in result
    assert "Nothing to backfill" in result["error"]
    # The stats still surface what was found — including the conflict
    assert result["per_column"]["library_id"]["already_set"] == 2
    assert result["per_column"]["library_id"]["conflicts"] == 1
    assert not list(tmp_path.glob("*-edit-*.h5ad"))


def test_backfill_zero_overlap_is_error(tmp_path):
    target = _make_h5ad(tmp_path / "target.h5ad", ["c1", "c2"], {"library_id": [None, None]})
    source = _make_h5ad(tmp_path / "source.h5ad", ["z1", "z2"], {"library_id": ["L1", "L2"]})

    result = backfill_obs_from_source(target, source, columns=["library_id"])

    assert "error" in result
    assert "0 shared" in result["error"]
    assert not list(tmp_path.glob("*-edit-*.h5ad"))


def test_backfill_partial_overlap_is_not_an_error(tmp_path):
    # Source cells absent from the target are skipped silently — the target
    # may simply have filtered them out.
    target = _make_h5ad(tmp_path / "target.h5ad", ["c1"], {"library_id": [None]})
    source = _make_h5ad(tmp_path / "source.h5ad", ["c1", "z1", "z2", "z3"], {"library_id": ["L1"] * 4})

    result = backfill_obs_from_source(target, source, columns=["library_id"])

    assert "error" not in result
    assert result["n_matched"] == 1
    assert result["per_column"]["library_id"]["filled"] == 1


def test_backfill_column_missing_from_source(target_source, tmp_path):
    target, _ = target_source
    source = _make_h5ad(tmp_path / "other-source.h5ad", SOURCE_IDS, {"other_col": SOURCE_LIB})

    result = backfill_obs_from_source(target, source, columns=["library_id"])

    assert "error" in result
    assert "Source file has no obs column 'library_id'" in result["error"]


def test_backfill_column_missing_from_target(target_source):
    target, source = target_source
    result = backfill_obs_from_source(target, source, columns=["nope"])
    assert "error" in result
    assert "Target file has no obs column 'nope'" in result["error"]


def test_backfill_numeric_column_refused(tmp_path):
    def make_numeric(path):
        obs = pd.DataFrame(
            {"n_counts": np.array([1.0, 2.0], dtype=np.float32)}, index=pd.Index(["c1", "c2"], name="cellID")
        )
        ad.AnnData(X=np.zeros((2, 2), dtype=np.float32), obs=obs).write_h5ad(path)
        return str(path)

    target = make_numeric(tmp_path / "target.h5ad")
    source = make_numeric(tmp_path / "source.h5ad")

    result = backfill_obs_from_source(target, source, columns=["n_counts"])

    assert "error" in result
    assert "not categorical or string" in result["error"]


def test_backfill_non_string_categorical_refused(tmp_path):
    """A numeric pandas Categorical is stored as a categories-group too; it
    must get the clear unsupported-column refusal, not a .strip() crash."""

    def make_numeric_categorical(path):
        obs = pd.DataFrame({"n_reads": pd.Categorical([1, 2])}, index=pd.Index(["c1", "c2"], name="cellID"))
        ad.AnnData(X=np.zeros((2, 2), dtype=np.float32), obs=obs).write_h5ad(path)
        return str(path)

    target = make_numeric_categorical(tmp_path / "target.h5ad")
    source = make_numeric_categorical(tmp_path / "source.h5ad")

    result = backfill_obs_from_source(target, source, columns=["n_reads"])

    assert "error" in result
    assert "categorical of non-string values" in result["error"]


def test_backfill_index_is_not_a_column(target_source):
    target, source = target_source
    result = backfill_obs_from_source(target, source, columns=["cellID"])
    assert "error" in result
    assert "join key" in result["error"]


def test_backfill_duplicate_source_ids_refused(target_source, tmp_path):
    target, _ = target_source
    with pytest.warns(UserWarning, match="Observation names are not unique"):
        source = _make_h5ad(tmp_path / "dupes.h5ad", ["c1", "c1", "c2"], {"library_id": ["L1", "L2", "L3"]})

    result = backfill_obs_from_source(target, source, columns=["library_id"])

    assert "error" in result
    assert "Source cells have duplicate IDs" in result["error"]


def test_backfill_argument_validation(target_source):
    target, source = target_source
    for bad_columns, expected in [
        ([], "non-empty list"),
        (["library_id", "library_id"], "duplicates"),
        (["obs/library_id"], "without '/'"),
        ([42], "not a valid obs column name"),
    ]:
        result = backfill_obs_from_source(target, source, columns=bad_columns)
        assert "error" in result
        assert expected in result["error"]


def test_backfill_same_file_refused(target_source):
    target, _ = target_source
    result = backfill_obs_from_source(target, target, columns=["library_id"])
    assert "error" in result
    assert "same file" in result["error"]


def test_backfill_missing_files(target_source):
    target, source = target_source
    assert "Target file not found" in backfill_obs_from_source("/nonexistent/t.h5ad", source, ["library_id"])["error"]
    assert "Source file not found" in backfill_obs_from_source(target, "/nonexistent/s.h5ad", ["library_id"])["error"]


def test_backfill_legacy_cap_target_refused(target_source, tmp_path):
    _, source = target_source
    target = _make_h5ad(
        tmp_path / "legacy.h5ad",
        TARGET_IDS,
        {"library_id": TARGET_LIB},
        uns={"cellannotation_metadata": {"some_set": {}}},
    )

    result = backfill_obs_from_source(target, source, columns=["library_id"])

    assert "error" in result
    assert "deprecated top-level CAP layout" in result["error"]


def test_backfill_runs_chain(tmp_path, monkeypatch):
    """Per-source runs chain: each resolves the newest snapshot and replaces
    the previous one, never touching the original."""
    # Distinct timestamps per run — two real runs can land in the same second,
    # which the same-second guard refuses.
    ticks = iter(["2026-08-19-00-00-01", "2026-08-19-00-00-02"])
    monkeypatch.setattr("hca_anndata_tools.write.generate_timestamp", lambda: next(ticks))
    target = _make_h5ad(tmp_path / "target.h5ad", ["c1", "c2"], {"library_id": [None, None]})
    source_a = _make_h5ad(tmp_path / "source-a.h5ad", ["c1"], {"library_id": ["L1"]})
    source_b = _make_h5ad(tmp_path / "source-b.h5ad", ["c2"], {"library_id": ["L2"]})

    first = backfill_obs_from_source(target, source_a, columns=["library_id"])
    assert "error" not in first
    # Passing the ORIGINAL path again: resolve_latest must pick up the snapshot
    second = backfill_obs_from_source(target, source_b, columns=["library_id"])
    assert "error" not in second

    assert (tmp_path / "target.h5ad").is_file()  # original never deleted
    snapshots = list(tmp_path.glob("target-edit-*.h5ad"))
    assert [str(p) for p in snapshots] == [second["output_path"]]  # previous snapshot cleaned up

    out = ad.read_h5ad(second["output_path"])
    assert list(out.obs["library_id"]) == ["L1", "L2"]
    entries = json.loads(out.uns["provenance"]["edit_history"])
    assert [e["operation"] for e in entries] == ["backfill_obs_from_source"] * 2
    assert second["per_column"]["library_id"]["pct_full_after"] == 100.0


def test_backfill_same_second_collision_resolves_after_waiting(target_source, tmp_path, pin_snapshot_names):
    """The common case since #597: waited out, not refused."""
    target, source = target_source
    fresh = str(Path(target).parent / "target-edit-2026-08-24-00-00-01.h5ad")
    pin_snapshot_names(str(target), fresh)

    result = backfill_obs_from_source(target, source, columns=["library_id"])

    assert "error" not in result
    assert result["output_path"] == fresh


def test_backfill_same_second_snapshot_refused(target_source, pin_snapshot_names):
    """A collision surviving the wait is refused, target untouched."""
    pin_snapshot_names()
    target, source = target_source

    result = backfill_obs_from_source(target, source, columns=["library_id"])

    assert "error" in result
    assert "already exists" in result["error"]
    assert ad.read_h5ad(target).n_obs == 7  # target untouched


def test_backfill_extends_categories_without_disturbing_existing(tmp_path):
    """New fill values extend the categories; existing values keep their
    meaning (read-back equality is the check, not code equality)."""
    target = _make_h5ad(tmp_path / "target.h5ad", ["c1", "c2", "c3"], {"library_id": ["unknown", "L_existing", None]})
    source = _make_h5ad(tmp_path / "source.h5ad", ["c1", "c3"], {"library_id": ["L_new_1", "L_new_2"]})

    result = backfill_obs_from_source(target, source, columns=["library_id"])

    assert "error" not in result
    out = ad.read_h5ad(result["output_path"])
    assert list(out.obs["library_id"]) == ["L_new_1", "L_existing", "L_new_2"]
    assert set(out.obs["library_id"].cat.categories) == {"L_existing", "L_new_1", "L_new_2"}


def test_backfill_keeps_preexisting_unused_categories(tmp_path):
    """The declared category vocabulary is set data: only categories the fill
    itself left unused (the replaced placeholder) are dropped."""
    obs = pd.DataFrame(
        {"library_id": pd.Categorical(["unknown", None], categories=["unknown", "L_unused"])},
        index=pd.Index(["c1", "c2"], name="cellID"),
    )
    ad.AnnData(X=np.zeros((2, 2), dtype=np.float32), obs=obs).write_h5ad(tmp_path / "target.h5ad")
    source = _make_h5ad(tmp_path / "source.h5ad", ["c1", "c2"], {"library_id": ["L1", "L2"]})

    result = backfill_obs_from_source(str(tmp_path / "target.h5ad"), source, columns=["library_id"])

    assert "error" not in result
    out = ad.read_h5ad(result["output_path"])
    assert list(out.obs["library_id"]) == ["L1", "L2"]
    # "unknown" became unused through the fill — dropped; "L_unused" was
    # already unused before the fill — kept.
    assert set(out.obs["library_id"].cat.categories) == {"L_unused", "L1", "L2"}


def test_backfill_refuses_new_categories_on_ordered_categorical(tmp_path):
    """Appending to an ordered vocabulary would corrupt its ordering; a fill
    that stays inside the existing vocabulary is fine."""
    obs = pd.DataFrame(
        {"stage": pd.Categorical([None, "E10", "E12"], categories=["E10", "E12"], ordered=True)},
        index=pd.Index(["c1", "c2", "c3"], name="cellID"),
    )
    ad.AnnData(X=np.zeros((3, 2), dtype=np.float32), obs=obs).write_h5ad(tmp_path / "target.h5ad")
    target = str(tmp_path / "target.h5ad")

    new_cat_source = _make_h5ad(tmp_path / "source-new.h5ad", ["c1"], {"stage": ["E09"]})
    result = backfill_obs_from_source(target, new_cat_source, columns=["stage"])
    assert "error" in result
    assert "ordered categorical" in result["error"]
    assert not list(tmp_path.glob("*-edit-*.h5ad"))

    in_vocab_source = _make_h5ad(tmp_path / "source-ok.h5ad", ["c1"], {"stage": ["E10"]})
    result = backfill_obs_from_source(target, in_vocab_source, columns=["stage"])
    assert "error" not in result
    out = ad.read_h5ad(result["output_path"])
    assert out.obs["stage"]["c1"] == "E10"
    assert out.obs["stage"].cat.ordered
    assert list(out.obs["stage"].cat.categories) == ["E10", "E12"]


def test_codes_dtype_upcasts_when_categories_outgrow_int8():
    assert _codes_dtype(100, np.dtype(np.int8)) == np.dtype(np.int8)
    assert _codes_dtype(200, np.dtype(np.int8)) == np.dtype(np.int16)
    assert _codes_dtype(200, np.dtype(np.int32)) == np.dtype(np.int32)
    assert _codes_dtype(2**20, np.dtype(np.int16)) == np.dtype(np.int32)


def test_backfill_refuses_a_masked_index_rather_than_joining_na_to_na(tmp_path):
    """A masked join key must not silently match another file's masked key.

    pandas joins pd.NA to pd.NA, so without this refusal a masked cell matches
    the *other* file's masked cell and is counted as a legitimate match — no
    error, no warning, a wrong number in the report. check_duplicate_ids
    catches it only for two or more masked rows; one sails through
    (hca-validation-tools#637).
    """
    target = create_sample_h5ad(tmp_path / "target.h5ad")
    source = create_sample_h5ad(tmp_path / "source.h5ad")
    make_nullable_index(source, masked=1)

    result = backfill_obs_from_source(str(target), str(source), columns=["cell_type"])

    assert "error" in result
    assert "missing value" in result["error"]


def test_backfill_reads_an_unmasked_nullable_index(target_source, tmp_path):
    """A nullable index the tool only reads is no obstacle.

    backfill transplants columns into a copy; it never rewrites either index,
    so the encoding that blocks the write tools (hca-validation-tools#641) does
    not block this one. Asserting the join, not just the absence of an error —
    an index read as bytes compares unequal to its str counterparts and would
    report 0 matched cells while claiming success.
    """
    target, source = target_source
    make_nullable_index(source)

    result = backfill_obs_from_source(target, source, columns=["library_id"])

    assert "error" not in result, result.get("error")
    assert result["n_matched"] == 5
    assert result["total_filled"] == 2
