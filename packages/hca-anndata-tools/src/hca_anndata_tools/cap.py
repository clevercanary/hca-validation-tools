"""CAP (Cell Annotation Platform) schema inspection for AnnData files."""

import numpy as np

from ._io import open_h5ad


def _make_serializable(obj):
    """Convert numpy/pandas types to JSON-serializable Python types."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.str_, np.bytes_)):
        return str(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(v) for v in obj]
    return obj

# CAP obs column suffixes per the cell-annotation-schema spec
_REQUIRED_SUFFIXES = [
    "",  # the cell label column itself
    "--cell_fullname",
    "--cell_ontology_exists",
    "--cell_ontology_term_id",
    "--cell_ontology_term",
    "--rationale",
    "--marker_gene_evidence",
]

_OPTIONAL_SUFFIXES = [
    "--rationale_dois",
    "--canonical_marker_genes",
    "--synonyms",
    "--category_fullname",
    "--category_cell_ontology_term_id",
    "--category_cell_ontology_term",
    "--cell_ontology_assessment",
    "--confidence_score",
]

_UNS_REQUIRED_KEYS = [
    "cellannotation_schema_version",
    "cellannotation_metadata",
    "title",
]

_UNS_OPTIONAL_KEYS = [
    "publication_timestamp",
    "publication_version",
    "description",
    "cap_dataset_url",
    "cap_publication_title",
    "cap_publication_description",
    "cap_publication_url",
    "authors_list",
    "hierarchy",
]


def _find_annotation_sets(obs_columns: list[str]) -> list[str]:
    """Identify CAP annotation set names from obs columns with -- separator."""
    sets = set()
    for col in obs_columns:
        if "--" in col:
            setname = col.split("--")[0]
            sets.add(setname)
    return sorted(sets)


def _get_unique_values(series, max_values: int = 50) -> list[str]:
    """Get unique values from a series, capped at max_values."""
    uniques = series.dropna().unique().tolist()
    if len(uniques) > max_values:
        return uniques[:max_values] + [f"... and {len(uniques) - max_values} more"]
    return uniques


def get_cap_annotations(path: str, annotation_set: str | None = None) -> dict:
    """Inspect CAP (Cell Annotation Platform) annotations in an AnnData file.

    Detects CAP-formatted annotation sets, lists cell labels with their ontology
    mappings, marker genes, and rationale. Reports schema compliance.

    Args:
        path: Absolute path to an .h5ad file.
        annotation_set: Specific annotation set name to inspect. If None, lists all sets found.
    """
    try:
        with open_h5ad(path) as adata:
            obs_columns = list(adata.obs.columns)
            annotation_sets = _find_annotation_sets(obs_columns)

            uns_keys = list(adata.uns.keys())
            uns_present = [k for k in _UNS_REQUIRED_KEYS if k in uns_keys]
            uns_missing = [k for k in _UNS_REQUIRED_KEYS if k not in uns_keys]
            uns_optional_present = [k for k in _UNS_OPTIONAL_KEYS if k in uns_keys]

            has_cap = len(annotation_sets) > 0 or "cellannotation_metadata" in uns_keys

            result = {
                "has_cap_annotations": has_cap,
                "annotation_sets": annotation_sets,
                "uns_metadata": {
                    "required_present": uns_present,
                    "required_missing": uns_missing,
                    "optional_present": uns_optional_present,
                },
            }

            if not has_cap and annotation_set is None:
                return result

            if "cellannotation_metadata" in uns_keys:
                result["cellannotation_metadata"] = _make_serializable(adata.uns["cellannotation_metadata"])

            if "authors_list" in uns_keys:
                result["authors_list"] = _make_serializable(adata.uns["authors_list"])

            sets_to_inspect = []
            if annotation_set:
                if annotation_set in annotation_sets:
                    sets_to_inspect = [annotation_set]
                else:
                    return {"error": f"Annotation set '{annotation_set}' not found. Available: {annotation_sets}"}
            elif len(annotation_sets) <= 3:
                sets_to_inspect = annotation_sets

            set_details = {}
            for setname in sets_to_inspect:
                detail = {}

                required_found = []
                required_missing = []
                for suffix in _REQUIRED_SUFFIXES:
                    col = f"{setname}{suffix}" if suffix else setname
                    if col in obs_columns:
                        required_found.append(col)
                    else:
                        required_missing.append(col)

                optional_found = []
                for suffix in _OPTIONAL_SUFFIXES:
                    col = f"{setname}{suffix}"
                    if col in obs_columns:
                        optional_found.append(col)

                detail["required_columns_present"] = required_found
                detail["required_columns_missing"] = required_missing
                detail["optional_columns_present"] = optional_found

                if setname in obs_columns:
                    vc = adata.obs[setname].value_counts()
                    detail["cell_labels"] = {str(k): int(v) for k, v in vc.items()}

                ont_col = f"{setname}--cell_ontology_term_id"
                if ont_col in obs_columns:
                    detail["ontology_terms"] = _get_unique_values(adata.obs[ont_col])

                marker_col = f"{setname}--marker_gene_evidence"
                if marker_col in obs_columns:
                    detail["marker_genes"] = _get_unique_values(adata.obs[marker_col])

                rat_col = f"{setname}--rationale"
                if rat_col in obs_columns:
                    detail["rationale"] = _get_unique_values(adata.obs[rat_col])

                set_details[setname] = detail

            if set_details:
                result["set_details"] = set_details

            return result

    except Exception as e:
        return {"error": str(e)}
