"""The HCA metadata schema: LinkML YAML definitions and the Pydantic models generated from them.

`CORE_SCHEMA_PATH` is the Tier 1 root schema; it imports every YAML file shipped here outside `tier_2/`.
`TIER_2_SCHEMA_PATH` is the Tier 2 root, which imports the Tier 2 files and the Tier 1 definitions they reuse. The
models are in `hca_metadata_schema.generated.core`, regenerated from the Tier 1 YAML by `make gen-schema`.
"""

from pathlib import Path

__version__ = "0.3.2"  # x-release-please-version

CORE_SCHEMA_PATH = Path(__file__).parent / "core.yaml"
TIER_2_SCHEMA_PATH = Path(__file__).parent / "tier_2" / "tier_2.yaml"
