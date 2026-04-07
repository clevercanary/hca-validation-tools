"""GENCODE gene reference loader for marker gene validation."""

from __future__ import annotations

import csv
import gzip
from collections import defaultdict
from functools import lru_cache
from importlib import resources


@lru_cache(maxsize=1)
def load_gencode_reference() -> tuple[dict[str, str], dict[str, list[str]]]:
    """Load the GENCODE human gene reference.

    Returns:
        id_to_name: {ensembl_id: gene_name} for all genes
        name_to_ids: {gene_name: [ensembl_id, ...]} (list because some
            names map to multiple IDs, e.g., WASH7P)
    """
    id_to_name: dict[str, str] = {}
    name_to_ids: dict[str, list[str]] = defaultdict(list)

    ref = resources.files("hca_anndata_tools") / "reference_data" / "genes_homo_sapiens.csv.gz"
    with resources.as_file(ref) as path:
        with gzip.open(path, "rt") as f:
            for row in csv.reader(f):
                ensembl_id, gene_name = row[0], row[1]
                id_to_name[ensembl_id] = gene_name
                name_to_ids[gene_name].append(ensembl_id)

    return id_to_name, dict(name_to_ids)
