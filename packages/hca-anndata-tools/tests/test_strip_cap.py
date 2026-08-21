"""Tests for strip_cap_annotations."""

import json

import anndata as ad
import numpy as np
import pandas as pd

from hca_anndata_tools.drop import drop_obs_columns
from hca_anndata_tools.strip_cap import strip_cap_annotations

_CAP_COLUMNS = ["Prelim annotation--cell_fullname", "Prelim annotation--cell_ontology_term_id"]


_IMPORT_ENTRY = {
    "timestamp": "2026-05-27T00:00:00Z",
    "tool": "hca-anndata-tools",
    "tool_version": "0.0.1",
    "operation": "import_cap_annotations",
    "description": "test import",
}


def _make_cap_file(path, uns_layout="legacy", cap_columns=True, imported=True, prior_log_entry=None, extra_uns=None):
    """Write a small HCA-layout h5ad carrying CAP material.

    ``uns_layout``: 'legacy' (top-level keys), 'nested' (uns['cap_metadata']),
    'mixed' (both), or 'none'. ``cap_columns`` controls the ``--`` obs
    columns independently of the uns keys. ``imported`` stamps the
    import_cap_annotations edit-log entry the provenance gate requires;
    ``imported=False`` models a raw CAP export (no edit history).
    """
    if prior_log_entry is None and imported and uns_layout != "none":
        prior_log_entry = _IMPORT_ENTRY
    columns = {
        "sample_id": pd.Categorical(["s1", "s2", "s3"]),
        "junk_col": pd.Categorical(["a", "b", "a"]),
    }
    if cap_columns:
        for col in _CAP_COLUMNS:
            columns[col] = pd.Categorical(["T cell", "B cell", "T cell"])
    obs = pd.DataFrame(columns, index=pd.Index(["c1", "c2", "c3"], name="cellID"))
    adata = ad.AnnData(X=np.zeros((3, 2), dtype=np.float32), obs=obs)
    adata.uns["title"] = "Test file"
    if uns_layout != "none":
        cap_block = {
            "cellannotation_schema_version": "1.0.0",
            "cellannotation_metadata": {"Prelim annotation": {}},
        }
        if uns_layout in ("legacy", "mixed"):
            adata.uns.update(cap_block)
        if uns_layout in ("nested", "mixed"):
            adata.uns["cap_metadata"] = dict(cap_block)
    if extra_uns:
        adata.uns.update(extra_uns)
    if prior_log_entry is not None:
        adata.uns["provenance"] = {"edit_history": json.dumps([prior_log_entry])}
    adata.write_h5ad(path)
    return str(path)


def test_strip_legacy_layout(tmp_path):
    path = _make_cap_file(tmp_path / "legacy.h5ad", uns_layout="legacy")

    result = strip_cap_annotations(path)

    assert "error" not in result
    assert result["uns_keys_removed"] == ["cellannotation_metadata", "cellannotation_schema_version"]
    assert result["obs_columns_removed"] == _CAP_COLUMNS

    out = ad.read_h5ad(result["output_path"])
    assert set(out.obs.columns) == {"sample_id", "junk_col"}  # everything else intact
    assert "cellannotation_metadata" not in out.uns
    assert "cellannotation_schema_version" not in out.uns
    assert out.uns["title"] == "Test file"
    entries = json.loads(out.uns["provenance"]["edit_history"])
    assert [e["operation"] for e in entries] == ["import_cap_annotations", "strip_cap_annotations"]
    assert entries[-1]["details"]["obs_columns_removed"] == _CAP_COLUMNS


def test_strip_nested_layout(tmp_path):
    path = _make_cap_file(tmp_path / "nested.h5ad", uns_layout="nested")

    result = strip_cap_annotations(path)

    assert "error" not in result
    assert result["uns_keys_removed"] == ["cap_metadata"]
    out = ad.read_h5ad(result["output_path"])
    assert "cap_metadata" not in out.uns


def test_strip_mixed_layout(tmp_path):
    path = _make_cap_file(tmp_path / "mixed.h5ad", uns_layout="mixed")

    result = strip_cap_annotations(path)

    assert "error" not in result
    assert result["uns_keys_removed"] == [
        "cellannotation_metadata",
        "cellannotation_schema_version",
        "cap_metadata",
    ]


def test_strip_columns_only(tmp_path):
    """A file with '--' columns but no CAP uns keys still strips."""
    path = _make_cap_file(tmp_path / "colsonly.h5ad", uns_layout="none", cap_columns=True)

    result = strip_cap_annotations(path)

    assert "error" not in result
    assert result["uns_keys_removed"] == []
    assert result["obs_columns_removed"] == _CAP_COLUMNS


def test_strip_warns_on_unknown_cap_suffix(tmp_path):
    """Every '--' column is CAP's and is removed, but a suffix outside the
    known vocabulary is surfaced — the signal that CAP grew a schema field
    cap.py should learn."""
    path = _make_cap_file(tmp_path / "newsuffix.h5ad", uns_layout="legacy")
    adata = ad.read_h5ad(path)
    adata.obs["Prelim annotation--brand_new_field"] = pd.Categorical(["x", "y", "x"])
    adata.write_h5ad(path)

    result = strip_cap_annotations(path)

    assert "error" not in result
    assert "Prelim annotation--brand_new_field" in result["obs_columns_removed"]  # still removed
    assert result["unknown_cap_suffix_columns"] == ["Prelim annotation--brand_new_field"]
    assert "add them to the suffix lists" in result["warning"]
    assert "Prelim annotation--brand_new_field" not in ad.read_h5ad(result["output_path"]).obs.columns


def test_strip_no_warning_for_known_suffixes(tmp_path):
    path = _make_cap_file(tmp_path / "known.h5ad", uns_layout="legacy")
    result = strip_cap_annotations(path)
    assert "error" not in result
    assert "warning" not in result
    assert "unknown_cap_suffix_columns" not in result


def test_strip_removes_orphaned_color_palettes(tmp_path):
    """A removed categorical column's scanpy palette must go with it — an
    orphaned uns['<col>_colors'] fails the schema validator."""
    palette_key = _CAP_COLUMNS[0] + "_colors"
    path = _make_cap_file(
        tmp_path / "palette.h5ad",
        uns_layout="legacy",
        extra_uns={palette_key: np.array(["#1f77b4", "#ff7f0e"]), "junk_col_colors": np.array(["#aaaaaa"])},
    )

    result = strip_cap_annotations(path)

    assert "error" not in result
    assert palette_key in result["uns_keys_removed"]
    out = ad.read_h5ad(result["output_path"])
    assert palette_key not in out.uns
    assert "junk_col_colors" in out.uns  # a kept column keeps its palette


def test_strip_removes_legacy_cap_provenance(tmp_path):
    """The pre-#452 copy_cap eras also wrote uns['provenance']['cap'] and
    top-level cap_* keys (the gut-v1 objects carry the former); 'remove ALL
    CAP material' must cover them — while edit_history survives untouched."""
    prior = {
        "timestamp": "2026-05-27T00:00:00Z",
        "tool": "hca-anndata-tools",
        "tool_version": "0.0.1",
        "operation": "import_cap_annotations",
        "description": "old import",
    }
    path = _make_cap_file(
        tmp_path / "provenance.h5ad",
        uns_layout="legacy",
        prior_log_entry=prior,
        extra_uns={"cap_dataset_url": "https://celltype.info/x", "cap_authors_list": "A, B"},
    )
    adata = ad.read_h5ad(path)
    adata.uns["provenance"]["cap"] = {"cap_publication_title": "Old Pub", "authors_list": "A, B"}
    adata.write_h5ad(path)

    result = strip_cap_annotations(path)

    assert "error" not in result
    assert "provenance/cap" in result["uns_keys_removed"]
    assert "cap_dataset_url" in result["uns_keys_removed"]
    assert "cap_authors_list" in result["uns_keys_removed"]  # collision-safe renamed era
    out = ad.read_h5ad(result["output_path"])
    assert "cap" not in out.uns["provenance"]
    assert "cap_dataset_url" not in out.uns
    assert "cap_authors_list" not in out.uns
    entries = json.loads(out.uns["provenance"]["edit_history"])
    assert [e["operation"] for e in entries] == ["import_cap_annotations", "strip_cap_annotations"]


def test_strip_removes_already_orphaned_cap_palettes(tmp_path):
    """The old overwrite era deleted CAP columns but left their palettes;
    a palette whose column is already gone must still be stripped."""
    path = _make_cap_file(
        tmp_path / "orphan.h5ad",
        uns_layout="legacy",
        extra_uns={"gone_set--cell_fullname_colors": np.array(["#ff0000"])},
    )

    result = strip_cap_annotations(path)

    assert "error" not in result
    assert "gone_set--cell_fullname_colors" in result["uns_keys_removed"]
    assert "gone_set--cell_fullname_colors" not in ad.read_h5ad(result["output_path"]).uns


def test_strip_preserves_existing_edit_history(tmp_path):
    prior = {
        "timestamp": "2026-05-27T00:00:00Z",
        "tool": "hca-anndata-tools",
        "tool_version": "0.0.1",
        "operation": "import_cap_annotations",
        "description": "old import",
    }
    path = _make_cap_file(tmp_path / "history.h5ad", uns_layout="legacy", prior_log_entry=prior)

    result = strip_cap_annotations(path)

    assert "error" not in result
    entries = json.loads(ad.read_h5ad(result["output_path"]).uns["provenance"]["edit_history"])
    assert [e["operation"] for e in entries] == ["import_cap_annotations", "strip_cap_annotations"]


def test_strip_unblocks_the_mutating_toolkit(tmp_path, monkeypatch):
    """The legacy layout locks out sibling tools; stripping clears the refusal."""
    # Distinct timestamps for the two writes — drop.py lacks the same-second
    # guard (#598/#600), so back-to-back edits in one second collide.
    ticks = iter(["2026-08-21-00-00-01", "2026-08-21-00-00-02"])
    monkeypatch.setattr("hca_anndata_tools.write.generate_timestamp", lambda: next(ticks))
    path = _make_cap_file(tmp_path / "locked.h5ad", uns_layout="legacy")

    refused = drop_obs_columns(path, columns=["junk_col"])
    assert "error" in refused
    assert "deprecated top-level CAP layout" in refused["error"]

    stripped = strip_cap_annotations(path)
    assert "error" not in stripped

    accepted = drop_obs_columns(stripped["output_path"], columns=["junk_col"])
    assert "error" not in accepted
    assert "junk_col" not in ad.read_h5ad(accepted["output_path"]).obs.columns


def test_strip_nothing_to_strip_is_an_error(tmp_path):
    path = _make_cap_file(tmp_path / "clean.h5ad", uns_layout="none", cap_columns=False)

    result = strip_cap_annotations(path)

    assert "error" in result
    assert "Nothing to strip" in result["error"]
    assert not list(tmp_path.glob("*-edit-*.h5ad"))


def test_strip_refuses_cap_export_without_our_import(tmp_path):
    """A raw legacy CAP export carries the same uns keys but no edit history —
    the provenance gate keeps it from being mutilated (the CellxGENE gate
    can't: legacy exports declare no schema_version)."""
    path = _make_cap_file(tmp_path / "export.h5ad", uns_layout="legacy", imported=False)

    result = strip_cap_annotations(path)

    assert "error" in result
    assert "import_cap_annotations" in result["error"]
    assert not list(tmp_path.glob("*-edit-*.h5ad"))


def test_strip_columns_only_needs_no_import_entry(tmp_path):
    """The provenance gate covers CAP uns metadata only: '--' columns without
    the uns block (e.g. convert-era files) strip without an import entry."""
    path = _make_cap_file(tmp_path / "cols.h5ad", uns_layout="none", cap_columns=True, imported=False)

    result = strip_cap_annotations(path)

    assert "error" not in result
    assert result["obs_columns_removed"] == _CAP_COLUMNS


def test_strip_refuses_cellxgene_layout(sample_h5ad):
    result = strip_cap_annotations(str(sample_h5ad))
    assert "error" in result
    assert "CellxGENE" in result["error"]


def test_strip_same_second_snapshot_refused(tmp_path, monkeypatch):
    monkeypatch.setattr("hca_anndata_tools.strip_cap.generate_output_path", lambda p: p)
    path = _make_cap_file(tmp_path / "guard.h5ad", uns_layout="legacy")

    result = strip_cap_annotations(path)

    assert "error" in result
    assert "already exists" in result["error"]
    assert ad.read_h5ad(path).uns["cellannotation_schema_version"] == "1.0.0"  # untouched


def test_strip_missing_file():
    result = strip_cap_annotations("/nonexistent/file.h5ad")
    assert "error" in result
    assert "File not found" in result["error"]
