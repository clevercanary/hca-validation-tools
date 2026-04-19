"""Tests for HCALabeler."""

import copy
import tempfile
from pathlib import Path

import anndata
import pandas as pd
import pytest

from hca_schema_validator import HCALabeler

from .fixtures import hca_fixtures


def _label_to_temp(adata):
    """Label adata and read the written file back. Returns the re-loaded adata."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "labeled.h5ad"
        HCALabeler(adata).write_labels(str(out_path))
        return anndata.read_h5ad(str(out_path))


@pytest.fixture
def base_adata():
    """Fresh, unlabeled copy of the canonical HCA-valid fixture."""
    return copy.deepcopy(hca_fixtures.adata)


def test_feature_name_populated_from_ensembl(base_adata):
    """var['feature_name'] is populated with GENCODE symbols for known Ensembl IDs."""
    labeled = _label_to_temp(base_adata)
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


def test_unknown_ensembl_yields_nan(base_adata):
    """Unknown Ensembl IDs get NaN across all five feature_* columns; real rows unaffected."""
    # Replace one known ID with a fake one. Patch both .var and .raw.var so their
    # indexes stay aligned.
    known_ids = list(base_adata.var.index)
    fake_id = "ENSG99999999999"
    new_ids = [fake_id] + known_ids[1:]
    base_adata.var.index = pd.Index(new_ids)
    raw = base_adata.raw.to_adata()
    raw.var.index = pd.Index(new_ids)
    base_adata.raw = raw

    labeled = _label_to_temp(base_adata)

    # Fake row: all five derived columns are NaN
    for col in ("feature_name", "feature_reference", "feature_biotype", "feature_length", "feature_type"):
        assert pd.isna(labeled.var.loc[fake_id, col]), f"{col} should be NaN for unknown ID"

    # Real row still resolves
    assert labeled.var.loc["ENSG00000141510", "feature_name"] == "TP53"


def test_obs_labels_populated_from_term_id(base_adata):
    """obs['tissue'], obs['cell_type'], obs['assay'], obs['disease'] are written."""
    labeled = _label_to_temp(base_adata)
    for col in ("tissue", "cell_type", "assay", "disease"):
        assert col in labeled.obs.columns, f"{col} should be added by labeler"
        assert labeled.obs[col].notna().all(), f"{col} should be fully populated"


def test_existing_obs_label_overwritten(base_adata):
    """Pre-existing obs label is replaced with the canonical value."""
    base_adata.obs["tissue"] = "STALE_VALUE"
    labeled = _label_to_temp(base_adata)
    assert "STALE_VALUE" not in labeled.obs["tissue"].astype(str).unique()


def test_organism_copied_to_uns_when_single_valued(base_adata):
    """Single-valued obs organism is also written to uns."""
    labeled = _label_to_temp(base_adata)
    assert labeled.uns.get("organism_ontology_term_id") == "NCBITaxon:9606"


def test_organism_not_copied_when_multivalued(base_adata):
    """Multi-valued organism in obs is not copied to uns."""
    # Introduce a second organism value on one cell
    base_adata.obs["organism_ontology_term_id"] = base_adata.obs["organism_ontology_term_id"].astype(str)
    base_adata.obs.iloc[0, base_adata.obs.columns.get_loc("organism_ontology_term_id")] = "NCBITaxon:10090"

    labeled = _label_to_temp(base_adata)
    assert "organism_ontology_term_id" not in labeled.uns


def test_cellxgene_only_uns_keys_absent(base_adata):
    """schema_version, schema_reference, and the label-form 'organism' are not written."""
    labeled = _label_to_temp(base_adata)
    assert "schema_version" not in labeled.uns
    assert "schema_reference" not in labeled.uns
    assert "organism" not in labeled.uns


def test_observation_joinid_written(base_adata):
    """obs['observation_joinid'] is written with one value per cell."""
    labeled = _label_to_temp(base_adata)
    assert "observation_joinid" in labeled.obs.columns
    assert len(labeled.obs["observation_joinid"]) == base_adata.n_obs
    assert labeled.obs["observation_joinid"].notna().all()


def test_producer_columns_preserved(base_adata):
    """Custom producer columns outside the labeler's controlled set are untouched."""
    base_adata.obs["author_cell_type"] = "custom_label"
    base_adata.var["gene_symbol"] = "CUSTOM_SYMBOL"
    labeled = _label_to_temp(base_adata)
    assert (labeled.obs["author_cell_type"].astype(str) == "custom_label").all()
    assert (labeled.var["gene_symbol"].astype(str) == "CUSTOM_SYMBOL").all()
