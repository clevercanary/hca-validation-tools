"""The HCA metadata schema: LinkML YAML definitions and the Pydantic models generated from them.

`CORE_SCHEMA_PATH` is the root schema; it imports every other YAML file shipped here. The models are in
`hca_metadata_schema.generated.core`, regenerated from the YAML by `make gen-schema`.
"""

from pathlib import Path

__version__ = "0.2.1"  # x-release-please-version

CORE_SCHEMA_PATH = Path(__file__).parent / "core.yaml"
