"""Metadata coverage reporting for HCA validation results.

Emits a per-file summary of how completely metadata is populated, broken out by
LinkML class. See PRD `prd-metadata-coverage.md` in hca-atlas-tracker for the
wire format and rationale.
"""

from .metadata_coverage import compute_metadata_coverage, SCHEMA_NAME
