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
