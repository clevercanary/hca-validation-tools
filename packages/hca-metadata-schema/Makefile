# hca-metadata-schema Makefile
# Schema validation and model generation. The data dictionary is built from shared/ (it needs shared's code).

SCHEMA_DIR := src/hca_metadata_schema
GENERATED := $(SCHEMA_DIR)/generated/core.py
# bionetwork/ too: core.yaml imports those files, but a break in one would otherwise be reported against core.yaml.
SCHEMAS := $(wildcard $(SCHEMA_DIR)/*.yaml $(SCHEMA_DIR)/bionetwork/*.yaml)
UV := uv run --group codegen
LINT := $(UV) linkml lint -c .linkmllint.yaml $(SCHEMA_DIR) --validate

.PHONY: help
help:
	@echo "hca-metadata-schema tasks:"
	@echo "  validate-schema - Validate all schema files"
	@echo "  lint-schema     - Lint schema files"
	@echo "  lint-schema-errors - Lint schema files (errors only; what CI runs)"
	@echo "  gen-schema      - Generate the Pydantic models from the LinkML schemas"
	@echo "  test            - Run the package tests"

# Schema validation. gen-yaml's stderr is shown only on failure: on success it holds nothing but a click warning
# about a duplicate -V option, and on failure it holds the file, line and cause (#546).
.PHONY: validate-schema
validate-schema:
	@echo "Validating all schema files..."
	@for schema in $(SCHEMAS); do \
		echo "Validating $$(basename $$schema)..."; \
		errors=$$($(UV) gen-yaml $$schema 2>&1 > /dev/null) || { echo "$$errors"; exit 1; }; \
		echo "✓ $$(basename $$schema) is valid"; \
	done
	@echo "All schema files are valid!"

# Lint schema files
.PHONY: lint-schema
lint-schema:
	@echo "Linting schema files..."
	@$(LINT)

# Lint schema files with only errors (no style warnings)
.PHONY: lint-schema-errors
lint-schema-errors:
	@echo "Linting schema files (errors only)..."
	@$(LINT) --ignore-warnings || (echo "❌ Schema has critical errors" && exit 1)
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
