"""Validate CAP marker genes against an h5ad file's var."""

from __future__ import annotations

import pandas as pd

from ._gencode import load_gencode_reference
from ._io import open_h5ad
from .cap import _find_annotation_sets

_SKIP_VALUES = {"unknown", "", "NA", "na", "none", "None"}


def _extract_marker_genes(series: pd.Series) -> set[str]:
    """Parse unique gene symbols from a marker_gene_evidence series.

    Values are comma-separated gene symbols like "MARCO,CST3,FABP4,INHBA".
    Skips null, empty, and placeholder values.
    """
    genes: set[str] = set()
    for val in series.dropna().unique():
        val = str(val).strip()
        if val in _SKIP_VALUES:
            continue
        for gene in val.split(","):
            gene = gene.strip()
            if gene and gene not in _SKIP_VALUES:
                genes.add(gene)
    return genes


def _get_gene_names_from_var(var: pd.DataFrame) -> tuple[set[str], dict[str, str]]:
    """Extract gene symbol set and ensembl_id->symbol map from var.

    Handles both CellxGENE-style (feature_name) and other (gene_name) files.

    Returns:
        gene_names: Set of all gene symbols in var
        eid_to_var_name: Dict mapping Ensembl ID (var.index) to gene symbol
    """
    for col in ("feature_name", "gene_name"):
        if col in var.columns:
            str_values = var[col].astype(str).values
            gene_names = set(str_values)
            eid_to_var_name = dict(zip(var.index, str_values))
            return gene_names, eid_to_var_name
    # Fallback: var.index IS the gene names, no Ensembl ID mapping
    return set(var.index), {}


def _classify_missing(
    gene: str,
    name_to_ids: dict[str, list[str]],
    eid_to_var_name: dict[str, str],
) -> dict:
    """Classify a missing marker gene as a known rename or probable typo."""
    if gene in name_to_ids:
        # Valid current GENCODE symbol — check if any of its Ensembl IDs
        # are in var under a different name
        for eid in name_to_ids[gene]:
            if eid in eid_to_var_name:
                return {
                    "marker_gene": gene,
                    "var_name": eid_to_var_name[eid],
                    "ensembl_id": eid,
                    "type": "known_rename",
                }
        # In GENCODE but not in this file's var at all
        return {"marker_gene": gene, "in_gencode": True, "type": "probable_typo"}
    # Not in GENCODE — probable typo
    return {"marker_gene": gene, "in_gencode": False, "type": "probable_typo"}


def validate_marker_genes(path: str, annotation_set: str | None = None) -> dict:
    """Validate that CAP marker genes exist in an h5ad file's var.

    Checks each marker gene symbol from CAP annotation obs columns against
    var['feature_name']. Missing genes are classified as known GENCODE renames
    or probable typos.

    Args:
        path: Absolute path to an .h5ad file.
        annotation_set: Specific annotation set to validate. If None, validates all.

    Returns:
        Dict with validation results, or 'error' on failure.
    """
    try:
        with open_h5ad(path) as adata:
            obs_columns = list(adata.obs.columns)
            all_sets = _find_annotation_sets(obs_columns)

            if annotation_set:
                if annotation_set not in all_sets:
                    return {
                        "error": (
                            f"Annotation set '{annotation_set}' not found. "
                            f"Available: {all_sets}"
                        )
                    }
                sets_to_check = [annotation_set]
            else:
                sets_to_check = all_sets

            # Filter to sets that have marker_gene_evidence
            sets_with_markers = [
                s for s in sets_to_check
                if f"{s}--marker_gene_evidence" in obs_columns
            ]

            if not sets_with_markers:
                return {
                    "annotation_sets_with_markers": [],
                    "total_unique_markers": 0,
                    "found_in_var": 0,
                    "missing": 0,
                    "known_renames": [],
                    "probable_typos": [],
                    "details": {},
                }

            gene_names, eid_to_var_name = _get_gene_names_from_var(adata.var)
            _, name_to_ids = load_gencode_reference()

            all_renames = []
            all_typos = []
            all_unique = set()
            details = {}

            for setname in sets_with_markers:
                marker_col = f"{setname}--marker_gene_evidence"
                markers = _extract_marker_genes(adata.obs[marker_col])
                all_unique.update(markers)

                found = markers & gene_names
                missing = markers - gene_names

                renames = []
                typos = []
                for gene in sorted(missing):
                    classification = _classify_missing(gene, name_to_ids, eid_to_var_name)
                    if classification["type"] == "known_rename":
                        renames.append(classification)
                    else:
                        typos.append(classification)

                all_renames.extend(renames)
                all_typos.extend(typos)

                details[setname] = {
                    "unique_markers": len(markers),
                    "found": len(found),
                    "known_renames": renames,
                    "probable_typos": typos,
                }

            total_found = len(all_unique & gene_names)

            return {
                "annotation_sets_with_markers": sets_with_markers,
                "total_unique_markers": len(all_unique),
                "found_in_var": total_found,
                "missing": len(all_unique) - total_found,
                "known_renames": all_renames,
                "probable_typos": all_typos,
                "details": details,
            }

    except Exception as e:
        return {"error": str(e)}
