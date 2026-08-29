"""Validate CAP marker genes against an h5ad file's var."""

from __future__ import annotations

import pandas as pd

from ._gencode import load_gencode_reference
from ._io import (
    DEFAULT_PLACEHOLDERS,
    is_missing_value,
    masked_categories_error_for_path,
    read_obs_categorical_values,
    read_obs_column_names,
    read_var_gene_names,
)
from .cap import _find_annotation_sets
from .write import resolve_latest

# The one placeholder vocabulary (_io's), judged through is_missing_value —
# case-insensitive, and no entry collides with an HGNC symbol.
_PLACEHOLDERS = set(DEFAULT_PLACEHOLDERS)


def _extract_marker_genes_from_categories(categories: set) -> set[str]:
    """Parse unique gene symbols from a set of category values.

    Values are comma-separated gene symbols like "MARCO,CST3,FABP4,INHBA".
    Skips masked (pd.NA), empty, and placeholder values — absent evidence,
    not genes. Non-string values (a numeric evidence column) are reported as
    symbols for the GENCODE check to flag, never crashed on.
    """
    genes: set[str] = set()
    for val in categories:
        # pd.isna before str(): str(pd.NA) is "<NA>".
        if pd.isna(val):
            continue
        val = str(val).strip()
        if is_missing_value(val, _PLACEHOLDERS):
            continue
        for gene in val.split(","):
            gene = gene.strip()
            if not is_missing_value(gene, _PLACEHOLDERS):
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


def _with_corruption(result: dict, path: str) -> dict:
    """Attach the corruption notice to a successful validation result.

    This validator is h5py-only, so nothing upstream of it fails on a file
    anndata cannot open — the diagnostic still runs (principle 3's skip
    arm), and this key is how the corruption gets said. Every non-error
    return goes through here, because the version that guarded only the
    main return still handed back a clean verdict on a corrupt file whose
    annotation sets carry no marker evidence — the common non-CAP shape.

    One whole-file scan rather than per-column notices: it is a superset
    of what the columns this validator reads could report, so a clean
    verdict on a corrupt file is impossible wherever the masks sit.
    """
    if corruption := masked_categories_error_for_path(path, best_effort=True):
        result["corruption"] = corruption
    return result


def validate_marker_genes(path: str, annotation_set: str | None = None) -> dict:
    """Validate that CAP marker genes exist in an h5ad file's var.

    Expects an HCA integrated object with organism_ontology_term_id in obs.
    Rejects non-human organisms. Checks marker gene symbols from CAP
    annotation obs columns against var gene names (feature_name, gene_name,
    or var index as fallback). Missing genes are classified as GENCODE
    renames, unmeasured genes, or probable typos.

    Args:
        path: Absolute path to an HCA .h5ad file.
        annotation_set: Specific annotation set to validate. If None, validates all.

    Returns:
        Dict with validation results, or 'error' on failure. A
        ``corruption`` key names a defect that makes the file unreadable
        to anndata — a categorical whose categories are masked, or an
        element the scan could not read at all (a dangling link, a mask
        that does not fit its values). The validation still ran (this
        reader is h5py-only), but the file needs repair: report it
        alongside the marker findings rather than treating the result as
        a pass.
    """
    try:
        path = resolve_latest(path)
        obs_columns = read_obs_column_names(path)

        if "organism_ontology_term_id" not in obs_columns:
            return {"error": "organism_ontology_term_id not found in obs columns"}
        organisms = read_obs_categorical_values(path, "organism_ontology_term_id")
        # A masked (pd.NA) value is a missing organism, not evidence of a
        # non-human one — and sorted() below cannot order pd.NA anyway.
        organisms = {o for o in organisms if not pd.isna(o)}
        if not organisms:
            # All values masked or NaN: absence of evidence must not pass the
            # human-only gate and validate against the human GENCODE.
            return {"error": "organism_ontology_term_id has no readable values — cannot confirm a human dataset"}
        non_human = organisms - {"NCBITaxon:9606"}
        if non_human:
            return {"error": f"Only human (NCBITaxon:9606) is supported, found non-human: {sorted(non_human)}"}
        all_sets = _find_annotation_sets(obs_columns)

        if annotation_set:
            if annotation_set not in all_sets:
                return {"error": (f"Annotation set '{annotation_set}' not found. Available: {all_sets}")}
            sets_to_check = [annotation_set]
        else:
            sets_to_check = all_sets

        # Filter to sets that have marker_gene_evidence
        sets_with_markers = [s for s in sets_to_check if f"{s}--marker_gene_evidence" in obs_columns]

        if not sets_with_markers:
            return _with_corruption(
                {
                    "annotation_sets_with_markers": [],
                    "total_unique_markers": 0,
                    "found_in_var": 0,
                    "missing": 0,
                    "known_renames": [],
                    "missing_from_var": [],
                    "not_in_gencode": [],
                    "details": {},
                },
                path,
            )

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

        result = {
            "annotation_sets_with_markers": sets_with_markers,
            "total_unique_markers": len(all_unique),
            "found_in_var": total_found,
            "missing": len(all_unique) - total_found,
            "known_renames": _dedup(all_renames),
            "missing_from_var": _dedup(all_missing_from_var),
            "not_in_gencode": _dedup(all_not_in_gencode),
            "details": details,
        }
        return _with_corruption(result, path)

    except Exception as e:
        return {"error": str(e)}
