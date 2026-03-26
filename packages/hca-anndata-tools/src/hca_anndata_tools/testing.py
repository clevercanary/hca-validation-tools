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
