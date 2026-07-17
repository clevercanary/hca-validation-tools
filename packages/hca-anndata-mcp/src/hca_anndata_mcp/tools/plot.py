"""MCP wrapper for plot_embedding that returns ImageContent."""

import functools

from mcp.types import ImageContent

from hca_anndata_tools.plot import plot_embedding as _plot_embedding


@functools.wraps(_plot_embedding, updated=[])
def plot_embedding_mcp(*args, **kwargs) -> ImageContent | dict:
    result = _plot_embedding(*args, **kwargs)
    if "error" in result:
        return result
    return ImageContent(type="image", data=result["data"], mimeType=result["mime_type"])
