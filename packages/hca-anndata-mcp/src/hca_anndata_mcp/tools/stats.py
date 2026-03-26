"""Descriptive statistics and value counts for AnnData attributes."""

import gc

import anndata as ad
import numpy as np
import pandas as pd


def get_descriptive_stats(
    path: str,
    attribute: str = "obs",
    columns: list[str] | None = None,
    value_counts: bool = False,
    filter_column: str | None = None,
    filter_operator: str | None = None,
    filter_value: str | float | bool | list | None = None,
) -> dict:
    """Get descriptive statistics for columns of an AnnData attribute.

    For numeric columns: count, mean, std, min, 25%, 50%, 75%, max.
    For categorical columns: count, unique, top, freq.
    Optionally returns full value_counts for categorical columns.

    Args:
        path: Absolute path to an .h5ad file.
        attribute: One of 'obs', 'var'. Defaults to 'obs'.
        columns: Column names to describe. If None, describes all columns.
        value_counts: If True, include full value counts for categorical columns.
        filter_column: Column name to filter rows by before computing stats.
        filter_operator: Operator for filtering. One of '==', '!=', '>', '>=', '<', '<=', 'isin', 'notin'.
        filter_value: Value(s) to filter by. Use a list for 'isin'/'notin'.
    """
    adata = None
    try:
        if attribute not in ("obs", "var"):
            return {"error": f"attribute must be 'obs' or 'var', got '{attribute}'"}

        adata = ad.read_h5ad(path, backed="r")
        df: pd.DataFrame = getattr(adata, attribute)

        # Apply filter
        filter_params = [filter_column, filter_operator, filter_value]
        if any(p is not None for p in filter_params) and not all(p is not None for p in filter_params):
            return {"error": "filter_column, filter_operator, and filter_value must all be provided together"}
        if filter_column is not None:
            if filter_column not in df.columns:
                return {"error": f"Filter column '{filter_column}' not found in {attribute}"}
            df = _apply_filter(df, filter_column, filter_operator, filter_value)
            if len(df) == 0:
                return {"error": "Filter resulted in zero rows"}

        # Select columns
        if columns is not None:
            missing = [c for c in columns if c not in df.columns]
            if missing:
                return {"error": f"Columns not found in {attribute}: {missing}"}
            df = df[columns]

        result = {"n_rows": len(df), "columns": {}}

        for col in df.columns:
            series = df[col]
            if pd.api.types.is_numeric_dtype(series.dtype) and not pd.api.types.is_bool_dtype(series.dtype):
                desc = series.describe()
                result["columns"][col] = {
                    "dtype": str(series.dtype),
                    "type": "numeric",
                    "count": int(desc["count"]),
                    "mean": _safe_float(desc["mean"]),
                    "std": _safe_float(desc["std"]),
                    "min": _safe_float(desc["min"]),
                    "25%": _safe_float(desc["25%"]),
                    "50%": _safe_float(desc["50%"]),
                    "75%": _safe_float(desc["75%"]),
                    "max": _safe_float(desc["max"]),
                    "n_nan": int(series.isna().sum()),
                }
            else:
                col_info = {
                    "dtype": str(series.dtype),
                    "type": "categorical",
                    "count": int(series.count()),
                    "unique": int(series.nunique()),
                    "n_nan": int(series.isna().sum()),
                }
                vc = series.value_counts(dropna=True)
                if len(vc) > 0:
                    col_info["top"] = str(vc.index[0])
                    col_info["freq"] = int(vc.iloc[0])
                if value_counts:
                    col_info["value_counts"] = {
                        str(k): int(v) for k, v in vc.items()
                    }
                result["columns"][col] = col_info

        return result
    except Exception as e:
        return {"error": str(e)}
    finally:
        if adata is not None:
            adata.file.close()
            del adata
            gc.collect()


def _safe_float(val) -> float | None:
    """Convert to float, returning None for NaN/inf."""
    f = float(val)
    if np.isnan(f) or np.isinf(f):
        return None
    return f


def _apply_filter(
    df: pd.DataFrame,
    column: str,
    operator: str,
    value,
) -> pd.DataFrame:
    """Apply a filter to a DataFrame."""
    series = df[column]
    ops = {
        "==": lambda s, v: s == v,
        "!=": lambda s, v: s != v,
        ">": lambda s, v: s > float(v),
        ">=": lambda s, v: s >= float(v),
        "<": lambda s, v: s < float(v),
        "<=": lambda s, v: s <= float(v),
        "isin": lambda s, v: s.isin(v if isinstance(v, list) else [v]),
        "notin": lambda s, v: ~s.isin(v if isinstance(v, list) else [v]),
    }
    if operator not in ops:
        raise ValueError(f"Unknown operator: {operator}")
    mask = ops[operator](series, value)
    return df[mask]
