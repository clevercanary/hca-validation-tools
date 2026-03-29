"""HCA AnnData Tools — inspection, summarization, and statistics for h5ad files."""

__version__ = "0.1.0"

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
    "EDIT_LOG_KEY",
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
    "EDIT_LOG_KEY": ".write",
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        import importlib
        module = importlib.import_module(_LAZY_IMPORTS[name], __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
