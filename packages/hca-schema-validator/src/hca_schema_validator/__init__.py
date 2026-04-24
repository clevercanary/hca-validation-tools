"""HCA Schema Validator - HCA-specific extensions for cellxgene schema validation."""

# Define constants first (before importing validator to avoid circular import)
__version__ = "0.11.0"
__schema_version__ = "1.0.0"  # HCA schema version (independent from CELLxGENE)
__schema_reference_url__ = "https://data.humancellatlas.org/metadata"  # Static URL, no version in path

# Import after constants are defined
from .cell_annotation_validator import HCACellAnnotationValidator
from .labeler import HCA_DERIVED_OBS_LABELS, HCALabeler
from .validator import HCAValidator, check_cosmetic_labels

__all__ = [
    "HCAValidator",
    "HCACellAnnotationValidator",
    "HCALabeler",
    "HCA_DERIVED_OBS_LABELS",
    "check_cosmetic_labels",
]
