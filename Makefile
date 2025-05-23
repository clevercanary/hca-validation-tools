# HCA Validation Tools Makefile
# This Makefile provides commands for validating LinkML schemas

# Variables
SCHEMA_DIR := src/hca_validation/schema
SCHEMAS := $(wildcard $(SCHEMA_DIR)/*.yaml)
POETRY := poetry run
# Redirect stderr to suppress warnings from LinkML tools (duplicate -V parameter warnings)
# These warnings are related to the LinkML tool implementation and not to schema issues
SUPPRESS_WARNINGS := 2>/dev/null

# Default target
.PHONY: help
help:
	@echo "HCA Validation Tools Makefile"
	@echo ""
	@echo "Available targets:"
	@echo "  validate-schema  - Validate all schema files"
	@echo "  validate-core    - Validate core schema"
	@echo "  validate-dataset - Validate dataset schema"
	@echo "  validate-donor   - Validate donor schema"
	@echo "  validate-sample  - Validate sample schema"
	@echo "  validate-cell    - Validate cell schema"
	@echo "  validate-verbose - Validate dataset schema with warnings"
	@echo "  lint-schema      - Run LinkML linter on all schema files"
	@echo "  lint-schema-errors - Run LinkML linter (critical errors only)"
	@echo "  generate-pydantic-models - Generate Pydantic models from all LinkML schemas"
	@echo "  generate-data-dictionary - Generate data dictionary JSON from core schema to standard path"
	@echo "  generate-data-dictionary-file - Generate data dictionary from schema to specified file"
	@echo "  test-dataset-validation - Run dataset validation tests"
	@echo "  help             - Show this help message"

# Validate all schema files
.PHONY: validate-schema
validate-schema:
	@echo "Validating all schema files..."
	@for schema in $(SCHEMAS); do \
		echo "Validating $$schema..."; \
		$(POETRY) gen-yaml $$schema > /dev/null $(SUPPRESS_WARNINGS) || exit 1; \
		echo "✓ $$schema is valid"; \
	done
	@echo "All schema files are valid!"

# Validate individual schema files
.PHONY: validate-core
validate-core:
	@echo "Validating core schema..."
	@$(POETRY) gen-yaml $(SCHEMA_DIR)/core.yaml > /dev/null $(SUPPRESS_WARNINGS) || (echo "❌ Core schema validation failed" && exit 1)
	@echo "✓ Core schema is valid"

.PHONY: validate-dataset
validate-dataset:
	@echo "Validating dataset schema..."
	@$(POETRY) gen-yaml $(SCHEMA_DIR)/dataset.yaml > /dev/null $(SUPPRESS_WARNINGS) || (echo "❌ Dataset schema validation failed" && exit 1)
	@echo "✓ Dataset schema is valid"

.PHONY: validate-donor
validate-donor:
	@echo "Validating donor schema..."
	@$(POETRY) gen-yaml $(SCHEMA_DIR)/donor.yaml > /dev/null $(SUPPRESS_WARNINGS) || (echo "❌ Donor schema validation failed" && exit 1)
	@echo "✓ Donor schema is valid"

.PHONY: validate-sample
validate-sample:
	@echo "Validating sample schema..."
	@$(POETRY) gen-yaml $(SCHEMA_DIR)/sample.yaml > /dev/null $(SUPPRESS_WARNINGS) || (echo "❌ Sample schema validation failed" && exit 1)
	@echo "✓ Sample schema is valid"

.PHONY: validate-cell
validate-cell:
	@echo "Validating cell schema..."
	@$(POETRY) gen-yaml $(SCHEMA_DIR)/cell.yaml > /dev/null $(SUPPRESS_WARNINGS) || (echo "❌ Cell schema validation failed" && exit 1)
	@echo "✓ Cell schema is valid"

# Validate with warnings shown
.PHONY: validate-verbose
validate-verbose:
	@echo "Validating dataset schema with warnings..."
	$(POETRY) gen-yaml $(SCHEMA_DIR)/dataset.yaml > /dev/null
	@echo "✓ Dataset schema is valid"

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

# Run validator tests
.PHONY: test-validator
test-validator:
	@echo "Running validator tests..."
	@$(POETRY) pytest tests/test_validator.py -v -W ignore::DeprecationWarning

# Validate Google Sheet
.PHONY: validate-sheet
validate-sheet:
	@echo "Validating Google Sheet..."
	@$(POETRY) python -m hca_validation.entry_sheet_validator.validate_sheet

# Validate specific Google Sheet
.PHONY: validate-sheet-id
validate-sheet-id:
	@echo "Validating Google Sheet with ID: $(SHEET_ID)"
	@$(POETRY) python -m hca_validation.entry_sheet_validator.validate_sheet $(SHEET_ID)

# Generate data dictionary from core schema to standard path
.PHONY: generate-data-dictionary
generate-data-dictionary:
	@echo "Generating data dictionary from core schema to standard path..."
	@cd $(shell pwd) && $(POETRY) python -c "from hca_validation.data_dictionary.generate_dictionary import generate_dictionary; generate_dictionary()"

# Generate data dictionary from a specific schema file to a specific output file
.PHONY: generate-data-dictionary-file
generate-data-dictionary-file:
	@if [ -z "$(OUTPUT_FILE)" ]; then \
		echo "Error: OUTPUT_FILE is required. Usage: make generate-data-dictionary-file OUTPUT_FILE=path/to/output.json [SCHEMA_FILE=path/to/schema.yaml]"; \
		exit 1; \
	fi
	@if [ -z "$(SCHEMA_FILE)" ]; then \
		echo "Generating data dictionary from core schema to $(OUTPUT_FILE)..."; \
		cd $(shell pwd) && $(POETRY) python -c "from hca_validation.data_dictionary.generate_dictionary import generate_dictionary; generate_dictionary('$(SCHEMA_DIR)/core.yaml', '$(OUTPUT_FILE)')"; \
	else \
		echo "Generating data dictionary from $(SCHEMA_FILE) to $(OUTPUT_FILE)..."; \
		cd $(shell pwd) && $(POETRY) python -c "from hca_validation.data_dictionary.generate_dictionary import generate_dictionary; generate_dictionary('$(SCHEMA_FILE)', '$(OUTPUT_FILE)')"; \
	fi
	@echo "✓ Data dictionary generated at $(OUTPUT_FILE)"
