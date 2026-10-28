# hca-metadata-schema

The HCA metadata schema: the LinkML YAML definitions and the Pydantic models generated from them.

## Installation

```bash
pip install hca-metadata-schema
```

## Usage

```python
from hca_metadata_schema import CORE_SCHEMA_PATH, __version__
from hca_metadata_schema.generated.core import Cell, Dataset, Donor, Sample

# The Pydantic models validate a record against the schema
Donor(...)

# The LinkML source, for tools that read the schema itself (e.g. linkml-runtime's SchemaView)
CORE_SCHEMA_PATH  # .../hca_metadata_schema/core.yaml
```

The package depends only on pydantic. Reading the YAML with `SchemaView` needs `linkml-runtime`, which
you install yourself.

## Versioning

The schema has one version, in `core.yaml`, and the package version is the same number. What each bump
means is set out in
[`docs/schema-version-contract.md`](https://github.com/clevercanary/hca-validation-tools/blob/main/docs/schema-version-contract.md).

## Development

```bash
make gen-schema       # regenerate generated/core.py from the YAML
make validate-schema  # check every YAML file compiles
uv run pytest tests/ -v
```
