"""MCP wrapper for hca_anndata_tools.rename_cell_ids.

Thin re-export to keep parity with the other MCP tools (each gets its
own wrapper file). The underlying function in hca-anndata-tools already
returns a dict-shaped result; this module exists so future wrapper-only
behavior (e.g. path normalization, MCP-side logging) lands here without
touching the tools layer.
"""

from hca_anndata_tools import rename_cell_ids

__all__ = ["rename_cell_ids"]
