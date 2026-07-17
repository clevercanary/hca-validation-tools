import os
from typing import Iterator, List, Optional, Tuple

import jsonasobj2
from linkml_runtime import SchemaView
from linkml_runtime.linkml_model.meta import SlotDefinition

# Map entity types and bionetworks to their corresponding class names
schema_classes = {
    "dataset": {
        "DEFAULT": "Dataset",
        "adipose": "AdiposeDataset",
        "gut": "GutDataset",
        "musculoskeletal": "MusculoskeletalDataset",
    },
    "donor": {"DEFAULT": "Donor"},
    "sample": {"DEFAULT": "Sample", "adipose": "AdiposeSample", "gut": "GutSample"},
    "cell": {"DEFAULT": "Cell"},
}

# Derive mapping from class name to entity type
entity_types_by_class = dict(
    (class_name, entity_type)
    for entity_type, network_mapping in schema_classes.items()
    for _, class_name in network_mapping.items()
)


def load_schemaview():
    # Get the schema path
    module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schema_path = os.path.join(module_dir, "schema/core.yaml")
    # Create a schemaview
    return SchemaView(schema_path)


def get_entity_class_name(schema_type: str, bionetwork: Optional[str] = None) -> str:
    # Validate schema type
    if schema_type not in schema_classes:
        raise ValueError(
            f"Unsupported schema type: {schema_type}. Supported types are: {', '.join(schema_classes.keys())}"
        )

    type_classes = schema_classes[schema_type]
    return type_classes.get(bionetwork, type_classes["DEFAULT"])


def get_class_entity_type(class_name: str) -> str:
    if class_name not in entity_types_by_class:
        raise ValueError(f"Unknown schema class: {class_name}")
    return entity_types_by_class[class_name]


def get_class_identifier_name(schemaview: SchemaView, class_name: str) -> str:
    for slot in schemaview.class_induced_slots(class_name):
        if slot.identifier:
            return slot.name
    raise ValueError(f"No identifier slot found for class {class_name}")


def get_slot_anndata_location(slot: SlotDefinition) -> Optional[str]:
    if not slot.annotations:
        return None
    for name, info in jsonasobj2.items(slot.annotations):
        if name == "annDataLocation":
            return info.value
    return None


def is_deprecated_slot(schemaview: SchemaView, slot: SlotDefinition) -> bool:
    parent = slot.is_a
    while parent is not None:
        if parent == "deprecated_slot":
            return True
        parent = schemaview.get_slot(parent).is_a
    return False


def coverage_classes(schemaview: SchemaView) -> List[str]:
    """DEFAULT LinkML class names eligible for metadata coverage reporting.

    Returns the canonical (non-bionetwork-specific) class for each entity type
    when that class has at least one coverage-eligible slot. Cell currently has
    no slots and so is excluded in v0.

    Bionetwork-specific variants (AdiposeDataset, GutSample, etc.) are intentionally
    excluded: the validator emits coverage at the generic entity grain (donor,
    sample, dataset) regardless of bionetwork.
    """
    eligible = []
    for entity_type, network_mapping in schema_classes.items():
        class_name = network_mapping["DEFAULT"]
        if any(True for _ in iter_coverage_slots(schemaview, class_name)):
            eligible.append(class_name)
    return eligible


def iter_coverage_slots(schemaview: SchemaView, class_name: str) -> Iterator[Tuple[str, str]]:
    """Yield (slot_name, annDataLocation) for slots of `class_name` that participate
    in coverage reporting at entity grain.

    Excludes: identifier slots (routed to obs grain separately), foreign-key slots
    (their information is captured by obs-grain identifier coverage), deprecated
    slots, and slots without an annDataLocation annotation.
    """
    fk_slot_names = {name for name, _ in get_class_foreign_keys(schemaview, class_name)}
    for slot in schemaview.class_induced_slots(class_name):
        if slot.identifier:
            continue
        if slot.name in fk_slot_names:
            continue
        if is_deprecated_slot(schemaview, slot):
            continue
        location = get_slot_anndata_location(slot)
        if location is None:
            continue
        yield slot.name, location


def get_class_foreign_keys(schemaview: SchemaView, class_name: str):
    """
    Get list of (slot name, slot range) tuples for slots of the given class that hold references to other classes.

    Args:
      schemaview: Schemaview to get class and slot info from
      class_name: Name of class to get slots for

    Returns:
      List of (slot name, slot range) tuples
    """
    foreign_keys = []
    classes = schemaview.all_classes()
    for slot in schemaview.class_induced_slots(class_name):
        if slot.inlined is False and slot.range in classes:
            foreign_keys.append((slot.name, slot.range))
    return foreign_keys
