# HCA Schema Validator

HCA-specific extensions for cellxgene schema validation.

## Installation

### From PyPI (Recommended)

```bash
pip install hca-schema-validator
```

### From Source (Development)

```bash
# Clone the repository
git clone https://github.com/clevercanary/hca-validation-tools.git
cd hca-validation-tools/packages/hca-schema-validator

# Install Poetry if you haven't already
curl -sSL https://install.python-poetry.org | python3 -

# Install dependencies and package
poetry install

# Run tests
poetry run pytest tests/
```

## Usage

```python
from hca_schema_validator import HCAValidator

# Create validator instance
validator = HCAValidator()

# Validate an h5ad file
is_valid = validator.validate_adata("path/to/file.h5ad")

# Check results
if is_valid:
    print("✅ Validation passed!")
else:
    print("❌ Validation failed:")
    for error in validator.errors:
        print(f"  - {error}")
```

## Development Status

**Current Version: 0.1.0** - Minimal passthrough implementation

Currently a passthrough wrapper around cellxgene-schema Validator.
HCA-specific validation rules will be added incrementally.

## Testing

```bash
cd hca_schema_validator
poetry run pytest tests/
```

## Project Structure

```
hca_schema_validator/
├── src/
│   └── hca_schema_validator/
│       ├── __init__.py       # Package exports
│       └── validator.py      # HCAValidator class
├── tests/
│   └── test_validator.py # Unit tests
├── pyproject.toml        # Poetry configuration & dependencies
└── README.md            # This file
```

## Ontology Data Overlay

The validator depends on `cellxgene-ontology-guide` for ontology term lookups. When that
package is missing terms we need (e.g., newly added CL or EFO terms), we generate updated
ontology data files and overlay them at runtime.

### How it works

`_vendored/cellxgene_schema/ontology_parser.py` monkey-patches two functions from
`cellxgene_ontology_guide.supported_versions`:

- `load_supported_versions()` loads upstream version data and patches only the ontology
  versions listed in `_ONTOLOGY_VERSION_OVERRIDES` — all other ontologies and any new
  entries added by future package releases are preserved unchanged.
- `load_ontology_file(file_name)` checks `ontology_data/` first for a `.json.zst` file,
  falling back to the package's bundled data.

### Current overlays

| Ontology | Overlay Version | Bundled Version | Why |
|----------|----------------|-----------------|-----|
| CL       | v2025-12-17    | v2025-07-30     | Missing salivary gland cell types (CL:4052065-4052069) |

### How to add/update an ontology overlay

Prerequisites: Python 3.10+, Docker, ~1GB disk for OWL files.

1. **Clone CZI's ontology-guide repo** (contains the build pipeline):
   ```bash
   cd /tmp && mkdir ontology-guide-build && cd ontology-guide-build
   git clone --depth 1 https://github.com/chanzuckerberg/cellxgene-ontology-guide.git
   ```

2. **Set up build environment**:
   ```bash
   python3 -m venv venv && source venv/bin/activate
   pip install owlready2==0.48 zstandard jsonschema semantic-version referencing cellxgene-ontology-guide
   docker pull obolibrary/robot:v1.9.8
   ```

3. **Create a targeted ontology_info JSON** with only the ontology to build.
   Save as `cellxgene-ontology-guide/ontology-assets/ontology_info_custom.json`:
   ```json
   {
     "7.0.0": {
       "ontologies": {
         "EFO": {
           "version": "v3.86.0",
           "source": "https://github.com/EBISPOT/efo/releases/download/{version}/{filename}",
           "filename": "efo.owl"
         }
       }
     }
   }
   ```
   Find the latest release version on the ontology's GitHub releases page (e.g.,
   [CL releases](https://github.com/obophenotype/cell-ontology/releases),
   [EFO releases](https://github.com/EBISPOT/efo/releases)).

   Copy the ontology entry from the existing `ontology_info.json` in
   `ontology-assets/` and update the `version` field. Keep `source`, `filename`,
   and any other fields (like `cross_ontology_mapping`) the same.

4. **Run the build script**:
   ```python
   #!/usr/bin/env python3
   import json, logging, os, sys
   logging.basicConfig(level=logging.INFO)

   REPO_DIR = "/tmp/ontology-guide-build/cellxgene-ontology-guide"
   sys.path.insert(0, os.path.join(REPO_DIR, "tools/ontology-builder/src"))
   import env
   env.ONTOLOGY_INFO_FILE = os.path.join(REPO_DIR, "ontology-assets/ontology_info_custom.json")
   env.ONTOLOGY_ASSETS_DIR = os.path.join(REPO_DIR, "ontology-assets")

   from all_ontology_generator import _download_ontologies, _parse_ontologies, get_ontology_info_file
   onto_info = get_ontology_info_file(env.ONTOLOGY_INFO_FILE)["7.0.0"]["ontologies"]
   _download_ontologies(onto_info)
   for f in _parse_ontologies(onto_info):
       logging.info(f"Generated: {f}")
   ```

5. **Copy the `.json.zst` output** into `src/hca_schema_validator/ontology_data/`.

6. **Add an entry to `_ONTOLOGY_VERSION_OVERRIDES`** in `ontology_parser.py`:
   ```python
   _ONTOLOGY_VERSION_OVERRIDES = {
       ("7.0.0", "CL"): "v2025-12-17",
       ("7.0.0", "EFO"): "v3.86.0",  # new
   }
   ```

7. **Verify and test**:
   ```bash
   poetry run python -c "
   from hca_schema_validator._vendored.cellxgene_schema.ontology_parser import ONTOLOGY_PARSER
   print(ONTOLOGY_PARSER.is_valid_term_id('CL:4052065'))  # True
   "
   poetry run pytest tests/ -v
   ```

8. **Clean up**: `rm -rf /tmp/ontology-guide-build`

### Removing the overlay

Once `cellxgene-ontology-guide` publishes a version that includes all the terms we need:

1. Delete the overlay files from `ontology_data/` (keep only `__init__.py`)
2. Revert `ontology_parser.py` to its original form:
   ```python
   from cellxgene_ontology_guide.ontology_parser import OntologyParser
   ONTOLOGY_PARSER = OntologyParser(schema_version="v7.0.0")
   ```
3. Bump `cellxgene-ontology-guide` version in `pyproject.toml`

## License

MIT
