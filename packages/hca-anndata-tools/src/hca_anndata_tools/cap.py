"""CAP (Cell Annotation Platform) schema inspection for AnnData files."""

from collections.abc import Mapping

from ._io import open_h5ad
from ._serialize import make_serializable as _make_serializable
from .write import resolve_latest

# Canonical home for the CAP metadata block (issue #452).
CAP_METADATA_KEY = "cap_metadata"

# CAP uns keys the inspector reports on. `title` is the dataset title (it lives
# at the top level of uns); the other keys constitute the CAP metadata block.
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

# Deprecated top-level CAP keys. Their presence signals the old layout — even
# alongside a nested cap_metadata block (a mixed-layout file) — which is refused
# rather than normalized (issue #452).
_LEGACY_CAP_MARKERS = ("cellannotation_metadata", "cellannotation_schema_version")

# Rendered from the marker tuple rather than retyped, so the keys a message
# names stay the keys the predicate detects. Subject-free and remedy-free on
# purpose: each refusal site supplies its own, and they differ — copy_cap tells
# the caller to re-export, drop_obs_columns deliberately points nowhere.
LEGACY_LAYOUT_DESCRIPTION = "the deprecated top-level CAP layout ({})".format(
    " / ".join(f"uns[{k!r}]" for k in _LEGACY_CAP_MARKERS)
)

LEGACY_LAYOUT_ERROR = (
    f"Source uses {LEGACY_LAYOUT_DESCRIPTION}. "
    "Only the nested uns['cap_metadata'] layout is accepted; re-export the CAP "
    "file with its metadata nested under uns['cap_metadata']."
)


def is_legacy_cap_layout(uns) -> bool:
    """True if the file carries any deprecated top-level CAP key.

    Accepts None (a file with no uns is not legacy-layout), so callers can
    pass ``read_uns``'s result without their own guard.

    Fires even when a nested ``cap_metadata`` block is also present (a
    mixed-layout file): the strict clean-break contract refuses anything
    carrying deprecated top-level keys rather than silently letting the nested
    block win.
    """
    if uns is None:
        return False
    return any(k in uns for k in _LEGACY_CAP_MARKERS)


def resolve_cap_block(uns) -> dict | None:
    """Return the nested ``uns['cap_metadata']`` block as a dict, or None.

    Only the canonical nested layout is accepted (issue #452) — the deprecated
    top-level layout is *not* normalized. Callers detect it with
    :func:`is_legacy_cap_layout` and refuse. A present-but-non-Mapping
    ``cap_metadata`` is treated as absent.
    """
    block = uns.get(CAP_METADATA_KEY)
    return dict(block) if isinstance(block, Mapping) else None


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
    "--category_cell_ontology_exists",
    "--category_cell_ontology_term_id",
    "--category_cell_ontology_term",
    "--cell_ontology_assessment",
    "--confidence_score",
]


def is_cap_declared(uns) -> bool:
    """True if the file declares CAP annotation sets the canonical way.

    The declaration is what makes a ``--`` column part of a set rather than a
    producer column that happens to contain the separator.
    """
    return CAP_METADATA_KEY in uns


def cap_palette_keys(uns_keys) -> list[str]:
    """CAP-shaped palette keys: ``<name>_colors`` whose base name is a CAP
    ``--`` column.

    Both those paired with a present column and those already orphaned by an
    earlier era's overwrite, which deleted columns but left palettes.
    """
    return [k for k in uns_keys if k.endswith("_colors") and cap_obs_columns([k.removesuffix("_colors")])]


def cap_obs_columns(obs_columns: list[str]) -> list[str]:
    """Return the subset of obs column names that are CAP annotation columns.

    CAP serializes annotation columns as ``<set>--<suffix>``; the ``--``
    separator is the convention. Owned here so the tools that detect,
    replace, or remove CAP columns all share one definition.
    """
    return [c for c in obs_columns if "--" in c]


# The full known CAP suffix vocabulary (maintained here, never supplied by
# callers). A '--' column outside it is still CAP material — but it means CAP
# grew a field this list hasn't learned yet, which tools surface as a warning.
_ALL_CAP_SUFFIXES: tuple[str, ...] = tuple(s for s in (*_REQUIRED_SUFFIXES, *_OPTIONAL_SUFFIXES) if s)


def unknown_cap_suffix_columns(obs_columns: list[str]) -> list[str]:
    """Return the ``--`` columns whose suffix is not in the known vocabulary.

    These are removed/handled as CAP material like any other ``--`` column;
    the point of flagging them is maintenance — a new CAP schema field should
    be added to the suffix lists above. The suffix is everything after the
    FIRST separator, matching :func:`_find_annotation_sets`' parse — so
    ``set--new_field--cell_fullname`` is flagged (unknown suffix
    ``new_field--cell_fullname``), not mistaken for a known one.
    """
    known = {s.removeprefix("--") for s in _ALL_CAP_SUFFIXES}
    return [c for c in cap_obs_columns(obs_columns) if c.split("--", 1)[1] not in known]


def _find_annotation_sets(obs_columns: list[str]) -> list[str]:
    """Identify CAP annotation set names from obs columns with -- separator."""
    return sorted({col.split("--")[0] for col in cap_obs_columns(obs_columns)})


def _get_unique_values(series, max_values: int = 50) -> list:
    """Get unique values from a series, capped at max_values."""
    uniques = [_make_serializable(v) for v in series.dropna().unique().tolist()]
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
        path = resolve_latest(path)
        with open_h5ad(path) as adata:
            obs_columns = list(adata.obs.columns)

            # Only the nested uns['cap_metadata'] layout is accepted. Any
            # deprecated top-level marker — even alongside a nested block (a
            # mixed-layout file) — is surfaced via `layout` as a diagnostic and
            # is not treated as valid CAP (has_cap_annotations stays False).
            if is_legacy_cap_layout(adata.uns):
                layout = "legacy_toplevel"
                cap = {}
            else:
                cap = resolve_cap_block(adata.uns)
                layout = "cap_metadata" if cap is not None else None
                cap = cap or {}

            # Annotation sets are defined in cellannotation_metadata
            meta = cap.get("cellannotation_metadata", {})
            annotation_sets = sorted(meta.keys()) if isinstance(meta, dict) else []

            # CAP schema keys live in the block; `title` stays top-level.
            present = set(cap) | ({"title"} if "title" in adata.uns else set())
            uns_present = [k for k in _UNS_REQUIRED_KEYS if k in present]
            uns_missing = [k for k in _UNS_REQUIRED_KEYS if k not in present]
            uns_optional_present = [k for k in _UNS_OPTIONAL_KEYS if k in cap]

            has_cap = "cellannotation_metadata" in cap and len(annotation_sets) > 0

            result = {
                "has_cap_annotations": has_cap,
                "layout": layout,
                "annotation_sets": annotation_sets,
                "uns_metadata": {
                    "required_present": uns_present,
                    "required_missing": uns_missing,
                    "optional_present": uns_optional_present,
                },
            }

            if not has_cap and annotation_set is None:
                return result

            if "cellannotation_metadata" in cap:
                result["cellannotation_metadata"] = _make_serializable(cap["cellannotation_metadata"])

            if "authors_list" in cap:
                result["authors_list"] = _make_serializable(cap["authors_list"])

            sets_to_inspect = []
            if annotation_set:
                if annotation_set in annotation_sets:
                    sets_to_inspect = [annotation_set]
                else:
                    return {"error": f"Annotation set '{annotation_set}' not found. Available: {annotation_sets}"}
            else:
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
