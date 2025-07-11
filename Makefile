# HCA Validation Tools Makefile
# This Makefile provides commands for validating LinkML schemas

# Variables
SCHEMA_DIR := src/hca_validation/schema
SCHEMAS := $(wildcard $(SCHEMA_DIR)/*.yaml)
POETRY := poetry run
# Redirect stderr to suppress warnings from LinkML tools (duplicate -V parameter warnings)
# These warnings are related to the LinkML tool implementation and not to schema issues
SUPPRESS_WARNINGS := 2>/dev/null

# Load Make-specific environment overrides (not checked in)
# Put only simple KEY=value pairs here (no JSON).
# Copy the provided `.env.make.example` to `.env.make` and fill in real values.
ifneq (,$(wildcard .env.make))
  include .env.make
endif

# Deployment environment selector (dev is default). Usage: make <target> ENV=prod
ENV ?= dev

# ----- Environment-specific settings -----
ifeq ($(ENV),prod)
AWS_ACCOUNT_ID   ?= $(PROD_AWS_ACCOUNT_ID)
REPO_NAME        ?= $(PROD_REPO_NAME)
LAMBDA_FUNCTION  ?= $(PROD_LAMBDA_FUNCTION)
AWS_REGION       ?= $(PROD_AWS_REGION)
LAMBDA_ROLE      ?= $(PROD_LAMBDA_ROLE)
else # dev
AWS_ACCOUNT_ID   ?= $(DEV_AWS_ACCOUNT_ID)
REPO_NAME        ?= $(DEV_REPO_NAME)
LAMBDA_FUNCTION  ?= $(DEV_LAMBDA_FUNCTION)
AWS_REGION       ?= $(DEV_AWS_REGION)
LAMBDA_ROLE      ?= $(DEV_LAMBDA_ROLE)
endif

# ECR registry and repository path
ECR_REGISTRY := $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com
ECR_REPO     := $(ECR_REGISTRY)/$(REPO_NAME)

# Default target
.PHONY: help
help:
	@echo "HCA Validation Tools Makefile"
	@echo ""
	@echo "Available targets:"
	@echo "  validate-schema  - Validate all schema files"
	@echo "  validate         - Validate a specific schema (make validate FILE=relative/path)"
	@echo "  validate-core    - Validate core schema"
	@echo "  validate-dataset - Validate dataset schema"
	@echo "  validate-donor   - Validate donor schema"
	@echo "  validate-sample  - Validate sample schema"
	@echo "  validate-cell    - Validate cell schema"
	@echo "  validate-verbose - Validate dataset schema with warnings"
	@echo "  lint-schema      - Run LinkML linter on all schema files"
	@echo "  lint-schema-errors - Run LinkML linter (critical errors only)"
	@echo "  gen-schema - Generate derived models from LinkML schema"
	@echo "  generate-data-dictionary - Generate data dictionary JSON from core schema to standard path"
	@echo "  generate-data-dictionary-file - Generate data dictionary from schema to specified file"
	@echo "  test-dataset-validation - Run dataset validation tests"
	@echo "  test-entry-sheet       - Run entry sheet validator tests"
	@echo "  test-all               - Run all tests"
	@echo "  build-lambda-container - Build the entry sheet validator Lambda container image"
	@echo "  deploy-lambda-container - Deploy the Lambda container image to AWS"
	@echo "  test-lambda-container  - Test the Lambda container locally (uses .env for credentials)"
	@echo "  test-lambda            - Alias for test-lambda-container"
	@echo "  invoke-lambda          - Invoke the deployed Lambda function"
	@echo "  help                   - Show this help message"

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

# Validate a specific schema file: make validate FILE=dataset or FILE=bionetwork/gut
.PHONY: validate
validate:
	@if [ -z "$(FILE)" ]; then echo "Usage: make validate FILE=<schema-relative-path (without .yaml)>"; exit 1; fi
	@echo "Validating $(FILE).yaml..."
	@$(POETRY) gen-yaml $(SCHEMA_DIR)/$(FILE).yaml > /dev/null $(SUPPRESS_WARNINGS) || (echo "❌ $(FILE) schema validation failed" && exit 1)
	@echo "✓ $(FILE) schema is valid"

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

# Generate derived models from schema
.PHONY: gen-schema
gen-schema:
	@echo "Generating models..."
	@$(POETRY) gen-pydantic src/hca_validation/schema/core.yaml --meta AUTO > src/hca_validation/schema/generated/core.py
	@echo "Done"

# Run validator tests
.PHONY: test-validator
test-validator:
	@echo "Running validator tests..."
	@$(POETRY) pytest tests/test_validator.py -v -W ignore::DeprecationWarning

# Run entry sheet validator tests
.PHONY: test-entry-sheet
test-entry-sheet:
	@echo "Running entry sheet validator tests..."
	@$(POETRY) pytest tests/test_entry_sheet_validator.py -v -W ignore::DeprecationWarning

# Run all tests
.PHONY: test-all
test-all:
	@echo "Running all tests..."
	@$(POETRY) pytest tests/ -v -W ignore::DeprecationWarning

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

# Lambda function targets (Docker-based)
.PHONY: build-lambda-container
build-lambda-container:
	@echo "Building Lambda container image..."
	@./deployment/docker-build/build_lambda_container.sh $(PROFILE)
	@echo "✓ Lambda container image built: hca-entry-sheet-validator"

.PHONY: test-lambda-container
test-lambda-container:
	@echo "Running pytest smoke test against Lambda container..."
	@$(POETRY) pytest tests/test_lambda_container_smoke.py -v


.PHONY: deploy-lambda-container
deploy-lambda-container:
	@if [ -z "$(AWS_ACCOUNT_ID)" ]; then \
		echo "Error: AWS_ACCOUNT_ID is not set (check .env.make or your environment)"; \
		exit 1; \
	fi
	@if [ "$(ENV)" = "prod" ]; then \
		echo "******** DEPLOYING TO PRODUCTION ********"; \
	else \
		echo "******** DEPLOYING TO DEVELOPMENT ********"; \
	fi
	@echo "Validating required environment variables: AWS_REGION and LAMBDA_ROLE..."
	@if [ -z "$(AWS_REGION)" ]; then \
		echo "Error: AWS_REGION environment variable is not set and could not be derived from .env.make"; \
		exit 1; \
	fi
	@if [ -z "$(LAMBDA_ROLE)" ]; then \
		echo "Error: LAMBDA_ROLE is required (set in .env.make)"; \
		exit 1; \
	fi

	@echo "Logging in to ECR..."
	@aws ecr get-login-password --region $(AWS_REGION) | docker login --username AWS --password-stdin $(ECR_REGISTRY)

	@echo "Creating ECR repository if it doesn't exist..."
	@aws ecr describe-repositories --repository-names $(REPO_NAME) --region $(AWS_REGION) > /dev/null 2>&1 || \
		aws ecr create-repository --repository-name $(REPO_NAME) --region $(AWS_REGION)

	@echo "Tagging and pushing container image to ECR..."
	@docker tag hca-entry-sheet-validator:latest $(ECR_REPO):latest
	@docker push $(ECR_REPO):latest

	@echo "Deploying Lambda function..."
	@if aws lambda get-function --function-name $(LAMBDA_FUNCTION) --region $(AWS_REGION) > /dev/null 2>&1; then \
		echo "Updating existing Lambda function..."; \
		aws lambda update-function-code \
			--function-name $(LAMBDA_FUNCTION) \
			--image-uri $(ECR_REPO):latest \
			--region $(AWS_REGION); \
	else \
		echo "Creating new Lambda function..."; \
		aws lambda create-function \
			--function-name $(LAMBDA_FUNCTION) \
			--package-type Image \
			--code ImageUri=$(ECR_REPO):latest \
			--role $(LAMBDA_ROLE) \
			--timeout 30 \
			--memory-size 256 \
			--region $(AWS_REGION); \
	fi
	@echo "✓ Lambda function deployed successfully as container image"

# Test Lambda function locally
.PHONY: test-lambda
test-lambda: test-lambda-container
	@echo "Redirecting to test-lambda-container target"

.PHONY: invoke-lambda
invoke-lambda:
	@echo "Invoking Lambda function..."
	@if [ -z "$(AWS_REGION)" ]; then \
		echo "Error: AWS_REGION environment variable is not set"; \
		exit 1; \
	fi
	@if [ -z "$(SHEET_ID)" ]; then \
		aws lambda invoke \
			--function-name $(LAMBDA_FUNCTION) \
			--region $(AWS_REGION) \
			--payload '{}' \
			response.json; \
	else \
		aws lambda invoke \
			--function-name $(LAMBDA_FUNCTION) \
			--region $(AWS_REGION) \
			--payload '{"sheet_id": "$(SHEET_ID)"}' \
			response.json; \
	fi
	@echo "Response saved to response.json"
	@cat response.json
