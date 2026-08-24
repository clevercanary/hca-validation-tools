"""MCP wrapper for hca_anndata_tools.set_producer_uns.

Thin re-export to keep parity with the other MCP tools (each gets its
own wrapper file). The underlying function already returns a dict-shaped
result; this module exists so future wrapper-only behavior lands here
without touching the tools layer.
"""

from hca_anndata_tools import set_producer_uns

__all__ = ["set_producer_uns"]
