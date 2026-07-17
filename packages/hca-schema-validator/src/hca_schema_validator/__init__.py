"""HCA Schema Validator - HCA-specific extensions for cellxgene schema validation."""

# Define constants first (before importing validator to avoid circular import)
__version__ = "0.14.1"
__schema_version__ = "1.0.0"  # HCA schema version (independent from CELLxGENE)
__schema_reference_url__ = "https://data.humancellatlas.org/metadata"  # Static URL, no version in path

# Import after constants are defined
from .cell_annotation_validator import HCACellAnnotationValidator
from .labeler import HCA_DERIVED_OBS_LABELS, HCALabeler
from .populator import populate_in_memory
from .validator import HCAValidator, check_cosmetic_labels

__all__ = [
    "HCA_DERIVED_OBS_LABELS",
    "HCACellAnnotationValidator",
    "HCALabeler",
    "HCAValidator",
    "check_cosmetic_labels",
    "populate_in_memory",
]
