"""
HCA Validation Tools - Main Validator Module

This module provides the main validation functionality for HCA data using Pydantic models.
"""

import itertools
from typing import Any, get_args

import hca_metadata_schema.generated.core as schema
import pandas as pd
from linkml_runtime import SchemaView
from pydantic import ValidationError
from pydantic_core import ErrorDetails, InitErrorDetails, PydanticCustomError
from pydantic_core.core_schema import ErrorType

from hca_validation.schema_utils.schema_utils import (
    get_class_entity_type,
    get_class_foreign_keys,
    get_class_identifier_name,
)


def validate(
    data: dict[str, Any], *, class_name: str, entry_sheet_optional: frozenset[str] = frozenset()
) -> ValidationError | None:
    """Validate an entry-sheet row against the Pydantic class `class_name`; return the ValidationError, or None.

    `entry_sheet_optional` names slots that may be blank or absent (#850, from `get_entry_sheet_optional_slots`): a
    blank value is treated as absent, and only the resulting `missing` error is dropped, so a present but invalid
    value still fails.

    An unknown `class_name` raises AttributeError."""

    model = getattr(schema, class_name)
    data = {key: value for key, value in data.items() if not (key in entry_sheet_optional and value is None)}
    try:
        model.model_validate(data)
        return None
    except ValidationError as e:
        errors = e.errors()
        kept = [err for err in errors if not (err["type"] == "missing" and _is_top_level(err, entry_sheet_optional))]
        if len(kept) == len(errors):
            return e
        if not kept:
            return None
        return ValidationError.from_exception_data(title=e.title, line_errors=[_line_error(err) for err in kept])


def _is_top_level(error: ErrorDetails, slots: frozenset[str]) -> bool:
    return len(error["loc"]) == 1 and error["loc"][0] in slots


_BUILT_IN_ERROR_TYPES = frozenset(get_args(ErrorType))


def _line_error(error: ErrorDetails) -> InitErrorDetails:
    """Rebuild an `errors()` entry as InitErrorDetails, keeping type and context so its message is unchanged."""
    if error["type"] in _BUILT_IN_ERROR_TYPES:
        details: InitErrorDetails = {"type": error["type"], "loc": error["loc"], "input": error["input"]}
        if "ctx" in error:
            details["ctx"] = error["ctx"]
        return details
    # A custom type (PydanticCustomError) is not rebuildable by name; keep its type and rendered message, which
    # is not formatted again without a context.
    return {"type": PydanticCustomError(error["type"], error["msg"]), "loc": error["loc"], "input": error["input"]}


def validate_id_uniqueness(data: pd.DataFrame, schemaview: SchemaView, class_name: str) -> ValidationError | None:
    """
    Validate that no entities in the given data have duplicate IDs.

    Args:
        data: A dataframe containing the entities to validate
        schemaview: The schemaview to use to determine the identifier slot
        class_name: The schema class name of the entities being validated

    Returns:
        A Pydantic ValidationError if any duplicate IDs appear, or None otherwise
    """

    id_name = get_class_identifier_name(schemaview, class_name)

    if id_name not in data:
        return None

    # Get IDs that are not missing and appear multiple times
    duplicate_ids = data[id_name][data[id_name].notna() & data[id_name].duplicated(keep=False)]

    if len(duplicate_ids) == 0:
        return None

    def get_row_error_details(index, id) -> InitErrorDetails:
        # Provide row-specific info to facilitate error handling
        ctx = {"row_index": index, "row_id": id}
        return {
            "type": PydanticCustomError("duplicate_id", "Duplicate identifier {row_id}", ctx),
            "loc": (id_name,),
            "input": id,
            "ctx": ctx,
        }

    return ValidationError.from_exception_data(
        title="Duplicate identifiers",
        line_errors=[get_row_error_details(index, value) for index, value in duplicate_ids.items()],
    )


def validate_referential_integrity(
    data_by_entity_type: dict[str, pd.DataFrame], schemaview: SchemaView, class_name: str
):
    """
    Validate that no foreign references in the data for the specified class are missing corresponding rows in the
    foreign data.

    Args:
        data_by_entity_type: Dict containing dataframes for all entity types, keyed by entity type
        schemaview: The schemaview to use to determine class and slot relationships
        class_name: The schema class name of the entities being validated

    Returns:
        A Pydantic ValidationError if any referenced entities are missing, or None otherwise
    """

    data = data_by_entity_type[get_class_entity_type(class_name)]
    id_name = get_class_identifier_name(schemaview, class_name)

    def get_row_error_details(index, id, fk_value, fk_slot_name, foreign_entity_type) -> InitErrorDetails:
        # Provide row-specific info to facilitate error handling
        ctx = {
            "row_index": index,
            "row_id": id,
            "foreign_entity_type": foreign_entity_type,
            "foreign_key_value": fk_value,
        }
        return {
            "type": PydanticCustomError(
                "missing_reference",
                "Referenced {foreign_entity_type} with ID {foreign_key_value} doesn't exist",
                ctx,
            ),
            "loc": (fk_slot_name,),
            "input": fk_value,
            "ctx": ctx,
        }

    line_errors = []

    for fk_slot_name, fk_class_name in get_class_foreign_keys(schemaview, class_name):
        # If the foreign key column doesn't exist, skip
        if fk_slot_name not in data:
            continue
        fk_entity_type = get_class_entity_type(fk_class_name)
        foreign_data = data_by_entity_type[fk_entity_type]
        foreign_id_name = get_class_identifier_name(schemaview, fk_class_name)
        if foreign_id_name not in foreign_data:
            # If the foreign data's ID column doesn't exist, all non-empty reference IDs are missing a corresponding
            # entry
            missing_ref_rows = data[data[fk_slot_name].notna()]
        else:
            # Otherwise, get reference IDs that are not empty and are not in the foreign ID column
            missing_ref_rows = data[
                data[fk_slot_name].notna() & ~data[fk_slot_name].isin(foreign_data[foreign_id_name])
            ]
        # Get iterable of row IDs; default to all-None if the ID column doesn't exist
        missing_ref_row_ids = (
            missing_ref_rows[id_name] if id_name in missing_ref_rows else itertools.repeat(None, len(missing_ref_rows))
        )
        # Add errors to list
        line_errors.extend(
            get_row_error_details(index, id_value, fk_value, fk_slot_name, fk_entity_type)
            for (index, fk_value), id_value in zip(
                missing_ref_rows[fk_slot_name].items(), missing_ref_row_ids, strict=True
            )
        )

    if not line_errors:
        return None

    return ValidationError.from_exception_data(title="Missing referenced entities", line_errors=line_errors)
