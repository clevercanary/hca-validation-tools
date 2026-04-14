"""Validate CAP marker genes against an h5ad file's var."""

from __future__ import annotations

from ._gencode import load_gencode_reference
from ._io import (
    read_obs_categorical_values,
    read_obs_column_names,
    read_var_gene_names,
)
from .cap import _find_annotation_sets

_SKIP_VALUES = {"unknown", "", "NA", "na", "none", "None"}


def _extract_marker_genes_from_categories(categories: set[str]) -> set[str]:
    """Parse unique gene symbols from a set of category values.

    Values are comma-separated gene symbols like "MARCO,CST3,FABP4,INHBA".
    Skips null, empty, and placeholder values.
    """
    genes: set[str] = set()
    for val in categories:
        val = str(val).strip()
        if val in _SKIP_VALUES:
            continue
        for gene in val.split(","):
            gene = gene.strip()
            if gene and gene not in _SKIP_VALUES:
                genes.add(gene)
    return genes


def _classify_missing(
    gene: str,
    name_to_ids: dict[str, list[str]],
    eid_to_var_name: dict[str, str],
) -> dict:
    """Classify a missing marker gene as a known rename or probable typo."""
    if gene in name_to_ids:
        # Valid current GENCODE symbol -- check if any of its Ensembl IDs
        # are in var under a different name
        for eid in name_to_ids[gene]:
            if eid in eid_to_var_name:
                return {
                    "marker_gene": gene,
                    "var_name": eid_to_var_name[eid],
                    "ensembl_id": eid,
                    "type": "known_rename",
                }
        # Valid GENCODE gene, but not measured in this file
        return {"marker_gene": gene, "type": "missing_from_var"}
    # Not in GENCODE -- probable typo
    return {"marker_gene": gene, "type": "not_in_gencode"}


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
        obs_columns = read_obs_column_names(path)

        if "organism_ontology_term_id" not in obs_columns:
            return {"error": "organism_ontology_term_id not found in obs columns"}
        organisms = read_obs_categorical_values(path, "organism_ontology_term_id")
        non_human = organisms - {"NCBITaxon:9606"}
        if non_human:
            return {"error": f"Only human (NCBITaxon:9606) is supported, found: {organisms}"}
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
                "missing_from_var": [],
                "not_in_gencode": [],
                "details": {},
            }

        gene_names, eid_to_var_name = read_var_gene_names(path)
        _, name_to_ids = load_gencode_reference()

        all_renames = []
        all_missing_from_var = []
        all_not_in_gencode = []
        all_unique = set()
        details = {}

        for setname in sets_with_markers:
            marker_col = f"{setname}--marker_gene_evidence"
            # Read only the category values, not the full per-cell column
            categories = read_obs_categorical_values(path, marker_col)
            markers = _extract_marker_genes_from_categories(categories)
            all_unique.update(markers)

            found = markers & gene_names
            missing = markers - gene_names

            renames = []
            missing_from_var = []
            not_in_gencode = []
            for gene in sorted(missing):
                classification = _classify_missing(gene, name_to_ids, eid_to_var_name)
                if classification["type"] == "known_rename":
                    renames.append(classification)
                elif classification["type"] == "missing_from_var":
                    missing_from_var.append(classification)
                else:
                    not_in_gencode.append(classification)

            all_renames.extend(renames)
            all_missing_from_var.extend(missing_from_var)
            all_not_in_gencode.extend(not_in_gencode)

            details[setname] = {
                "unique_markers": len(markers),
                "found": len(found),
                "known_renames": renames,
                "missing_from_var": missing_from_var,
                "not_in_gencode": not_in_gencode,
            }

        total_found = len(all_unique & gene_names)

        # Deduplicate top-level lists (same gene can appear in multiple sets)
        seen = set()
        def _dedup(items):
            out = []
            for item in items:
                key = item["marker_gene"]
                if key not in seen:
                    seen.add(key)
                    out.append(item)
            return out

        return {
            "annotation_sets_with_markers": sets_with_markers,
            "total_unique_markers": len(all_unique),
            "found_in_var": total_found,
            "missing": len(all_unique) - total_found,
            "known_renames": _dedup(all_renames),
            "missing_from_var": _dedup(all_missing_from_var),
            "not_in_gencode": _dedup(all_not_in_gencode),
            "details": details,
        }

    except Exception as e:
        return {"error": str(e)}
