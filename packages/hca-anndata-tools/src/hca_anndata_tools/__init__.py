"""HCA AnnData Tools — inspection, summarization, and statistics for h5ad files."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cap import get_cap_annotations
    from .compress import compress_h5ad
    from .convert import convert_cellxgene_to_hca
    from .copy_cap import copy_cap_annotations
    from .edit import (
        list_uns_fields,
        replace_placeholder_values,
        set_uns,
        view_edit_log,
    )
    from .files import locate_files
    from .inspect import inspect_x
    from .marker_genes import validate_marker_genes
    from .normalize import normalize_raw
    from .plot import plot_embedding
    from .stats import get_descriptive_stats
    from .storage import get_storage_info
    from .summary import get_summary
    from .view import view_data
    from .write import (
        EDIT_LOG_KEY,
        generate_output_path,
        generate_timestamp,
        resolve_latest,
        strip_timestamp,
        write_h5ad,
    )

__version__ = "0.3.1"

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
    "replace_placeholder_values": ".edit",
    "view_edit_log": ".edit",
    "convert_cellxgene_to_hca": ".convert",
    "validate_marker_genes": ".marker_genes",
    "copy_cap_annotations": ".copy_cap",
    "compress_h5ad": ".compress",
    "normalize_raw": ".normalize",
    "inspect_x": ".inspect",
}

__all__ = list(_LAZY_IMPORTS)  # pyright: ignore[reportUnsupportedDunderAll]


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        import importlib
        module = importlib.import_module(_LAZY_IMPORTS[name], __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
