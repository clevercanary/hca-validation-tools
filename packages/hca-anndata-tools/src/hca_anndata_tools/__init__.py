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
]

_LAZY_IMPORTS = {
    "locate_files": ".files",
    "get_summary": ".summary",
    "get_descriptive_stats": ".stats",
    "view_data": ".view",
    "get_storage_info": ".storage",
    "get_cap_annotations": ".cap",
    "plot_embedding": ".plot",
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        import importlib
        module = importlib.import_module(_LAZY_IMPORTS[name], __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
