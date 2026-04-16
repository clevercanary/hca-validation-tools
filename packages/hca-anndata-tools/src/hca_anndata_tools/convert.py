"""Convert CellxGENE h5ad files to HCA schema format."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from datetime import datetime, timezone

import anndata as ad
import h5py
import numpy as np
import pandas as pd

from . import __version__
from ._io import ensure_provenance_group, open_h5ad, read_obs_index, transplant_obs_columns, verify_obs_transplant
from ._serialize import make_serializable
from .write import (
    EDIT_LOG_KEY,
    build_edit_log,
    generate_timestamp,
)

# CellxGENE reserved uns keys — moved to provenance/cellxgene
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

    Uses a hybrid anndata + h5py approach: reads uns via AnnData
    (backed mode), writes a temp file via anndata for correct encoding,
    then copies the source and transplants new data via h5py.copy().
    Avoids loading the expression matrix into memory.

    Preserves cellxgene provenance in uns['provenance']['cellxgene'], broadcasts
    organism from uns to obs, and renames the output from the dataset title.

    Args:
        path: Path to a CellxGENE h5ad file.
        output_dir: Directory for the output file. Defaults to same as source.

    Returns:
        Dict with 'output_path', 'source', 'title', 'conversions' on success,
        or 'error' on failure.
    """
    output_path = None
    try:
        # --- Step 1: Read uns via anndata backed mode ---
        with open_h5ad(path) as adata:
            if "schema_version" not in adata.uns:
                return {"error": "Not a CellxGENE file — uns['schema_version'] is missing"}

            schema_ver = str(adata.uns["schema_version"]).strip()
            if not schema_ver:
                return {"error": "uns['schema_version'] is empty — cannot determine CellxGENE schema version"}
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

            # Snapshot uns values we need
            cellxgene_source = {}
            for key in _CELLXGENE_RESERVED_UNS:
                if key in adata.uns:
                    cellxgene_source[key] = make_serializable(adata.uns[key])

            uns_to_broadcast = {}
            for key in _UNS_TO_OBS:
                if key in adata.uns:
                    uns_to_broadcast[key] = make_serializable(adata.uns[key])

        # --- Step 2: Read cell index and count via h5py ---
        source_index = read_obs_index(path)
        n_obs = len(source_index)

        # --- Step 3: Build temp AnnData ---
        conversions = []

        if cellxgene_source:
            conversions.append(
                f"Moved cellxgene reserved keys to uns['provenance']['cellxgene']: "
                f"{list(cellxgene_source.keys())}"
            )

        # Broadcast obs columns (categorical, 1 category, all codes=0)
        obs_data = {}
        for key in _UNS_TO_OBS:
            if key in uns_to_broadcast:
                value = uns_to_broadcast[key]
                obs_data[key] = pd.Categorical.from_codes(
                    np.zeros(n_obs, dtype=np.int8),
                    categories=[value],
                )
                conversions.append(f"{key}: uns → obs (broadcast '{value}')")

        obs = pd.DataFrame(obs_data, index=source_index)

        # Build uns for temp file
        temp_uns = {}
        if cellxgene_source:
            temp_uns["provenance"] = {"cellxgene": cellxgene_source}

        # Build edit log
        slug = _slugify(title)
        timestamp = generate_timestamp()
        out_filename = f"{slug}-edit-{timestamp}.h5ad"
        directory = output_dir if output_dir is not None else os.path.dirname(path)
        output_path = os.path.join(directory, out_filename)

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

        log_result = build_edit_log("[]", [entry], path)
        if "error" in log_result:
            return log_result

        temp_uns.setdefault("provenance", {})[EDIT_LOG_KEY] = log_result["json"]

        temp_adata = ad.AnnData(
            X=np.empty((n_obs, 0), dtype=np.float32),
            obs=obs,
            uns=temp_uns,
        )

        # --- Step 4: Copy source + transplant via h5py ---
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = os.path.join(tmpdir, "convert_temp.h5ad")
            temp_adata.write_h5ad(temp_path)
            del temp_adata

            shutil.copy2(path, output_path)

            with h5py.File(temp_path, "r") as f_temp, \
                 h5py.File(output_path, "a") as f_out:

                f_out.require_group("uns")

                # Delete CellxGENE reserved keys from uns
                for key in _CELLXGENE_RESERVED_UNS:
                    if key in f_out["uns"]:
                        del f_out["uns"][key]

                # Delete organism keys from uns (now in obs)
                for key in _UNS_TO_OBS:
                    if key in f_out["uns"]:
                        del f_out["uns"][key]

                prov_out = ensure_provenance_group(f_out)

                # Transplant provenance/cellxgene from temp (merge, don't replace whole group)
                if "provenance" in f_temp["uns"] and "cellxgene" in f_temp["uns"]["provenance"]:
                    if "cellxgene" in prov_out:
                        del prov_out["cellxgene"]
                    f_temp.copy("uns/provenance/cellxgene", prov_out, "cellxgene")

                obs_cols_added = list(obs_data.keys())
                transplant_obs_columns(f_temp, f_out, obs_cols_added, overwrite=True)

                # Transplant edit_history into provenance
                if EDIT_LOG_KEY in prov_out:
                    del prov_out[EDIT_LOG_KEY]
                if "provenance" in f_temp["uns"] and EDIT_LOG_KEY in f_temp["uns"]["provenance"]:
                    f_temp.copy(f"uns/provenance/{EDIT_LOG_KEY}", prov_out, EDIT_LOG_KEY)

            # --- Step 5: Verify transplant ---
            verify_err = verify_obs_transplant(temp_path, output_path, obs_cols_added)
            if verify_err:
                os.remove(output_path)
                return {"error": verify_err}

        return {
            "output_path": output_path,
            "source": os.path.basename(path),
            "title": title,
            "conversions": conversions,
        }

    except Exception as e:
        if output_path and os.path.isfile(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
        return {"error": str(e)}
