from collections.abc import Iterator

import jsonasobj2
from hca_metadata_schema import CORE_SCHEMA_PATH
from linkml_runtime import SchemaView
from linkml_runtime.linkml_model.meta import ClassDefinition, SlotDefinition

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
entity_types_by_class = {
    class_name: entity_type
    for entity_type, network_mapping in schema_classes.items()
    for _, class_name in network_mapping.items()
}


def load_schemaview():
    return SchemaView(CORE_SCHEMA_PATH)


def get_entity_class_name(schema_type: str, bionetwork: str | None = None) -> str:
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


def _annotation_value(element: SlotDefinition | ClassDefinition, key: str):
    for name, info in jsonasobj2.items(element.annotations or {}):
        if name == key:
            return info.value
    return None


def get_slot_anndata_location(slot: SlotDefinition) -> str | None:
    return _annotation_value(slot, "annDataLocation")


_ENTRY_SHEET_REQUIRED = "entrySheetRequired"


def get_entry_sheet_optional_slots(schemaview: SchemaView, class_name: str) -> frozenset[str]:
    """Slots of `class_name` annotated `entrySheetRequired: false` (#850); another value, or an optional slot, raises.

    A `slot_usage` that sets annotations replaces the inherited ones (linkml#2805), so when the induced slot lacks the
    tag, the class's and its ancestors' `slot_usage` are searched in order, then the slot itself.
    """
    optional = set()
    ancestors = [schemaview.get_class(c) for c in schemaview.class_ancestors(class_name)]
    for slot in schemaview.class_induced_slots(class_name):
        usages = [(ancestor.slot_usage or {}).get(slot.name) for ancestor in ancestors]
        value = None
        for source in [slot, *usages, schemaview.get_slot(slot.name)]:
            if source is not None:
                value = _annotation_value(source, _ENTRY_SHEET_REQUIRED)
                if value is not None:
                    break
        if value is None:
            continue
        if value is not False:
            raise ValueError(f"{class_name}.{slot.name}: {_ENTRY_SHEET_REQUIRED} must be false, got {value!r}")
        if not slot.required:
            raise ValueError(f"{class_name}.{slot.name}: {_ENTRY_SHEET_REQUIRED} is only for required slots")
        optional.add(slot.name)
    return frozenset(optional)


def get_bionetwork_keys(schemaview: SchemaView) -> list[str]:
    """Return the sorted keys of the schema's `BioNetwork` enum."""
    enum_info = schemaview.get_enum("BioNetwork")
    if enum_info is None or not enum_info.permissible_values:
        raise ValueError("Schema has no BioNetwork enum")
    return sorted(enum_info.permissible_values)


def get_class_bionetwork(class_info: ClassDefinition) -> str | None:
    """Return the network a class names in its `bioNetwork` annotation, if any."""
    return _annotation_value(class_info, "bioNetwork")


def get_bionetwork_subclasses(schemaview: SchemaView, base_class: str) -> dict[str, str]:
    """Map each subclass of `base_class` to the network its `bioNetwork` annotation names.

    Only direct, concrete subclasses are supported; any other descendant is refused rather
    than skipped, so its slots cannot silently go missing from callers.

    Raises:
        ValueError: If a descendant is abstract or indirect, or a subclass has no
            `bioNetwork` annotation or one that is not a key of the `BioNetwork` enum
    """
    network_keys = get_bionetwork_keys(schemaview)
    children = schemaview.class_children(base_class, mixins=False)
    for descendant in schemaview.class_descendants(base_class, reflexive=False, mixins=False):
        if descendant not in children or schemaview.get_class(descendant).abstract:
            raise ValueError(f"{descendant} is not a direct, concrete subclass of {base_class}")
    subclasses = {}
    for subclass_name in children:
        subclass_info = schemaview.get_class(subclass_name)
        network = get_class_bionetwork(subclass_info)
        if network is None:
            raise ValueError(f"{subclass_name} extends {base_class} but has no bioNetwork annotation")
        if network not in network_keys:
            raise ValueError(f"{subclass_name} has bioNetwork {network!r}, which is not in the BioNetwork enum")
        subclasses[subclass_name] = network
    return subclasses


def is_deprecated_slot(schemaview: SchemaView, slot: SlotDefinition) -> bool:
    parent = slot.is_a
    while parent is not None:
        if parent == "deprecated_slot":
            return True
        parent = schemaview.get_slot(parent).is_a
    return False


def coverage_classes(schemaview: SchemaView) -> list[str]:
    """DEFAULT LinkML class names eligible for metadata coverage reporting.

    Returns the canonical (non-bionetwork-specific) class for each entity type
    when that class has at least one coverage-eligible slot. Cell is excluded
    deliberately — see below.

    Bionetwork-specific variants (AdiposeDataset, GutSample, etc.) are intentionally
    excluded: the validator emits coverage at the generic entity grain (donor,
    sample, dataset) regardless of bionetwork.
    """
    eligible = []
    for network_mapping in schema_classes.values():
        class_name = network_mapping["DEFAULT"]
        # Cell gained slots in #538, which would otherwise make it eligible and
        # emit entity_class == "cell" rows. The tracker validates every coverage
        # row against a closed allowlist of ["dataset", "donor", "obs", "sample"],
        # and because metadata_coverage shares a schema with tool_reports, an
        # unrecognized grain fails the *entire* validation-results message rather
        # than degrading coverage. Nothing consumes cell-grain coverage today, so
        # suppressing it here avoids a cross-repo deploy ordering constraint.
        #
        # Note the asymmetry, which is deliberate rather than an oversight: only
        # `entity_class` is allowlisted. The row's `field` is `string().required()`
        # with no `oneOf`, and the tracker's completeness rollup intersects incoming
        # fields against its own data dictionary, ignoring ones it does not know. So
        # new *fields* are safe to emit without coordination, while a new *grain* is
        # not — which is why #538 could add a sample-grain row for
        # `sample_collection_method` in the same change that suppresses Cell.
        # (`is_primary_data` also gained the obs annotation but emits nothing: it
        # remains a deprecated_slot, and deprecated slots are filtered from coverage.)
        # Remove once clevercanary/hca-atlas-tracker#1499 ships, which widens the
        # allowlist and makes entities["cell"] optional.
        if class_name == "Cell":
            continue
        if any(True for _ in iter_coverage_slots(schemaview, class_name)):
            eligible.append(class_name)
    return eligible


def iter_coverage_slots(schemaview: SchemaView, class_name: str) -> Iterator[tuple[str, str]]:
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
