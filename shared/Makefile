# Shared Library Makefile
# Tasks specific to the shared validation library

# Variables
SCHEMA_DIR := src/hca_validation/schema
SCHEMAS := $(wildcard $(SCHEMA_DIR)/*.yaml)
POETRY := poetry run
SUPPRESS_WARNINGS := 2>/dev/null

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

# Schema validation
.PHONY: validate-schema
validate-schema:
	@echo "Validating all schema files..."
	@for schema in $(SCHEMAS); do \
		schema_file=$$(basename $$schema); \
		echo "Validating $$schema_file..."; \
		$(POETRY) gen-yaml $(SCHEMA_DIR)/$$schema_file > /dev/null $(SUPPRESS_WARNINGS) || exit 1; \
		echo "✓ $$schema_file is valid"; \
	done
	@echo "All schema files are valid!"

# Lint schema files
.PHONY: lint-schema
lint-schema:
	@echo "Linting schema files..."
	@$(POETRY) linkml lint $(SCHEMA_DIR) --validate

# Lint schema files with only errors (no style warnings)
.PHONY: lint-schema-errors
lint-schema-errors:
	@echo "Linting schema files (errors only)..."
	@$(POETRY) linkml lint $(SCHEMA_DIR) --validate --ignore-warnings || (echo "❌ Schema has critical errors" && exit 1)
	@echo "✓ No critical errors found in schema files"

# Generate Python models from schemas
.PHONY: gen-schema
gen-schema:
	@echo "Generating models..."
	@$(POETRY) gen-pydantic src/hca_validation/schema/core.yaml --meta AUTO > src/hca_validation/schema/generated/core.py
	@echo "Done"

# Generate data dictionary
.PHONY: generate-data-dictionary
generate-data-dictionary:
	@echo "Generating data dictionary from core schema..."
	@$(POETRY) python -c "from hca_validation.data_dictionary.generate_dictionary import generate_dictionary; generate_dictionary('src/hca_validation/schema/core.yaml', '../data_dictionaries/core_data_dictionary.json')"
	@echo "✓ Data dictionary generated"

# Run validator tests (in shared library)
.PHONY: test-validator
test-validator:
	@echo "Running validator tests..."
	@$(POETRY) pytest tests/test_validator.py -v -W ignore::DeprecationWarning

# Run entry sheet validator tests (in shared library)
.PHONY: test-entry-sheet
test-entry-sheet:
	@echo "Running entry sheet validator tests..."
	@$(POETRY) pytest tests/test_entry_sheet_validator.py -v -W ignore::DeprecationWarning

# Run shared library tests
.PHONY: test-shared
test-shared:
	@echo "Running shared library tests..."
	@$(POETRY) pytest tests/ -v -W ignore::DeprecationWarning

# Run integration tests only
.PHONY: test-integration
test-integration:
	@echo "Running integration tests..."
	@$(POETRY) pytest tests/ -m integration -v
	@echo "✓ Integration tests passed"

# Build target (validate + generate)
.PHONY: build
build: validate-schema gen-schema generate-data-dictionary
	@echo "✓ Shared library built successfully"
