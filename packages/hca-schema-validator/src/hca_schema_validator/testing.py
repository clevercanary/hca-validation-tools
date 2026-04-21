"""Runtime test helpers for hca-schema-validator and downstream packages.

Kept minimal — the rich fixtures under ``tests/fixtures/`` are test-only and
not installed. This module gets packaged so other packages' test suites
(e.g. ``hca-anndata-mcp``) can build a labelable h5ad without reaching into
this package's test tree.
"""

from __future__ import annotations

from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse


# GENCODE-recognized human Ensembl IDs used in the existing labeler fixtures.
# These all resolve to a gene symbol, so ``feature_name`` comes out fully
# populated (helps test the happy-path overwrite reporting).
_ENSEMBL_IDS = (
    "ENSG00000127603",  # MACF1
    "ENSG00000141510",  # TP53
    "ENSG00000012048",  # BRCA1
    "ENSG00000139618",  # BRCA2
    "ENSG00000002330",  # BAD
    "ENSG00000000005",  # TNMD
    "ENSG00000000419",  # DPM1
)


def create_labelable_h5ad(path: Path) -> Path:
    """Create a small h5ad that passes :class:`HCALabeler` preflight.

    Writes the file to ``path`` and returns it. Exposes:

    - ``obs`` with the required ``*_ontology_term_id`` columns the labeler
      reads, including ``organism_ontology_term_id`` set to human.
    - ``var`` with GENCODE-resolvable Ensembl IDs on the index.
    - ``raw`` populated from a copy of ``X`` so raw.var mirroring fires.

    The resulting file has no CellxGENE-only ``uns`` keys (``schema_version``
    / ``schema_reference``) so preflight passes.
    """
    n_obs = 4
    n_vars = len(_ENSEMBL_IDS)

    X = sparse.random(n_obs, n_vars, density=0.5, format="csr", dtype=np.float32, random_state=0)  # pyright: ignore[reportCallIssue]

    obs = pd.DataFrame(
        {
            "cell_type_ontology_term_id": pd.Categorical(["CL:0000066"] * n_obs),
            "assay_ontology_term_id": pd.Categorical(["EFO:0009899"] * n_obs),
            "disease_ontology_term_id": pd.Categorical(["MONDO:0100096"] * n_obs),
            "sex_ontology_term_id": pd.Categorical(["PATO:0000383"] * n_obs),
            "tissue_ontology_term_id": pd.Categorical(["UBERON:0002048"] * n_obs),
            "self_reported_ethnicity_ontology_term_id": pd.Categorical(["HANCESTRO:0019"] * n_obs),
            "development_stage_ontology_term_id": pd.Categorical(["HsapDv:0000003"] * n_obs),
            "organism_ontology_term_id": pd.Categorical(["NCBITaxon:9606"] * n_obs),
        },
        index=[f"cell_{i}" for i in range(n_obs)],  # pyright: ignore[reportArgumentType]
    )

    var = pd.DataFrame(
        {"feature_is_filtered": [False] * n_vars},
        index=list(_ENSEMBL_IDS),  # pyright: ignore[reportArgumentType]
    )

    adata = ad.AnnData(X=X, obs=obs, var=var)
    adata.raw = adata.copy()
    adata.write_h5ad(path)
    return path


# CAP-required per-set obs column suffixes the cell-annotation validator checks.
_CAP_COLUMN_SUFFIXES = (
    "cell_fullname",
    "cell_ontology_exists",
    "cell_ontology_term_id",
    "cell_ontology_term",
    "rationale",
    "marker_gene_evidence",
)


def create_cap_annotated_h5ad(
    path: Path,
    set_name: str = "author_annotation",
    schema_version: str = "0.2.0",
) -> Path:
    """Create a small h5ad with a valid CAP annotation set.

    Builds on :func:`create_labelable_h5ad` and overlays the CAP structures
    (``obs`` columns with the ``<set>--<col>`` prefix + ``uns`` metadata) that
    :class:`HCACellAnnotationValidator` expects. Returns ``path``.

    Tests can mutate the written file to exercise specific failure modes.
    """
    create_labelable_h5ad(path)
    adata = ad.read_h5ad(path)

    n_obs = adata.n_obs
    for suffix in _CAP_COLUMN_SUFFIXES:
        adata.obs[f"{set_name}--{suffix}"] = pd.Categorical(["value"] * n_obs)

    adata.uns["cellannotation_schema_version"] = schema_version
    adata.uns["cellannotation_metadata"] = {
        set_name: {"title": f"{set_name} title"}
    }

    adata.write_h5ad(path)
    return path
