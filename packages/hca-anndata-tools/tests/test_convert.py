"""Tests for convert_cellxgene_to_hca."""

import json
import os
import re

import anndata as ad

from hca_anndata_tools.convert import _slugify, convert_cellxgene_to_hca
from hca_anndata_tools.write import EDIT_LOG_KEY


# --- _slugify ---


def test_slugify_basic():
    assert _slugify("Human Retina - RGC Subset") == "human-retina-rgc-subset"


def test_slugify_special_chars():
    assert _slugify("snRNA-seq (v3) of Human Retina") == "snrna-seq-v3-of-human-retina"


def test_slugify_truncates():
    long_title = "A" * 200
    result = _slugify(long_title, max_length=80)
    assert len(result) <= 80


def test_slugify_empty():
    assert _slugify("") == "untitled"


# --- convert_cellxgene_to_hca ---


def test_convert_basic(cellxgene_h5ad):
    result = convert_cellxgene_to_hca(str(cellxgene_h5ad))
    assert "error" not in result
    assert "output_path" in result
    assert "conversions" in result


def test_convert_cellxgene_source_preserved(cellxgene_h5ad):
    result = convert_cellxgene_to_hca(str(cellxgene_h5ad))
    written = ad.read_h5ad(result["output_path"])

    assert "provenance" in written.uns
    assert "cellxgene" in written.uns["provenance"]
    source = written.uns["provenance"]["cellxgene"]
    assert source["schema_version"] == "7.1.0"
    assert "schema_reference" in source
    assert "citation" in source


def test_convert_reserved_keys_removed_from_uns(cellxgene_h5ad):
    result = convert_cellxgene_to_hca(str(cellxgene_h5ad))
    written = ad.read_h5ad(result["output_path"])

    assert "schema_version" not in written.uns
    assert "schema_reference" not in written.uns
    assert "citation" not in written.uns


def test_convert_organism_broadcast_to_obs(cellxgene_h5ad):
    result = convert_cellxgene_to_hca(str(cellxgene_h5ad))
    written = ad.read_h5ad(result["output_path"])

    assert "organism_ontology_term_id" in written.obs.columns
    assert "organism" in written.obs.columns
    assert (written.obs["organism_ontology_term_id"] == "NCBITaxon:9606").all()
    assert (written.obs["organism"] == "Homo sapiens").all()


def test_convert_organism_removed_from_uns(cellxgene_h5ad):
    result = convert_cellxgene_to_hca(str(cellxgene_h5ad))
    written = ad.read_h5ad(result["output_path"])

    assert "organism_ontology_term_id" not in written.uns
    assert "organism" not in written.uns


def test_convert_label_columns_preserved(cellxgene_h5ad):
    result = convert_cellxgene_to_hca(str(cellxgene_h5ad))
    written = ad.read_h5ad(result["output_path"])

    # obs labels
    assert "cell_type" in written.obs.columns
    assert "assay" in written.obs.columns
    assert "tissue" in written.obs.columns
    assert "observation_joinid" in written.obs.columns

    # var labels
    assert "feature_name" in written.var.columns
    assert "feature_reference" in written.var.columns


def test_convert_output_named_from_title(cellxgene_h5ad):
    result = convert_cellxgene_to_hca(str(cellxgene_h5ad))
    basename = os.path.basename(result["output_path"])

    assert basename.startswith("snrna-seq-of-human-retina-test-subset-edit-")
    assert re.search(r"\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}\.h5ad$", basename)


def test_convert_edit_log(cellxgene_h5ad):
    result = convert_cellxgene_to_hca(str(cellxgene_h5ad))
    written = ad.read_h5ad(result["output_path"])

    log = json.loads(written.uns[EDIT_LOG_KEY])
    assert len(log) == 1
    assert log[0]["operation"] == "import_cellxgene"
    assert "CellxGENE" in log[0]["description"]
    assert "conversions" in log[0]["details"]
    assert log[0]["details"]["source_schema_version"] == "7.1.0"


def test_convert_expression_unchanged(cellxgene_h5ad):
    original = ad.read_h5ad(str(cellxgene_h5ad))
    result = convert_cellxgene_to_hca(str(cellxgene_h5ad))
    written = ad.read_h5ad(result["output_path"])

    assert written.X.shape == original.X.shape
    assert written.n_obs == original.n_obs
    assert written.n_vars == original.n_vars


def test_convert_title_preserved_in_uns(cellxgene_h5ad):
    result = convert_cellxgene_to_hca(str(cellxgene_h5ad))
    written = ad.read_h5ad(result["output_path"])

    assert written.uns["title"] == "snRNA-seq of Human Retina - Test Subset"


def test_convert_custom_output_dir(cellxgene_h5ad, tmp_path):
    out_dir = tmp_path / "converted"
    out_dir.mkdir()
    result = convert_cellxgene_to_hca(str(cellxgene_h5ad), output_dir=str(out_dir))
    assert "error" not in result
    assert result["output_path"].startswith(str(out_dir))


def test_convert_bad_path():
    result = convert_cellxgene_to_hca("/nonexistent/file.h5ad")
    assert "error" in result


def test_convert_rejects_non_cellxgene(sample_h5ad_for_write):
    """Non-cellxgene file (no schema_version in uns) is rejected."""
    adata = ad.read_h5ad(str(sample_h5ad_for_write))
    del adata.uns["schema_version"]
    no_sv_path = sample_h5ad_for_write.parent / "no-schema-version.h5ad"
    adata.write_h5ad(no_sv_path)

    result = convert_cellxgene_to_hca(str(no_sv_path))
    assert "error" in result
    assert "CellxGENE" in result["error"]


def test_convert_rejects_old_cellxgene_schema(cellxgene_h5ad):
    """CellxGENE schema < 6.0 is rejected."""
    adata = ad.read_h5ad(str(cellxgene_h5ad))
    adata.uns["schema_version"] = "5.1.0"
    old_path = cellxgene_h5ad.parent / "old-schema.h5ad"
    adata.write_h5ad(old_path)

    result = convert_cellxgene_to_hca(str(old_path))
    assert "error" in result
    assert "6.0+" in result["error"]


def test_convert_missing_title(cellxgene_h5ad):
    """File without a title in uns returns an error."""
    adata = ad.read_h5ad(str(cellxgene_h5ad))
    del adata.uns["title"]
    no_title_path = cellxgene_h5ad.parent / "no-title.h5ad"
    adata.write_h5ad(no_title_path)

    result = convert_cellxgene_to_hca(str(no_title_path))
    assert "error" in result
    assert "title" in result["error"].lower()


def test_convert_returns_source_and_title(cellxgene_h5ad):
    result = convert_cellxgene_to_hca(str(cellxgene_h5ad))
    assert result["source"] == cellxgene_h5ad.name
    assert result["title"] == "snRNA-seq of Human Retina - Test Subset"
