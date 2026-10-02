# HCA Schema Validator

HCA-specific extensions for cellxgene schema validation.

## Installation

### From PyPI (Recommended)

```bash
pip install hca-schema-validator
```

### From Source (Development)

Install uv by whichever method you prefer — see the
[official installation guide](https://docs.astral.sh/uv/getting-started/installation/).
On macOS `brew install uv` and `pipx install uv` are both auditable alternatives
to the piped install script. Any method works; uv's version is what matters, not
how it got there.

```bash
# Clone the repository
git clone https://github.com/clevercanary/hca-validation-tools.git
cd hca-validation-tools/packages/hca-schema-validator

# Install dependencies and package
uv sync

# Run tests
uv run pytest tests/
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
uv run pytest tests/
```

## Project Structure

```
hca_schema_validator/
├── src/
│   └── hca_schema_validator/
│       ├── __init__.py       # Package exports
│       ├── validator.py      # HCAValidator and the HCA-specific checks
│       ├── ontology_data/    # Ontology overlay files (see below)
│       └── gene_release_intervals.csv.gz  # Gene presence per Ensembl release (see below)
├── tests/
│   └── test_validator.py # Unit tests
├── pyproject.toml        # uv/PEP 621 configuration & dependencies
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
   uv run python -c "
   from hca_schema_validator._vendored.cellxgene_schema.ontology_parser import ONTOLOGY_PARSER
   print(ONTOLOGY_PARSER.is_valid_term_id('CL:4052065'))  # True
   "
   uv run pytest tests/ -v
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

## Gene Release Interval Table

`check_gene_annotation_version` compares the annotation a file declares in
`obs['gene_annotation_version']` against the genes the file actually contains. To
do that it needs to know which Ensembl releases each gene existed in, which is
what `src/hca_schema_validator/gene_release_intervals.csv.gz` records.

### How it works

One row per gene per contiguous run of releases it was present in:

```
# ensembl GRCh38 gene presence, releases 76-116
gene_id,first_release,last_release
ENSG00000000003,76,116
```

Intervals rather than a single `(first, last)` pair because genes are
occasionally **resurrected** — `ENSG00000288593` is retired at r105 and returns
at r109, and a flat pair would claim it existed at r106–r108. Two genes in the
shipped range have more than one interval.

The table is sized by genes, not releases, so covering the whole GRCh38 history
costs no more than covering a handful of releases.

### Current table

| | |
|---|---|
| Ensembl releases covered | **r76 – r116** (r76 is the first GRCh38 core database) |
| Genes | 93,543 |
| Intervals | 93,545 |
| File size | 249 KB gzipped |

### When to regenerate

**The validator tells you.** When a file declares a release newer than the table
covers, the check says so rather than failing the file:

> `obs['gene_annotation_version']` is `'v117'`, which is newer than this
> reference data covers (through r116), so the genes in this file were not
> checked against it.

That warning is the trigger. Regenerate when you see it, or when Ensembl ships a
release you want to date against.

The table also sets the ceiling on the Ensembl/GENCODE ambiguity: a bare number
below r76 could be either scheme, and the boundary is read from the vendored
`gencode_files/gene_info.yml`, so bumping `cellxgene-schema` moves it
independently of this table.

### How to regenerate

Ensembl keeps a core database per release on its public MySQL server, so the
whole history is one query per release rather than a download. Needs outbound
MySQL to `ensembldb.ensembl.org:3306` (user `anonymous`, no password).

1. Run the generator. About two seconds per release, so roughly 90 seconds for
   the full GRCh38 range:

   ```bash
   uv run --no-project --with pymysql python scripts/build_gene_release_intervals.py
   ```

   It writes `src/hca_schema_validator/gene_release_intervals.csv.gz` by default;
   `--out` writes elsewhere.

2. Check the header records the range you expect, and that the gene and interval
   counts moved in the direction you expect:

   ```bash
   gzip -dc src/hca_schema_validator/gene_release_intervals.csv.gz | head -3
   gzip -dc src/hca_schema_validator/gene_release_intervals.csv.gz | tail -n +3 | wc -l
   ```

3. Run the tests. `test_resurrected_gene_is_absent_between_its_runs` pins the
   resurrection behaviour against a known gene, so a regeneration that flattened
   intervals would fail there:

   ```bash
   uv run pytest tests/ -q
   ```

4. Commit the regenerated file and update the **Current table** above.

### Why not `stable_id_event`

Ensembl's `stable_id_event` table is the right source for *retirement history*
but cannot answer presence at a given release. Measured against release 114:
`mapping_session` only covers releases 10–99, and self-mappings are not recorded
exhaustively — TP53 has 22 rows across 72 sessions. Presence has to come from
each release's own `gene` table, which is what the generator queries.

## License

MIT
