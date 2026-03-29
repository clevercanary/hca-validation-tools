"""Schema-aware editing tools for HCA h5ad files."""

from __future__ import annotations

import os
import types
import typing
from datetime import datetime, timezone

from pydantic import TypeAdapter, ValidationError

from ._io import open_h5ad
from ._serialize import make_serializable
from .schema.helpers import uns_field_registry
from .write import EDIT_LOG_KEY, write_h5ad
from . import __version__


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
        Dict with 'fields' (list of field info), 'missing_required',
        'extra_uns_keys', 'obs_columns', 'obsm_keys', or 'error'.
    """
    try:
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
            schema_keys = set(registry.keys()) | {EDIT_LOG_KEY}
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
    output_dir: str | None = None,
) -> dict:
    """Set a single HCA uns field with schema validation.

    Validates the field name and value against the HCA schema, then writes
    the updated file via write_h5ad() with edit log tracking.

    Args:
        path: Path to an .h5ad file.
        field: The uns field name (e.g. 'title', 'study_pi').
        value: The value to set.
        output_dir: Directory for output file. Defaults to same as source.

    Returns:
        Dict with 'output_path', 'field', 'old_value', 'new_value' on success,
        or 'error' on failure.
    """
    try:
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
                "tool": "hca-anndata-mcp",
                "tool_version": __version__,
                "operation": "set_uns",
                "description": f"Set uns['{field}']",
                "details": {
                    "field": field,
                    "old_value": old_value,
                    "new_value": make_serializable(validated_value),
                },
            }

            result = write_h5ad(adata, path, [entry], output_dir=output_dir)

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
