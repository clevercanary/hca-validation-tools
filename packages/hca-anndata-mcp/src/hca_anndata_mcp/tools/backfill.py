"""MCP wrapper for hca_anndata_tools.backfill_obs_from_source.

Thin re-export to keep parity with the other MCP tools (each gets its
own wrapper file). The underlying function in hca-anndata-tools already
returns a dict-shaped result; this module exists so future wrapper-only
behavior (e.g. path normalization, MCP-side logging) lands here without
touching the tools layer.
"""

from hca_anndata_tools import backfill_obs_from_source

__all__ = ["backfill_obs_from_source"]
