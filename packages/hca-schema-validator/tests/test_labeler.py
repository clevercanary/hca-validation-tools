"""Tests for HCALabeler."""

import copy

import anndata
import pandas as pd
import pytest

from hca_schema_validator import HCALabeler

from .fixtures.hca_fixtures import adata as valid_adata


@pytest.fixture
def base_adata():
    # Deepcopy the module-level fixture so tests don't mutate each other's state.
    return copy.deepcopy(valid_adata)


@pytest.fixture
def labeled(base_adata, tmp_path):
    out_path = tmp_path / "labeled.h5ad"
    HCALabeler(base_adata).write_labels(str(out_path))
    return anndata.read_h5ad(str(out_path))


def _label(adata, tmp_path):
    out_path = tmp_path / "labeled.h5ad"
    HCALabeler(adata).write_labels(str(out_path))
    return anndata.read_h5ad(str(out_path))


def test_feature_name_populated_from_ensembl(labeled):
    expected = {
        "ENSG00000127603": "MACF1",
        "ENSG00000141510": "TP53",
        "ENSG00000012048": "BRCA1",
        "ENSG00000139618": "BRCA2",
        "ENSG00000002330": "BAD",
        "ENSG00000000005": "TNMD",
        "ENSG00000000419": "DPM1",
    }
    for ens_id, symbol in expected.items():
        assert labeled.var.loc[ens_id, "feature_name"] == symbol


def test_unknown_ensembl_yields_nan(base_adata, tmp_path):
    known_ids = list(base_adata.var.index)
    fake_id = "ENSG99999999999"
    new_ids = [fake_id] + known_ids[1:]
    base_adata.var.index = pd.Index(new_ids)
    raw = base_adata.raw.to_adata()
    raw.var.index = pd.Index(new_ids)
    base_adata.raw = raw

    labeled = _label(base_adata, tmp_path)
    raw_var = labeled.raw.to_adata().var

    for col in ("feature_name", "feature_reference", "feature_biotype", "feature_length", "feature_type"):
        assert pd.isna(labeled.var.loc[fake_id, col]), f"var.{col} should be NaN for unknown ID"
        assert pd.isna(raw_var.loc[fake_id, col]), f"raw.var.{col} should be NaN for unknown ID"
    assert labeled.var.loc["ENSG00000141510", "feature_name"] == "TP53"
    assert raw_var.loc["ENSG00000141510", "feature_name"] == "TP53"


def test_obs_labels_populated_from_term_id(labeled):
    for col in (
        "tissue",
        "cell_type",
        "assay",
        "disease",
        "sex",
        "organism",
        "development_stage",
        "self_reported_ethnicity",
    ):
        assert col in labeled.obs.columns, f"{col} should be added by labeler"
        assert labeled.obs[col].notna().all(), f"{col} should be fully populated"


def test_existing_obs_label_overwritten(base_adata, tmp_path):
    base_adata.obs["tissue"] = "STALE_VALUE"
    labeled = _label(base_adata, tmp_path)
    assert "STALE_VALUE" not in labeled.obs["tissue"].astype(str).unique()


def test_organism_copied_to_uns_when_single_valued(labeled):
    assert labeled.uns.get("organism_ontology_term_id") == "NCBITaxon:9606"


def test_organism_not_copied_when_multivalued(base_adata, tmp_path):
    base_adata.obs["organism_ontology_term_id"] = base_adata.obs["organism_ontology_term_id"].astype(str)
    first_label = base_adata.obs.index[0]
    base_adata.obs.loc[first_label, "organism_ontology_term_id"] = "NCBITaxon:10090"

    labeled = _label(base_adata, tmp_path)
    assert "organism_ontology_term_id" not in labeled.uns


def test_cellxgene_only_uns_keys_absent(labeled):
    assert "schema_version" not in labeled.uns
    assert "schema_reference" not in labeled.uns
    assert "organism" not in labeled.uns


def test_observation_joinid_written(labeled, base_adata):
    assert "observation_joinid" in labeled.obs.columns
    assert len(labeled.obs["observation_joinid"]) == base_adata.n_obs
    assert labeled.obs["observation_joinid"].notna().all()


def test_preflight_fails_on_missing_ontology_term_id_column(base_adata, tmp_path):
    del base_adata.obs["cell_type_ontology_term_id"]
    with pytest.raises(ValueError, match="cell_type_ontology_term_id"):
        _label(base_adata, tmp_path)


def test_preflight_fails_when_cellxgene_schema_keys_present(base_adata, tmp_path):
    base_adata.uns["schema_version"] = "5.0.0"
    with pytest.raises(ValueError, match="schema_version"):
        _label(base_adata, tmp_path)


def test_producer_columns_preserved(base_adata, tmp_path):
    base_adata.obs["author_cell_type"] = "custom_label"
    base_adata.var["gene_symbol"] = "CUSTOM_SYMBOL"
    labeled = _label(base_adata, tmp_path)
    assert (labeled.obs["author_cell_type"].astype(str) == "custom_label").all()
    assert (labeled.var["gene_symbol"].astype(str) == "CUSTOM_SYMBOL").all()
