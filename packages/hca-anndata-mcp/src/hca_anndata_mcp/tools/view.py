"""View raw data slices from an AnnData object."""

import gc

import anndata as ad
import numpy as np
import pandas as pd

_ALLOWED_ATTRIBUTES = {"obs", "var", "X", "obsm", "varm", "obsp", "varp", "layers", "uns"}


def view_data(
    path: str,
    attribute: str = "obs",
    key: str | None = None,
    columns: list[str] | None = None,
    row_start: int = 0,
    row_end: int = 10,
    col_start: int = 0,
    col_end: int = 10,
) -> dict:
    """View a slice of data from an AnnData attribute.

    For dataframe attributes (obs, var): returns rows as records with column selection.
    For array attributes (X, layers, obsm, etc.): returns a numeric slice.
    For uns: returns the value directly (dicts, strings, arrays).

    Args:
        path: Absolute path to an .h5ad file.
        attribute: One of 'obs', 'var', 'X', 'obsm', 'varm', 'obsp', 'varp', 'layers', 'uns'.
        key: Key within the attribute. Required for obsm, varm, obsp, varp, layers. Optional for uns (omit for a summarized view).
        columns: Column names to include (for obs/var only).
        row_start: Start row index for slicing. Defaults to 0.
        row_end: End row index for slicing. Defaults to 10.
        col_start: Start column index for array slicing. Defaults to 0.
        col_end: End column index for array slicing. Defaults to 10.
    """
    adata = None
    try:
        if attribute not in _ALLOWED_ATTRIBUTES:
            return {"error": f"attribute must be one of {sorted(_ALLOWED_ATTRIBUTES)}, got '{attribute}'"}

        adata = ad.read_h5ad(path, backed="r")

        attr_obj = getattr(adata, attribute, None)
        if attr_obj is None:
            return {"error": f"Attribute '{attribute}' not found"}

        if key is not None:
            if attribute in ("obs", "var"):
                return {"error": "Use 'columns' parameter for obs/var, not 'key'"}
            try:
                attr_obj = attr_obj[key]
            except (KeyError, IndexError):
                return {"error": f"Key '{key}' not found in {attribute}"}

        if isinstance(attr_obj, pd.DataFrame):
            return _view_dataframe(attr_obj, columns, row_start, row_end)
        elif hasattr(attr_obj, "shape") and len(getattr(attr_obj, "shape", ())) >= 1:
            return _view_array(attr_obj, row_start, row_end, col_start, col_end)
        elif isinstance(attr_obj, dict):
            return _view_dict(attr_obj)
        else:
            return {"data": str(attr_obj), "type": type(attr_obj).__name__}

    except Exception as e:
        return {"error": str(e)}
    finally:
        if adata is not None:
            adata.file.close()
            del adata
            gc.collect()


def _view_dataframe(
    df: pd.DataFrame,
    columns: list[str] | None,
    row_start: int,
    row_end: int,
) -> dict:
    """View a slice of a DataFrame."""
    if columns is not None:
        missing = [c for c in columns if c not in df.columns]
        if missing:
            return {"error": f"Columns not found: {missing}"}
        df = df[columns]

    sliced = df.iloc[row_start:row_end]
    return {
        "type": "dataframe",
        "full_shape": list(df.shape),
        "slice_shape": list(sliced.shape),
        "index": [str(i) for i in sliced.index],
        "columns": list(sliced.columns),
        "data": sliced.to_dict(orient="list"),
    }


def _view_array(arr, row_start: int, row_end: int, col_start: int, col_end: int) -> dict:
    """View a slice of an array-like object."""
    shape = arr.shape
    if len(shape) == 1:
        sliced = arr[row_start:row_end]
    else:
        sliced = arr[row_start:row_end, col_start:col_end]

    if hasattr(sliced, "toarray"):
        sliced = sliced.toarray()
    if hasattr(sliced, "compute"):
        sliced = sliced.compute()
    data = np.asarray(sliced)

    return {
        "type": "array",
        "dtype": str(arr.dtype),
        "full_shape": list(shape),
        "slice_shape": list(data.shape),
        "data": data.tolist(),
    }


def _view_dict(d: dict) -> dict:
    """View a dict (uns entries), summarizing large values."""
    result = {}
    for k, v in d.items():
        if isinstance(v, (str, int, float, bool)):
            result[k] = v
        elif isinstance(v, np.ndarray):
            result[k] = f"ndarray shape={v.shape} dtype={v.dtype}"
        elif isinstance(v, dict):
            result[k] = f"dict with {len(v)} keys: {list(v.keys())[:10]}"
        elif isinstance(v, (list, tuple)):
            result[k] = f"{type(v).__name__} with {len(v)} items"
        elif isinstance(v, pd.DataFrame):
            result[k] = f"DataFrame shape={v.shape}"
        else:
            result[k] = f"{type(v).__name__}"
    return {"type": "dict", "data": result}
