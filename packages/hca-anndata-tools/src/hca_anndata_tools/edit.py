"""Schema-aware editing tools for HCA h5ad files."""

from __future__ import annotations

import os
import shutil
import types
import typing
from datetime import datetime, timezone

import h5py
import numpy as np
from pydantic import TypeAdapter, ValidationError

from ._io import open_h5ad, read_edit_log_h5py, verify_categorical_integrity, write_edit_log_h5py, _decode_bytes
from ._serialize import make_serializable
from .schema.helpers import uns_field_registry
from .write import (
    build_edit_log,
    cleanup_previous_version,
    generate_output_path,
    resolve_latest,
    write_h5ad,
    _compute_sha256,
)
from . import __version__

# Default HCA placeholder values (case-insensitive)
_DEFAULT_PLACEHOLDERS = [
    "unknown", "na", "n/a", "none", "not available",
    "not applicable", "tbd", "todo", "null", "undefined",
]


def _type_display(annotation) -> str:
    """Human-readable string for a type annotation."""
    origin = getattr(annotation, "__origin__", None)
    args = getattr(annotation, "__args__", ())
    if origin is list:
        inner = args[0].__name__ if args else "?"
        return f"list[{inner}]"
    # Optional[X] shows as Union[X, None] or X | None (types.UnionType on 3.10+)
    if (origin is typing.Union or isinstance(annotation, types.UnionType)) and type(None) in args:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _type_display(non_none[0])
    if hasattr(annotation, "__name__"):
        return annotation.__name__
    return str(annotation)


def list_uns_fields(path: str) -> dict:
    """List all HCA uns fields with current values and schema metadata.

    Args:
        path: Path to an .h5ad file.

    Returns:
        Dict with 'filename', 'fields' (list of field info), 'set_count',
        'missing_required', 'missing_required_bionetwork', 'extra_uns_keys',
        'obs_columns', 'obsm_keys', or 'error'.
    """
    try:
        path = resolve_latest(path)
        registry = uns_field_registry()

        with open_h5ad(path, backed="r") as adata:
            fields = []
            missing_required = []
            missing_required_bionetwork = []

            for name, info in registry.items():
                current = adata.uns.get(name, None)
                is_set = name in adata.uns
                serialized = make_serializable(current) if is_set else None

                fields.append({
                    "name": name,
                    "title": info.title,
                    "description": info.description,
                    "type": _type_display(info.annotation),
                    "required": info.required,
                    "bionetwork_only": info.bionetwork_only,
                    "current_value": serialized,
                    "is_set": is_set,
                    "examples": info.examples,
                })

                if info.required and not is_set:
                    if info.bionetwork_only:
                        missing_required_bionetwork.append(name)
                    else:
                        missing_required.append(name)

            # Extra uns keys not in the HCA schema
            schema_keys = set(registry.keys()) | {"provenance"}
            extra_uns_keys = sorted(k for k in adata.uns.keys() if k not in schema_keys)

            return {
                "filename": os.path.basename(path),
                "fields": fields,
                "set_count": sum(1 for f in fields if f["is_set"]),
                "missing_required": missing_required,
                "missing_required_bionetwork": missing_required_bionetwork,
                "extra_uns_keys": extra_uns_keys,
                "obs_columns": list(adata.obs.columns),
                "obsm_keys": list(adata.obsm.keys()),
            }

    except Exception as e:
        return {"error": str(e)}


def set_uns(
    path: str,
    field: str,
    value: str | list[str],
) -> dict:
    """Set a single HCA uns field with schema validation.

    Validates the field name and value against the HCA schema, then writes
    the updated file via write_h5ad() with edit log tracking. Output is
    written to the same directory as the input file.

    Args:
        path: Path to an .h5ad file.
        field: The uns field name (e.g. 'title', 'study_pi').
        value: The value to set.

    Returns:
        Dict with 'output_path', 'editing', 'wrote', 'field', 'old_value',
        'new_value' on success, or 'error' on failure.
    """
    try:
        path = resolve_latest(path)
        registry = uns_field_registry()

        # Validate field name
        if field not in registry:
            valid = sorted(registry.keys())
            return {"error": f"'{field}' is not a recognized HCA uns field. Valid fields: {valid}"}

        info = registry[field]

        # Validate value type via Pydantic
        try:
            adapter = TypeAdapter(info.annotation)
            validated_value = adapter.validate_python(value)
        except ValidationError as e:
            return {"error": f"Invalid value for '{field}': {e}"}

        # Reject empty values for required fields
        if info.required:
            if isinstance(validated_value, str) and not validated_value.strip():
                return {"error": f"Invalid value for '{field}': must be non-empty"}
            if isinstance(validated_value, list):
                if not validated_value:
                    return {"error": f"Invalid value for '{field}': list must be non-empty"}
                bad = [v for v in validated_value if isinstance(v, str) and not v.strip()]
                if bad:
                    return {"error": f"Invalid value for '{field}': list elements must be non-empty"}

        # Open file in memory for editing
        with open_h5ad(path, backed=None) as adata:
            # Cross-validation for specific fields
            if field == "batch_condition" and validated_value is not None:
                obs_cols = set(adata.obs.columns)
                invalid = [v for v in validated_value if v not in obs_cols]
                if invalid:
                    return {
                        "error": (
                            f"batch_condition values {invalid} are not obs columns. "
                            f"Valid columns: {sorted(obs_cols)}"
                        )
                    }

            if field == "default_embedding" and validated_value is not None:
                obsm_keys = set(adata.obsm.keys())
                if validated_value not in obsm_keys:
                    return {
                        "error": (
                            f"default_embedding '{validated_value}' is not an obsm key. "
                            f"Valid keys: {sorted(obsm_keys)}"
                        )
                    }

            # Record previous value
            old_value = make_serializable(adata.uns.get(field, None))

            # Set the value
            adata.uns[field] = validated_value

            # Build edit log entry
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tool": "hca-anndata-tools",
                "tool_version": __version__,
                "operation": "set_uns",
                "description": f"Set uns['{field}']",
                "details": {
                    "field": field,
                    "old_value": old_value,
                    "new_value": make_serializable(validated_value),
                },
            }

            result = write_h5ad(adata, path, [entry])

        if "error" in result:
            return result

        return {
            **result,
            "editing": os.path.basename(path),
            "wrote": os.path.basename(result["output_path"]),
            "field": field,
            "old_value": old_value,
            "new_value": make_serializable(validated_value),
        }

    except Exception as e:
        return {"error": str(e)}


def replace_placeholder_values(
    path: str,
    columns: list[str],
    placeholders: list[str] | None = None,
) -> dict:
    """Replace placeholder values with NaN in categorical obs columns.

    Uses direct h5py modification on a copy — does not load the expression
    matrix into memory. Sets codes to -1 for any value matching the
    placeholders (case-insensitive). Removes unused categories after
    replacement. Only categorical columns are supported.

    Args:
        path: Path to an .h5ad file.
        columns: Obs columns to fix.
        placeholders: Values to replace. Defaults to the HCA placeholder list.

    Returns:
        Dict with 'output_path', 'columns_fixed', 'total_cells_affected'
        on success, or 'error' on failure.
    """
    output_path = None
    try:
        path = resolve_latest(path)
        if not columns:
            return {"error": "columns must not be empty"}

        bl = {v.lower() for v in (placeholders or _DEFAULT_PLACEHOLDERS)}

        # Scan for placeholder values and read edit log in one pass
        columns_fixed = {}
        expected_valid_counts = {}
        with h5py.File(path, "r") as f:
            obs = f["obs"]
            obs_col_names = [_decode_bytes(c) for c in obs.attrs["column-order"]]
            for col in columns:
                if col not in obs_col_names:
                    return {"error": f"Column '{col}' not found in obs"}
                item = obs[col]
                if isinstance(item, h5py.Group) and "categories" in item:
                    cats = [_decode_bytes(v) for v in item["categories"][:]]
                    codes = item["codes"][:]
                    placeholder_count = 0
                    matches = {}
                    for i in range(len(cats)):
                        if cats[i].lower() in bl:
                            count = int((codes == i).sum())
                            if count > 0:
                                matches[cats[i]] = count
                                placeholder_count += count
                    if matches:
                        columns_fixed[col] = matches
                        valid_count = int((codes >= 0).sum()) - placeholder_count
                        expected_valid_counts[col] = valid_count
                else:
                    return {"error": f"Column '{col}' is not categorical"}
            raw_log = read_edit_log_h5py(f)

        if not columns_fixed:
            return {"error": "No placeholder values found in the specified columns"}

        total_affected = sum(sum(v.values()) for v in columns_fixed.values())

        target_sha256 = _compute_sha256(path)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool": "hca-anndata-tools",
            "tool_version": __version__,
            "operation": "replace_placeholder_values",
            "description": f"Replaced placeholder values with NaN in {len(columns_fixed)} columns",
            "details": {
                "columns_fixed": {col: dict(vals) for col, vals in columns_fixed.items()},
                "total_cells_affected": total_affected,
            },
        }

        log_result = build_edit_log(raw_log, [entry], path, target_sha256)
        if "error" in log_result:
            return log_result

        # Copy and patch
        output_path = generate_output_path(path)
        shutil.copy2(path, output_path)

        with h5py.File(output_path, "a") as f:
            for col in columns_fixed:
                item = f["obs"][col]
                cats = [_decode_bytes(v) for v in item["categories"][:]]
                codes = item["codes"][:]

                # Preserve original settings
                encoding_type = item.attrs["encoding-type"]
                encoding_version = item.attrs["encoding-version"]
                ordered = bool(item.attrs["ordered"])
                codes_compression = item["codes"].compression
                codes_compression_opts = item["codes"].compression_opts
                codes_chunks = item["codes"].chunks

                # Set blocked codes to -1 (NaN)
                blocked = {i for i in range(len(cats)) if cats[i].lower() in bl}
                for i in blocked:
                    codes[codes == i] = -1

                # Remove unused categories and remap codes
                used = sorted(set(codes[codes >= 0]))
                new_cats = [cats[i] for i in used]
                # Vectorized remap via lookup table
                lookup = np.full(len(cats), -1, dtype=codes.dtype)
                for new_idx, old_idx in enumerate(used):
                    lookup[old_idx] = new_idx
                mask = codes >= 0
                new_codes = np.full_like(codes, -1)
                new_codes[mask] = lookup[codes[mask]]

                # Rewrite the column preserving compression settings
                del f["obs"][col]
                grp = f["obs"].create_group(col)
                grp.attrs["encoding-type"] = encoding_type
                grp.attrs["encoding-version"] = encoding_version
                grp.attrs["ordered"] = ordered
                cat_data = np.array(new_cats, dtype=object) if new_cats else np.array([], dtype=h5py.string_dtype())
                grp.create_dataset("categories", data=cat_data)
                grp.create_dataset(
                    "codes", data=new_codes.astype(codes.dtype),
                    compression=codes_compression,
                    compression_opts=codes_compression_opts,
                    chunks=codes_chunks,
                )

            write_edit_log_h5py(f, log_result["json"])

            # Verify integrity after rewrite
            integrity_err = verify_categorical_integrity(
                f, list(columns_fixed.keys()), expected_valid_counts
            )
            if integrity_err:
                raise RuntimeError(integrity_err)

        cleanup_previous_version(path, output_path)

        return {
            "output_path": output_path,
            "columns_fixed": {col: dict(vals) for col, vals in columns_fixed.items()},
            "total_cells_affected": total_affected,
        }

    except Exception as e:
        if output_path and os.path.isfile(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
        return {"error": str(e)}
