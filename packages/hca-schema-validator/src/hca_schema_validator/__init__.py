"""HCA Schema Validator - HCA-specific extensions for cellxgene schema validation."""

# Define constants first (before importing validator to avoid circular import)
__version__ = "0.3.0"
__schema_version__ = "1.0.0"  # HCA schema version (independent from CELLxGENE)
__schema_reference_url__ = "https://data.humancellatlas.org/metadata"  # Static URL, no version in path

# Import after constants are defined
from .validator import HCAValidator

__all__ = ["HCAValidator"]
