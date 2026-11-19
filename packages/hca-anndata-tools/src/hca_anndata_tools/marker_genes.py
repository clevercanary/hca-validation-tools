"""Validate CAP marker genes against an h5ad file's var."""

from __future__ import annotations

import pandas as pd

from ._gencode import load_gencode_reference
from ._io import (
    DEFAULT_PLACEHOLDERS,
    gate_h5ad_paths,
    is_missing_value,
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


def human_gate_failure(path: str, obs_columns: list[str]) -> str | None:
    """Why ``path`` cannot be checked against the human GENCODE, or None when it can."""
    if "organism_ontology_term_id" not in obs_columns:
        return "organism_ontology_term_id not found in obs columns"
    organisms = read_obs_categorical_values(path, "organism_ontology_term_id")
    # A masked (pd.NA) value is a missing organism, not evidence of a
    # non-human one — and sorted() below cannot order pd.NA anyway.
    organisms = {o for o in organisms if not pd.isna(o)}
    if not organisms:
        # All values masked or NaN: absence of evidence must not pass the
        # human-only gate and validate against the human GENCODE.
        return "organism_ontology_term_id has no readable values — cannot confirm a human dataset"
    non_human = organisms - {"NCBITaxon:9606"}
    if non_human:
        return f"Only human (NCBITaxon:9606) is supported, found non-human: {sorted(non_human)}"
    return None


def marker_symbols(path: str, annotation_sets: list[str]) -> dict[str, set[str]]:
    """The gene symbols each set's ``--marker_gene_evidence`` column cites; sets without that column are left out."""
    obs_columns = read_obs_column_names(path)
    return {
        s: _extract_marker_genes_from_categories(read_obs_categorical_values(path, f"{s}--marker_gene_evidence"))
        for s in annotation_sets
        if f"{s}--marker_gene_evidence" in obs_columns
    }


def classify_markers(
    markers_by_set: dict[str, set[str]],
    gene_names: set[str],
    eid_to_var_name: dict[str, str],
    name_to_ids: dict[str, list[str]],
) -> dict:
    """Which markers are in ``gene_names`` and why each missing one is missing, shaped as `validate_marker_genes`."""
    all_renames = []
    all_missing_from_var = []
    all_not_in_gencode = []
    all_unique = set()
    details = {}

    for setname, markers in markers_by_set.items():
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
        "annotation_sets_with_markers": list(markers_by_set),
        "total_unique_markers": len(all_unique),
        "found_in_var": total_found,
        "missing": len(all_unique) - total_found,
        "known_renames": _dedup(all_renames),
        "missing_from_var": _dedup(all_missing_from_var),
        "not_in_gencode": _dedup(all_not_in_gencode),
        "details": details,
    }


def markers_against_var(markers_by_set: dict[str, set[str]], var_path: str) -> dict:
    """:func:`classify_markers` against the var of ``var_path``; reads nothing when there are no markers."""
    if not markers_by_set:
        return classify_markers({}, set(), {}, {})
    gene_names, eid_to_var_name = read_var_gene_names(var_path)
    _, name_to_ids = load_gencode_reference()
    return classify_markers(markers_by_set, gene_names, eid_to_var_name, name_to_ids)


@gate_h5ad_paths
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
        Dict with validation results, or 'error' on failure.
    """
    try:
        path = resolve_latest(path)
        obs_columns = read_obs_column_names(path)
        if failure := human_gate_failure(path, obs_columns):
            return {"error": failure}
        all_sets = _find_annotation_sets(obs_columns)

        if annotation_set:
            if annotation_set not in all_sets:
                return {"error": (f"Annotation set '{annotation_set}' not found. Available: {all_sets}")}
            sets_to_check = [annotation_set]
        else:
            sets_to_check = all_sets

        return markers_against_var(marker_symbols(path, sets_to_check), path)

    except Exception as e:
        return {"error": str(e)}
