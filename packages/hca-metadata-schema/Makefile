# hca-metadata-schema Makefile
# Schema validation and model generation. The data dictionary is built from shared/ (it needs shared's code).

SCHEMA_DIR := src/hca_metadata_schema
GENERATED := $(SCHEMA_DIR)/generated/core.py
SCHEMAS := $(wildcard $(SCHEMA_DIR)/*.yaml)
UV := uv run --group codegen
SUPPRESS_WARNINGS := 2>/dev/null

.PHONY: help
help:
	@echo "hca-metadata-schema tasks:"
	@echo "  validate-schema - Validate all schema files"
	@echo "  lint-schema     - Lint schema files"
	@echo "  gen-schema      - Generate the Pydantic models from the LinkML schemas"
	@echo "  test            - Run the package tests"

# Schema validation
.PHONY: validate-schema
validate-schema:
	@echo "Validating all schema files..."
	@for schema in $(SCHEMAS); do \
		echo "Validating $$(basename $$schema)..."; \
		$(UV) gen-yaml $$schema > /dev/null $(SUPPRESS_WARNINGS) || exit 1; \
		echo "✓ $$(basename $$schema) is valid"; \
	done
	@echo "All schema files are valid!"

# Lint schema files
.PHONY: lint-schema
lint-schema:
	@echo "Linting schema files..."
	@$(UV) linkml lint $(SCHEMA_DIR) --validate

# Lint schema files with only errors (no style warnings)
.PHONY: lint-schema-errors
lint-schema-errors:
	@echo "Linting schema files (errors only)..."
	@$(UV) linkml lint $(SCHEMA_DIR) --validate --ignore-warnings || (echo "❌ Schema has critical errors" && exit 1)
	@echo "✓ No critical errors found in schema files"

# Generate Python models from schemas
.PHONY: gen-schema
gen-schema:
	@echo "Generating models..."
	@# Generate to a temp file so a failed run leaves the committed model intact. sed marks the schema version line
	@# so release-please bumps it with core.yaml (docs/schema-version-contract.md).
	@$(UV) gen-pydantic $(SCHEMA_DIR)/core.yaml --meta AUTO > $(GENERATED).tmp
	@sed -E 's/^(version = "[^"]*")$$/\1  # x-release-please-version/' $(GENERATED).tmp > $(GENERATED)
	@rm $(GENERATED).tmp
	@echo "Done"

.PHONY: test
test:
	@uv run pytest tests/ -v
