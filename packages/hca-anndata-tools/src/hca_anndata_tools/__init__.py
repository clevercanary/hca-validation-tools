"""HCA AnnData Tools — inspection, summarization, and statistics for h5ad files."""

__version__ = "0.3.1"

__all__ = [
    "locate_files",
    "get_summary",
    "get_descriptive_stats",
    "view_data",
    "get_storage_info",
    "get_cap_annotations",
    "plot_embedding",
    "write_h5ad",
    "strip_timestamp",
    "generate_output_path",
    "generate_timestamp",
    "EDIT_LOG_KEY",
    "resolve_latest",
    "set_uns",
    "list_uns_fields",
    "convert_cellxgene_to_hca",
    "validate_marker_genes",
    "copy_cap_annotations",
]

_LAZY_IMPORTS = {
    "locate_files": ".files",
    "get_summary": ".summary",
    "get_descriptive_stats": ".stats",
    "view_data": ".view",
    "get_storage_info": ".storage",
    "get_cap_annotations": ".cap",
    "plot_embedding": ".plot",
    "write_h5ad": ".write",
    "strip_timestamp": ".write",
    "generate_output_path": ".write",
    "generate_timestamp": ".write",
    "EDIT_LOG_KEY": ".write",
    "resolve_latest": ".write",
    "set_uns": ".edit",
    "list_uns_fields": ".edit",
    "convert_cellxgene_to_hca": ".convert",
    "validate_marker_genes": ".marker_genes",
    "copy_cap_annotations": ".copy_cap",
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        import importlib
        module = importlib.import_module(_LAZY_IMPORTS[name], __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
