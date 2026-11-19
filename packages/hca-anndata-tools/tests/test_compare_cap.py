"""Tests for compare_cap_export: the copy's pre-write checks, reported without writing (#749)."""

from collections.abc import Callable
from pathlib import Path

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pytest

from hca_anndata_tools.compare_cap import compare_cap_export
from hca_anndata_tools.copy_cap import copy_cap_annotations

from .test_copy_cap import CELL_IDS, _make_cap_source, _make_hca_target

# Real Ensembl IDs, so the GENCODE lookup can tell a rename from a typo.
ENSEMBL = ["ENSG00000131095", "ENSG00000204472", "ENSG00000167281", "ENSG00000173947"]
SYMBOLS = ["GFAP", "AIF1", "RBFOX3", "PIFO"]  # PIFO is the old name for CIMAP3


def _edit(path: Path, change: Callable[[ad.AnnData], None]) -> Path:
    adata = ad.read_h5ad(path)
    change(adata)
    adata.write_h5ad(path)
    return path


def _pair(tmp_path: Path, source_ids=CELL_IDS, target_ids=CELL_IDS, **target_kw) -> tuple[Path, Path]:
    tmp_path.mkdir(exist_ok=True)
    return (
        _make_cap_source(tmp_path / "cap.h5ad", list(source_ids)),
        _make_hca_target(tmp_path / "target.h5ad", list(target_ids), **target_kw),
    )


# --- one builder per pre-write refusal of copy_cap_annotations, and the passing pairs ---


def _matching(tmp_path, _downgrade):
    return _pair(tmp_path)


def _reordered(tmp_path, _downgrade):
    return _pair(tmp_path, target_ids=list(reversed(CELL_IDS)))


def _same_file(tmp_path, _downgrade):
    source, _ = _pair(tmp_path)
    return source, source


def _legacy_source(tmp_path, downgrade):
    source, target = _pair(tmp_path)
    return downgrade(source), target


def _mixed_source(tmp_path, _downgrade):
    source, target = _pair(tmp_path)
    return _edit(source, lambda a: a.uns.__setitem__("cellannotation_schema_version", "1.0.2")), target


def _malformed_source(tmp_path, _downgrade):
    source, target = _pair(tmp_path)
    return _edit(source, lambda a: a.uns.__setitem__("cap_metadata", "not-a-dict")), target


def _no_cap_source(tmp_path, _downgrade):
    return _make_hca_target(tmp_path / "no-cap.h5ad", CELL_IDS), _make_hca_target(tmp_path / "t.h5ad", CELL_IDS)


def _no_schema_version(tmp_path, _downgrade):
    source, target = _pair(tmp_path)
    return _edit(source, lambda a: a.uns["cap_metadata"].pop("cellannotation_schema_version")), target


def _metadata_not_a_dict(tmp_path, _downgrade):
    source, target = _pair(tmp_path)
    return _edit(source, lambda a: a.uns["cap_metadata"].__setitem__("cellannotation_metadata", "none")), target


def _non_categorical_column(tmp_path, _downgrade):
    source, target = _pair(tmp_path)
    with h5py.File(source, "a") as f:
        del f["obs"]["author_cell_type--rationale"]
        f["obs"].create_dataset("author_cell_type--rationale", data=np.array(["morphology"] * len(CELL_IDS), dtype="S"))
    return source, target


def _duplicate_target_genes(tmp_path, _downgrade):
    return _pair(tmp_path, var_ids=["GENE0", "GENE1", "GENE1", "GENE2", "GENE3"])


def _legacy_target(tmp_path, _downgrade):
    def legacy(adata):
        adata.uns["cellannotation_schema_version"] = "1.0.2"
        adata.uns["cellannotation_metadata"] = {"author_cell_type": {"description": "x"}}

    source, target = _pair(tmp_path)
    return source, _edit(target, legacy)


def _target_with_cap(tmp_path, _downgrade):
    source, target = _pair(tmp_path)
    return source, _edit(target, lambda a: a.obs.__setitem__("existing--cell_ontology_term_id", "CL:0000000"))


def _target_with_orphan_palette(tmp_path, _downgrade):
    source, target = _pair(tmp_path)
    return source, _edit(target, lambda a: a.uns.__setitem__("gone--cell_fullname_colors", np.array(["#ff0000"])))


def _disjoint_cells(tmp_path, _downgrade):
    return _pair(tmp_path, target_ids=[f"other_{i}" for i in range(10)])


def _cap_cells_missing_from_target(tmp_path, _downgrade):
    return _pair(tmp_path, target_ids=CELL_IDS[:9])


def _ten_percent_missing(tmp_path, _downgrade):
    return _pair(tmp_path, target_ids=[f"cell_{i}" for i in range(9)] + ["target_only"])


def _broken_edit_log(tmp_path, _downgrade):
    source, target = _pair(tmp_path)
    return source, _edit(target, lambda a: a.uns.__setitem__("provenance", {"edit_history": "not valid json {{"}))


def _rootless_snapshot(tmp_path, _downgrade):
    source, target = _pair(tmp_path)
    return source, target.rename(target.with_name("target-edit-2026-03-27-13-54-26.h5ad"))


PAIRS = [
    (_matching, "yes", None),
    (_reordered, "yes", None),
    (_same_file, "no", "distinct_files"),
    (_legacy_source, "no", "source_layout"),
    (_mixed_source, "no", "source_layout"),
    (_malformed_source, "no", "source_cap_block"),
    (_no_cap_source, "no", "source_cap_block"),
    (_no_schema_version, "no", "source_schema_version"),
    (_metadata_not_a_dict, "no", "source_annotation_sets"),
    (_non_categorical_column, "no", "source_columns_categorical"),
    (_duplicate_target_genes, "no", "target_gene_ids_unique"),
    (_legacy_target, "no", "target_layout"),
    (_target_with_cap, "with_overwrite", "target_has_no_cap"),
    (_target_with_orphan_palette, "with_overwrite", "target_has_no_cap"),
    (_disjoint_cells, "no", "cell_overlap"),
    (_ten_percent_missing, "no", "cell_overlap"),
    (_cap_cells_missing_from_target, "no", "cell_overlap"),
    (_broken_edit_log, "no", "target_edit_log"),
    (_rootless_snapshot, "no", "target_lineage"),
]


@pytest.mark.filterwarnings("ignore:Variable names are not unique:UserWarning")
@pytest.mark.filterwarnings("ignore::anndata._warnings.OldFormatWarning")
@pytest.mark.parametrize(("build", "accepts", "refused_by"), PAIRS, ids=[b.__name__.strip("_") for b, *_ in PAIRS])
def test_the_verdict_is_what_the_copy_does(tmp_path, downgrade_cap_to_legacy, build, accepts, refused_by):
    source, target = build(tmp_path, downgrade_cap_to_legacy)

    verdict = compare_cap_export(str(source), str(target))["verdict"]
    copied = copy_cap_annotations(str(source), str(target))

    assert (verdict["copy_would_accept"], verdict["refused_by"]) == (accepts, refused_by)
    if accepts == "yes":
        assert "error" not in copied
    else:
        # with_overwrite adds a note that the strip makes checks of its own.
        assert verdict["message"].startswith(copied["error"])
    if accepts == "with_overwrite":
        assert "error" not in copy_cap_annotations(str(source), str(target), overwrite=True)


def test_reports_every_section_and_writes_nothing(tmp_path):
    source, target = _pair(tmp_path)

    result = compare_cap_export(str(source), str(target))

    assert set(result) == {"source", "target", "cells", "genes", "marker_genes", "cap", "checks", "verdict"}
    assert {c["status"] for c in result["checks"]} == {"pass"}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["cap.h5ad", "target.h5ad"]


def test_reads_no_matrix(tmp_path):
    source, target = _pair(tmp_path)
    before = compare_cap_export(str(source), str(target))
    for path in (source, target):
        with h5py.File(path, "a") as f:
            del f["X"]

    assert compare_cap_export(str(source), str(target)) == before


def test_a_failed_check_leaves_the_checks_that_depend_on_it_not_run(tmp_path):
    source, target = _no_cap_source(tmp_path, None)

    checks = {c["name"]: c for c in compare_cap_export(str(source), str(target))["checks"]}

    assert checks["source_cap_block"]["status"] == "fail"
    assert checks["source_annotation_sets"]["status"] == "not_run"
    assert checks["source_columns_present"]["status"] == "not_run"
    # The cell check does not depend on the CAP block, so it still runs.
    assert checks["cell_overlap"]["status"] == "pass"


def test_mismatched_cells_are_counted(tmp_path):
    result = compare_cap_export(*map(str, _disjoint_cells(tmp_path, None)))

    assert result["cells"]["n_matched"] == 0
    assert result["cells"]["missing_from_hca"] == {"n": 10, "pct": 100.0}
    assert result["cells"]["within_copy_limit"] is False


def test_genes_are_reported_both_ways_without_a_verdict(tmp_path):
    source = _make_cap_source(tmp_path / "cap.h5ad", CELL_IDS, var_ids=["GENE0", "GENE1", "CAP_ONLY"])
    target = _make_hca_target(tmp_path / "target.h5ad", CELL_IDS, var_ids=["GENE0", "GENE1", "HCA_ONLY", "HCA_TWO"])

    result = compare_cap_export(str(source), str(target))
    genes = result["genes"]

    assert (genes["n_matched"], genes["missing_from_hca"]["n"], genes["missing_from_cap"]["n"]) == (2, 1, 2)
    assert genes["missing_from_hca_examples"] == ["CAP_ONLY"]
    assert genes["missing_from_cap_examples"] == ["HCA_ONLY", "HCA_TWO"]
    assert result["verdict"]["copy_would_accept"] == "yes"


def test_gene_examples_stop_at_25(tmp_path):
    source = _make_cap_source(tmp_path / "cap.h5ad", CELL_IDS, var_ids=[f"G{i:03}" for i in range(40)])
    target = _make_hca_target(tmp_path / "target.h5ad", CELL_IDS, var_ids=["OTHER"])

    genes = compare_cap_export(str(source), str(target))["genes"]

    assert genes["missing_from_hca"]["n"] == 40
    assert genes["missing_from_hca_examples"] == [f"G{i:03}" for i in range(25)]


@pytest.fixture
def marker_pair(tmp_path) -> tuple[Path, Path]:
    """An export citing found markers, a rename (CIMAP3, PIFO in var), a typo (SCL25A5) and an unmeasured FOXP3."""
    evidence = (["GFAP,AIF1", "CIMAP3", "SCL25A5", "FOXP3"] * 3)[: len(CELL_IDS)]
    source = _edit(
        _make_cap_source(tmp_path / "cap.h5ad", CELL_IDS, var_ids=ENSEMBL),
        lambda a: a.obs.__setitem__("author_cell_type--marker_gene_evidence", pd.Categorical(evidence)),
    )
    target = _edit(
        _make_hca_target(tmp_path / "target.h5ad", CELL_IDS, var_ids=ENSEMBL),
        lambda a: a.var.__setitem__("feature_name", pd.Categorical(SYMBOLS)),
    )
    return source, target


def test_marker_genes_missing_from_the_target_are_classified(marker_pair):
    markers = compare_cap_export(*map(str, marker_pair))["marker_genes"]

    assert markers["found_in_var"] == 2
    assert [(r["marker_gene"], r["var_name"]) for r in markers["known_renames"]] == [("CIMAP3", "PIFO")]
    assert [t["marker_gene"] for t in markers["not_in_gencode"]] == ["SCL25A5"]
    unmeasured = [(m["marker_gene"], m["ensembl_ids"]) for m in markers["missing_from_var"]]
    assert unmeasured == [("FOXP3", ["ENSG00000049768"])]
    assert markers["details"]["author_cell_type"]["missing_from_var"] == markers["missing_from_var"]


def _without_ensembl_ids(markers: dict) -> dict:
    def drop(entries):
        return [{k: v for k, v in e.items() if k != "ensembl_ids"} for e in entries]

    details = {s: {**d, "missing_from_var": drop(d["missing_from_var"])} for s, d in markers["details"].items()}
    return {**markers, "missing_from_var": drop(markers["missing_from_var"]), "details": details}


def test_marker_genes_match_what_the_copy_reports_apart_from_ensembl_ids(marker_pair):
    source, target = map(str, marker_pair)

    compared = compare_cap_export(source, target)["marker_genes"]
    copied = copy_cap_annotations(source, target)["marker_gene_validation"]

    assert compared["missing_from_var"]
    assert "ensembl_ids" not in copied["missing_from_var"][0]
    assert _without_ensembl_ids(compared) == copied


def test_cap_layout_of_each_file(tmp_path, downgrade_cap_to_legacy):
    nested = compare_cap_export(*map(str, _matching(tmp_path / "a", None)))["cap"]
    mixed = compare_cap_export(*map(str, _mixed_source(tmp_path / "b", None)))["cap"]
    legacy = compare_cap_export(*map(str, _legacy_source(tmp_path / "c", downgrade_cap_to_legacy)))["cap"]

    assert (nested["export"]["layout"], nested["target"]["layout"]) == ("nested", "absent")
    assert nested["export"]["fields"]["cap_dataset_url"] == "https://celltype.info/test"
    assert nested["target"]["fields"] is None
    malformed = compare_cap_export(*map(str, _malformed_source(tmp_path / "d", None)))["cap"]
    assert (mixed["export"]["layout"], legacy["export"]["layout"]) == ("mixed", "legacy")
    assert legacy["export"]["fields"]["cap_dataset_url"] == "https://celltype.info/test"
    assert (malformed["export"]["layout"], malformed["export"]["fields"]) == ("malformed", None)


def test_marker_genes_need_a_human_target(tmp_path):
    source, target = _pair(tmp_path)
    _edit(target, lambda a: a.obs.__setitem__("organism_ontology_term_id", pd.Categorical(["NCBITaxon:10090"] * 10)))

    result = compare_cap_export(str(source), str(target))

    assert result["marker_genes"] == {
        "error": "Only human (NCBITaxon:9606) is supported, found non-human: ['NCBITaxon:10090']"
    }
    assert result["verdict"]["copy_would_accept"] == "yes"


def test_an_unexpected_failure_carries_its_traceback(monkeypatch, tmp_path):
    def boom(*_args, **_kwargs):
        raise ValueError("synthetic failure")

    monkeypatch.setattr("hca_anndata_tools.compare_cap.read_column_order", boom)

    result = compare_cap_export(*map(str, _pair(tmp_path)))

    assert result["error"] == "ValueError: synthetic failure"
    assert "boom" in result["traceback"]


def test_with_overwrite_says_the_strip_has_checks_of_its_own(tmp_path):
    verdict = compare_cap_export(*map(str, _target_with_cap(tmp_path, None)))["verdict"]

    assert verdict["copy_would_accept"] == "with_overwrite"
    assert "strip_cap_annotations, which makes checks of its own" in verdict["message"]
