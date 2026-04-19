"""HCA labeler - extends cellxgene AnnDataLabelAppender with HCA-specific behavior.

Populates derived columns (var feature_*, obs ontology labels, observation_joinid)
using GENCODE 48 and cellxgene-ontology-guide, while:
  * Skipping CELLxGENE-only uns keys (schema_version, schema_reference, organism label).
  * Tolerating Ensembl IDs not in bundled GENCODE (sets NaN instead of raising).
  * Copying organism_ontology_term_id into uns when single-valued in obs.

See packages/hca-schema-validator/PRD-hca-add-labels.md for full design.
"""

from pathlib import Path
from typing import Dict, List

import pandas as pd
import yaml

from hca_schema_validator._vendored.cellxgene_schema import gencode
from hca_schema_validator._vendored.cellxgene_schema.gencode import get_gene_checker
from hca_schema_validator._vendored.cellxgene_schema.utils import get_hash_digest_column
from hca_schema_validator._vendored.cellxgene_schema.write_labels import AnnDataLabelAppender

_SCHEMA_PATH = Path(__file__).parent / "schema_definitions" / "hca_schema_definition.yaml"


class HCALabeler(AnnDataLabelAppender):
    """HCA-flavored AnnDataLabelAppender.

    Subclasses the vendored CELLxGENE labeler with three changes:
      1. Loads hca_schema_definition.yaml as schema_def.
      2. Overrides the 5 feature mapping methods to return NaN when the
         Ensembl ID isn't recognized by bundled GENCODE.
      3. Overrides write_labels to skip CELLxGENE-only uns keys and to
         write uns['organism_ontology_term_id'] (when single-valued in
         obs) plus obs['observation_joinid'].
    """

    def __init__(self, adata):
        super().__init__(adata)
        with open(_SCHEMA_PATH) as f:
            self.schema_def = yaml.safe_load(f)

    # -- NaN-tolerance overrides: each wraps the same inner GENCODE lookup as
    # the base, but returns pd.NA when get_organism_from_feature_id yields None
    # (the base raises ValueError on the first unknown ID).

    def _get_mapping_dict_feature_id(self, ids: List[str]) -> Dict[str, object]:
        out: Dict[str, object] = {}
        for i in ids:
            organism = gencode.get_organism_from_feature_id(i)
            out[i] = pd.NA if organism is None else get_gene_checker(organism).get_symbol(i)
        return out

    def _get_mapping_dict_feature_reference(self, ids: List[str]) -> Dict[str, object]:
        out: Dict[str, object] = {}
        for i in ids:
            organism = gencode.get_organism_from_feature_id(i)
            out[i] = pd.NA if organism is None else organism.value
        return out

    def _get_mapping_dict_feature_type(self, ids: List[str]) -> Dict[str, object]:
        out: Dict[str, object] = {}
        for i in ids:
            organism = gencode.get_organism_from_feature_id(i)
            out[i] = pd.NA if organism is None else get_gene_checker(organism).get_type(i)
        return out

    def _get_mapping_dict_feature_length(self, ids: List[str]) -> Dict[str, object]:
        out: Dict[str, object] = {}
        for i in ids:
            organism = gencode.get_organism_from_feature_id(i)
            out[i] = pd.NA if organism is None else get_gene_checker(organism).get_length(i)
        return out

    def _get_mapping_dict_feature_biotype(self, ids: List[str]) -> Dict[str, object]:
        # Base uses ERCC prefix only and never touches organism, so it can't fail.
        # We still NaN unknown-organism IDs to keep R1 consistent: all five
        # feature_* columns are NaN for rows the rest of the labeler can't resolve.
        out: Dict[str, object] = {}
        for i in ids:
            organism = gencode.get_organism_from_feature_id(i)
            if organism is None:
                out[i] = pd.NA
            elif i.startswith("ERCC"):
                out[i] = "spike-in"
            else:
                out[i] = "gene"
        return out

    # -- HCA-specific write path --

    def write_labels(self, output_path: str) -> None:
        """Apply HCA labels and write a new h5ad.

        Unlike the base, does NOT set uns['schema_version'] or
        uns['schema_reference'] (CELLxGENE-only). Copies
        organism_ontology_term_id from obs to uns when single-valued,
        and writes obs['observation_joinid'].
        """
        self._add_labels()
        self._remove_categories_with_zero_values()

        organism_col = self.adata.obs.get("organism_ontology_term_id")
        if organism_col is not None:
            vals = organism_col.dropna().unique()
            if len(vals) == 1:
                self.adata.uns["organism_ontology_term_id"] = str(vals[0])

        self.adata.obs["observation_joinid"] = get_hash_digest_column(self.adata.obs)

        self.adata.write_h5ad(output_path, compression="gzip")
