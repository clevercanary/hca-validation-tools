"""MCP wrapper for plot_embedding that returns ImageContent."""

import functools

from mcp.types import ImageContent

from hca_anndata_tools.plot import plot_embedding as _plot_embedding


# Not __module__ or __qualname__: a read worker finds this function by its own.
@functools.wraps(_plot_embedding, assigned=("__name__", "__doc__", "__annotations__"), updated=[])
def plot_embedding_mcp(*args, **kwargs) -> ImageContent | dict:
    result = _plot_embedding(*args, **kwargs)
    if "error" in result:
        return result
    return ImageContent(type="image", data=result["data"], mimeType=result["mime_type"])
