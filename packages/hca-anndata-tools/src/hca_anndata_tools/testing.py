"""Test utilities for hca-anndata-tools and downstream packages."""

from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import scipy.sparse as sp


def create_sample_h5ad(path: Path) -> Path:
    """Create a small but realistic h5ad file for testing.

    Contains:
    - 50 cells, 20 genes
    - obs columns: sex, tissue, cell_type, n_counts (numeric)
    - var columns: gene_name, highly_variable (bool)
    - obsm: X_umap (2D), X_pca (10D)
    - layers: raw_counts
    - uns: title, schema_version, batch_condition

    Args:
        path: Where to write the .h5ad file.

    Returns:
        The path to the written file.
    """
    n_obs, n_vars = 50, 20

    # Sparse count matrix
    rng = np.random.default_rng(42)
    X = sp.random(n_obs, n_vars, density=0.3, format="csr", dtype=np.float32, random_state=rng)

    obs = pd.DataFrame(
        {
            "sex": pd.Categorical(rng.choice(["male", "female", "unknown"], n_obs)),
            "tissue": pd.Categorical(rng.choice(["brain", "lung", "heart"], n_obs)),
            "cell_type": pd.Categorical(rng.choice(
                ["T cell", "B cell", "macrophage", "neuron", "epithelial"], n_obs
            )),
            "n_counts": rng.integers(500, 5000, n_obs).astype(np.float32),
        },
        index=[f"cell_{i}" for i in range(n_obs)],
    )

    var = pd.DataFrame(
        {
            "gene_name": [f"GENE{i}" for i in range(n_vars)],
            "highly_variable": rng.choice([True, False], n_vars),
        },
        index=[f"ENSG{i:011d}" for i in range(n_vars)],
    )

    adata = ad.AnnData(X=X, obs=obs, var=var)
    adata.obsm["X_umap"] = rng.standard_normal((n_obs, 2)).astype(np.float32)
    adata.obsm["X_pca"] = rng.standard_normal((n_obs, 10)).astype(np.float32)
    adata.layers["raw_counts"] = X.copy()
    adata.uns["title"] = "Test Dataset"
    adata.uns["schema_version"] = "5.1.0"
    adata.uns["batch_condition"] = np.array(["batch1", "batch2"])

    adata.write_h5ad(path)
    return path


def create_cellxgene_h5ad(path: Path) -> Path:
    """Create a small h5ad file mimicking CellxGENE Discover output.

    Contains:
    - 30 cells, 15 genes
    - uns: title, schema_version, schema_reference, citation,
           organism_ontology_term_id, organism
    - obs: cellxgene columns + label columns (cell_type, assay, etc.)
           + observation_joinid
    - var: feature_is_filtered + label columns (feature_name, etc.)
    - obsm: X_umap
    - raw: copy of X

    Args:
        path: Where to write the .h5ad file.

    Returns:
        The path to the written file.
    """
    n_obs, n_vars = 30, 15
    rng = np.random.default_rng(99)

    X = sp.random(n_obs, n_vars, density=0.3, format="csr", dtype=np.float32, random_state=rng)

    obs = pd.DataFrame(
        {
            "cell_type_ontology_term_id": pd.Categorical(
                rng.choice(["CL:0000540", "CL:0000235"], n_obs)
            ),
            "assay_ontology_term_id": pd.Categorical(["EFO:0009922"] * n_obs),
            "disease_ontology_term_id": pd.Categorical(["PATO:0000461"] * n_obs),
            "sex_ontology_term_id": pd.Categorical(
                rng.choice(["PATO:0000383", "PATO:0000384"], n_obs)
            ),
            "tissue_ontology_term_id": pd.Categorical(["UBERON:0000966"] * n_obs),
            "self_reported_ethnicity_ontology_term_id": pd.Categorical(["unknown"] * n_obs),
            "development_stage_ontology_term_id": pd.Categorical(["HsapDv:0000087"] * n_obs),
            "donor_id": pd.Categorical(rng.choice(["donor_1", "donor_2"], n_obs)),
            "suspension_type": pd.Categorical(["nucleus"] * n_obs),
            "tissue_type": pd.Categorical(["tissue"] * n_obs),
            "is_primary_data": [True] * n_obs,
            "sample_id": pd.Categorical(rng.choice(["sample_1", "sample_2"], n_obs)),
            "library_id": pd.Categorical(rng.choice(["lib_1", "lib_2"], n_obs)),
            "institute": pd.Categorical(["Test Institute"] * n_obs),
            # CellxGENE label columns (human-readable, added by cellxgene)
            "cell_type": pd.Categorical(rng.choice(["neuron", "macrophage"], n_obs)),
            "assay": pd.Categorical(["10x 3' v3"] * n_obs),
            "disease": pd.Categorical(["normal"] * n_obs),
            "sex": pd.Categorical(rng.choice(["female", "male"], n_obs)),
            "tissue": pd.Categorical(["retina"] * n_obs),
            "self_reported_ethnicity": pd.Categorical(["unknown"] * n_obs),
            "development_stage": pd.Categorical(["human adult stage"] * n_obs),
            "observation_joinid": [f"joinid_{i}" for i in range(n_obs)],
        },
        index=[f"AACG{i:08d}-1" for i in range(n_obs)],
    )

    var = pd.DataFrame(
        {
            "feature_is_filtered": [False] * n_vars,
            "feature_name": [f"GENE{i}" for i in range(n_vars)],
            "feature_reference": ["NCBITaxon:9606"] * n_vars,
            "feature_biotype": ["gene"] * n_vars,
            "feature_length": [1000] * n_vars,
            "feature_type": ["gene"] * n_vars,
        },
        index=[f"ENSG{i:011d}" for i in range(n_vars)],
    )

    adata = ad.AnnData(X=X, obs=obs, var=var)
    adata.obsm["X_umap"] = rng.standard_normal((n_obs, 2)).astype(np.float32)
    adata.raw = adata.copy()

    # CellxGENE uns fields
    adata.uns["title"] = "snRNA-seq of Human Retina - Test Subset"
    adata.uns["schema_version"] = "7.1.0"
    adata.uns["schema_reference"] = "https://github.com/chanzuckerberg/single-cell-curation/blob/main/schema/7.1.0/schema.md"
    adata.uns["citation"] = "Publication: https://doi.org/10.1234/test Dataset Version: https://datasets.cellxgene.cziscience.com/test-uuid.h5ad"
    adata.uns["organism_ontology_term_id"] = "NCBITaxon:9606"
    adata.uns["organism"] = "Homo sapiens"

    adata.write_h5ad(path)
    return path
