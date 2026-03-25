"""Summary overview of an AnnData object."""

import gc

import anndata as ad


def _dtype_str(arr) -> str:
    """Get dtype string from an array-like, or 'unknown'."""
    return str(getattr(arr, "dtype", "unknown"))


def _shape_str(arr) -> str:
    """Get shape string from an array-like, or 'N/A'."""
    shape = getattr(arr, "shape", None)
    return str(shape) if shape is not None else "N/A"


def _type_name(obj) -> str:
    """Get the qualified type name of an object."""
    t = type(obj)
    module = getattr(t, "__module__", "")
    name = getattr(t, "__qualname__", t.__name__)
    if module and module != "builtins":
        return f"{module}.{name}"
    return name


def get_summary(path: str) -> dict:
    """Get a structural summary of an AnnData file (.h5ad or .zarr).

    Returns cell/gene counts, obs/var column names and dtypes, obsm/varm/obsp/varp keys,
    layers, uns keys, and whether raw data is present.

    Args:
        path: Absolute path to an .h5ad or .zarr file.
    """
    adata = None
    try:
        adata = ad.read_h5ad(path, backed="r")

        result = {
            "n_obs": adata.n_obs,
            "n_vars": adata.n_vars,
            "X": {
                "type": _type_name(adata.X),
                "dtype": _dtype_str(adata.X),
                "shape": _shape_str(adata.X),
            } if adata.X is not None else None,
            "obs_columns": [
                {"name": col, "dtype": str(adata.obs[col].dtype)}
                for col in adata.obs.columns
            ],
            "var_columns": [
                {"name": col, "dtype": str(adata.var[col].dtype)}
                for col in adata.var.columns
            ],
            "obsm_keys": [
                {"key": k, "type": _type_name(adata.obsm[k]), "shape": _shape_str(adata.obsm[k])}
                for k in adata.obsm.keys()
            ],
            "varm_keys": [
                {"key": k, "type": _type_name(adata.varm[k]), "shape": _shape_str(adata.varm[k])}
                for k in adata.varm.keys()
            ],
            "obsp_keys": [
                {"key": k, "type": _type_name(adata.obsp[k])}
                for k in adata.obsp.keys()
            ],
            "varp_keys": [
                {"key": k, "type": _type_name(adata.varp[k])}
                for k in adata.varp.keys()
            ],
            "layers": [
                {"name": k, "type": _type_name(adata.layers[k]), "dtype": _dtype_str(adata.layers[k])}
                for k in adata.layers.keys()
            ],
            "uns_keys": list(adata.uns.keys()),
            "has_raw": adata.raw is not None,
        }
        return result
    except Exception as e:
        return {"error": str(e)}
    finally:
        if adata is not None:
            adata.file.close()
            del adata
            gc.collect()
