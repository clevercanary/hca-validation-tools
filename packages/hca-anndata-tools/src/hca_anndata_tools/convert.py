"""Convert CellxGENE h5ad files to HCA schema format."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from ._io import open_h5ad
from ._serialize import make_serializable
from .write import generate_timestamp, write_h5ad
from . import __version__

# CellxGENE reserved uns keys — moved to cellxgene_source, not deleted
_CELLXGENE_RESERVED_UNS = ["schema_version", "schema_reference", "citation"]

# CellxGENE uns keys that need to be broadcast to obs
_UNS_TO_OBS = ["organism_ontology_term_id", "organism"]


def _slugify(text: str, max_length: int = 80) -> str:
    """Convert text to a filename-safe slug."""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug or "untitled"


def convert_cellxgene_to_hca(
    path: str,
    output_dir: str | None = None,
) -> dict:
    """Convert a CellxGENE h5ad file to HCA schema format.

    Preserves cellxgene provenance in uns['cellxgene_source'], broadcasts
    organism from uns to obs, and renames the output from the dataset title.
    Does not add missing HCA-specific fields — wranglers fill those later.

    Args:
        path: Path to a CellxGENE h5ad file.
        output_dir: Directory for the output file. Defaults to same as source.

    Returns:
        Dict with 'output_path', 'source', 'title', 'conversions' on success,
        or 'error' on failure.
    """
    try:
        with open_h5ad(path, backed=None) as adata:
            # Verify this is a cellxgene 6.0+ file (organism in uns, single species)
            if "schema_version" not in adata.uns:
                return {"error": "Not a CellxGENE file — uns['schema_version'] is missing"}

            schema_ver = str(adata.uns["schema_version"])
            major = int(schema_ver.split(".")[0]) if schema_ver[0].isdigit() else 0
            if major < 6:
                return {
                    "error": (
                        f"CellxGENE schema {schema_ver} is not supported. "
                        f"Requires 6.0+ (organism in uns, single species per dataset)."
                    )
                }

            title = adata.uns.get("title", "")
            if not title:
                return {"error": "File has no title in uns — cannot generate output filename"}

            conversions = []

            # --- 1. Preserve cellxgene provenance ---
            cellxgene_source = {}
            for key in _CELLXGENE_RESERVED_UNS:
                if key in adata.uns:
                    cellxgene_source[key] = make_serializable(adata.uns[key])
                    del adata.uns[key]

            if cellxgene_source:
                adata.uns["cellxgene_source"] = cellxgene_source
                conversions.append(
                    f"Moved cellxgene reserved keys to uns['cellxgene_source']: "
                    f"{list(cellxgene_source.keys())}"
                )

            # --- 2. Broadcast organism from uns → obs ---
            for key in _UNS_TO_OBS:
                if key in adata.uns:
                    value = adata.uns[key]
                    adata.obs[key] = pd.Categorical.from_codes(
                        np.zeros(adata.n_obs, dtype=np.int8),
                        categories=[value],
                    )
                    del adata.uns[key]
                    conversions.append(f"{key}: uns → obs (broadcast '{value}')")

            slug = _slugify(title)
            timestamp = generate_timestamp()
            out_filename = f"{slug}-{timestamp}.h5ad"
            directory = output_dir if output_dir is not None else os.path.dirname(path)
            output_path = os.path.join(directory, out_filename)

            # --- 4. Build edit log entry ---
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tool": "hca-anndata-tools",
                "tool_version": __version__,
                "operation": "import_cellxgene",
                "description": f"Imported from CellxGENE Discover: {title}",
                "details": {
                    "source_schema_version": cellxgene_source.get("schema_version"),
                    "source_citation": cellxgene_source.get("citation"),
                    "conversions": conversions,
                },
            }

            # --- 5. Write ---
            result = write_h5ad(adata, path, [entry], output_path=output_path)

        if "error" in result:
            return result

        return {
            **result,
            "source": os.path.basename(path),
            "title": title,
            "conversions": conversions,
        }

    except Exception as e:
        return {"error": str(e)}
