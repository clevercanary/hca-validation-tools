# Shared Library Makefile
# Tasks specific to the shared validation library

# Variables
# The LinkML schema lives in its own package (#350); the schema targets below run there.
SCHEMA_PKG := ../packages/hca-metadata-schema
UV := uv run

.PHONY: help
help:
	@echo "Shared Library Tasks:"
	@echo "  validate-schema        - Validate all schema files"
	@echo "  lint-schema           - Lint schema files"
	@echo "  lint-schema-errors    - Lint schema files (errors only)"
	@echo "  gen-schema            - Generate Python models from LinkML schemas"
	@echo "  generate-data-dictionary - Generate data dictionary from core schema"
	@echo "  test                  - Run shared library tests"
	@echo "  test-validator        - Run validator tests only"
	@echo "  test-entry-sheet      - Run entry sheet validator tests only"
	@echo "  test-integration      - Run integration tests only"
	@echo "  build                 - Build shared library (validate + generate)"

# Schema targets: run in the hca-metadata-schema package, which owns the YAML and the generated models
.PHONY: validate-schema lint-schema lint-schema-errors gen-schema
validate-schema lint-schema lint-schema-errors gen-schema:
	@$(MAKE) -C $(SCHEMA_PKG) $@

# Generate data dictionary
.PHONY: generate-data-dictionary
generate-data-dictionary:
	@echo "Generating data dictionary from core schema..."
	@$(UV) python -c "from hca_validation.data_dictionary.generate_dictionary import generate_dictionary; generate_dictionary(output_path='../data_dictionaries/core_data_dictionary.json')"
	@echo "✓ Data dictionary generated"

# Run validator tests (in shared library)
.PHONY: test-validator
test-validator:
	@echo "Running validator tests..."
	@$(UV) pytest tests/test_validator.py -v -W ignore::DeprecationWarning

# Run entry sheet validator tests (in shared library)
.PHONY: test-entry-sheet
test-entry-sheet:
	@echo "Running entry sheet validator tests..."
	@$(UV) pytest tests/test_entry_sheet_validator.py -v -W ignore::DeprecationWarning

# Run shared library tests
.PHONY: test-shared
test-shared:
	@echo "Running shared library tests..."
	@$(UV) pytest tests/ -v -W ignore::DeprecationWarning

# Run integration tests only
.PHONY: test-integration
test-integration:
	@echo "Running integration tests..."
	@$(UV) pytest tests/ -m integration -v
	@echo "✓ Integration tests passed"

# Build target (validate + generate)
.PHONY: build
build: validate-schema gen-schema generate-data-dictionary
	@echo "✓ Shared library built successfully"
