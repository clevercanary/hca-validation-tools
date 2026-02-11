# HCA Validation Tools Makefile
# This Makefile provides commands for validating LinkML schemas

# Variables
SCHEMA_DIR := src/hca_validation/schema
SCHEMAS := $(wildcard shared/$(SCHEMA_DIR)/*.yaml)
POETRY := cd shared && poetry run
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

# ----- Batch environment settings (mapped from .env.make) -----
ifeq ($(ENV),prod)
BATCH_PROFILE        ?= $(PROD_BATCH_PROFILE)
BATCH_AWS_REGION     ?= $(PROD_BATCH_AWS_REGION)
BATCH_AWS_ACCOUNT_ID ?= $(PROD_BATCH_AWS_ACCOUNT_ID)
BATCH_ECR_REPO       ?= $(PROD_BATCH_ECR_REPO)
BATCH_JOB_DEF_NAME   ?= $(PROD_BATCH_JOB_DEF_NAME)
BATCH_JOB_QUEUE      ?= $(PROD_BATCH_JOB_QUEUE)
BATCH_LOG_GROUP      ?= $(PROD_BATCH_LOG_GROUP)
BATCH_EXEC_ROLE_ARN  ?= $(PROD_BATCH_EXEC_ROLE_ARN)
BATCH_TASK_ROLE_ARN  ?= $(PROD_BATCH_TASK_ROLE_ARN)
BATCH_VCPU           ?= $(PROD_BATCH_VCPU)
BATCH_MEMORY         ?= $(PROD_BATCH_MEMORY)
BATCH_EPHEMERAL_STORAGE ?= $(PROD_BATCH_EPHEMERAL_STORAGE)
else # dev
BATCH_PROFILE        ?= $(DEV_BATCH_PROFILE)
BATCH_AWS_REGION     ?= $(DEV_BATCH_AWS_REGION)
BATCH_AWS_ACCOUNT_ID ?= $(DEV_BATCH_AWS_ACCOUNT_ID)
BATCH_ECR_REPO       ?= $(DEV_BATCH_ECR_REPO)
BATCH_JOB_DEF_NAME   ?= $(DEV_BATCH_JOB_DEF_NAME)
BATCH_JOB_QUEUE      ?= $(DEV_BATCH_JOB_QUEUE)
BATCH_LOG_GROUP      ?= $(DEV_BATCH_LOG_GROUP)
BATCH_EXEC_ROLE_ARN  ?= $(DEV_BATCH_EXEC_ROLE_ARN)
BATCH_TASK_ROLE_ARN  ?= $(DEV_BATCH_TASK_ROLE_ARN)
BATCH_VCPU           ?= $(DEV_BATCH_VCPU)
BATCH_MEMORY         ?= $(DEV_BATCH_MEMORY)
BATCH_EPHEMERAL_STORAGE ?= $(DEV_BATCH_EPHEMERAL_STORAGE)
endif

# ECR registry and repository path
ECR_REGISTRY := $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com
ECR_REPO     := $(ECR_REGISTRY)/$(REPO_NAME)

# Default target
.PHONY: help
help:
	@echo "HCA Validation Tools - Multi-Service Architecture"
	@echo ""
	@echo "Multi-Service Orchestration:"
	@echo "  build-all              - Build all services (shared + Lambda container)"
	@echo "  test-all               - Run all tests across services"
	@echo ""
	@echo "Lambda Service (Entry Sheet Validator):"
	@echo "  build-lambda-container - Build the entry sheet validator Lambda container image"
	@echo "  deploy-lambda-container - Deploy the Lambda container image to AWS"
	@echo "  test-lambda-container  - Test the Lambda container locally"
	@echo "  test-lambda            - Alias for test-lambda-container"
	@echo "  invoke-lambda          - Invoke the deployed Lambda function"
	@echo ""
	@echo "Batch (Dataset Validator):"
	@echo "  batch-publish-container - Build, tag, push image to ECR, then register JD (on success)"
	@echo "  batch-register-jd       - Register a new Job Definition revision using the pushed tag"
	@echo "  batch-submit-job        - Submit a job to the configured Job Queue"
	@echo ""
	@echo "Service-Specific Commands:"
	@echo "  cd shared && make help                           - Shared library tasks"
	@echo "  cd services/entry-sheet-validator && make help  - Lambda service tasks"
	@echo "  cd services/dataset-validator && make help      - Dataset validator tasks"
	@echo ""
	@echo "  help                   - Show this help message"

# Lambda function targets (Docker-based) - delegate to service
.PHONY: build-lambda-container
build-lambda-container:
	@$(MAKE) -C services/entry-sheet-validator build-lambda-container PROFILE=$(PROFILE)

.PHONY: test-lambda-container
test-lambda-container:
	@$(MAKE) -C services/entry-sheet-validator test-lambda-container


.PHONY: deploy-lambda-container
deploy-lambda-container:
	@$(MAKE) -C services/entry-sheet-validator deploy-lambda-container \
		AWS_ACCOUNT_ID=$(AWS_ACCOUNT_ID) \
		AWS_REGION=$(AWS_REGION) \
		LAMBDA_FUNCTION=$(LAMBDA_FUNCTION) \
		LAMBDA_ROLE=$(LAMBDA_ROLE) \
		REPO_NAME=$(REPO_NAME) \
		ECR_REGISTRY=$(ECR_REGISTRY) \
		ECR_REPO=$(ECR_REPO) \
		ENV=$(ENV)

# ----- Batch orchestrator targets (delegate to dataset-validator service) -----
.PHONY: batch-publish-container
batch-publish-container:
	@$(MAKE) -C services/dataset-validator publish-batch \
		PROFILE=$(BATCH_PROFILE) \
		AWS_REGION=$(BATCH_AWS_REGION) \
		AWS_ACCOUNT_ID=$(BATCH_AWS_ACCOUNT_ID) \
		ECR_REPO=$(BATCH_ECR_REPO) \
		$(if $(TAG),TAG=$(TAG))
	@$(MAKE) -C services/dataset-validator register-jd \
		PROFILE=$(BATCH_PROFILE) \
		AWS_REGION=$(BATCH_AWS_REGION) \
		AWS_ACCOUNT_ID=$(BATCH_AWS_ACCOUNT_ID) \
		ECR_REPO=$(BATCH_ECR_REPO) \
		JOB_DEF_NAME=$(BATCH_JOB_DEF_NAME) \
		LOG_GROUP=$(BATCH_LOG_GROUP) \
		EXEC_ROLE_ARN=$(BATCH_EXEC_ROLE_ARN) \
		TASK_ROLE_ARN=$(BATCH_TASK_ROLE_ARN) \
		VCPU=$(BATCH_VCPU) \
		MEMORY=$(BATCH_MEMORY) \
		EPHEMERAL_STORAGE=$(BATCH_EPHEMERAL_STORAGE) \
		$(if $(TAG),TAG=$(TAG))

.PHONY: batch-register-jd
batch-register-jd:
	@$(MAKE) -C services/dataset-validator register-jd \
		PROFILE=$(BATCH_PROFILE) \
		AWS_REGION=$(BATCH_AWS_REGION) \
		AWS_ACCOUNT_ID=$(BATCH_AWS_ACCOUNT_ID) \
		ECR_REPO=$(BATCH_ECR_REPO) \
		JOB_DEF_NAME=$(BATCH_JOB_DEF_NAME) \
		LOG_GROUP=$(BATCH_LOG_GROUP) \
		EXEC_ROLE_ARN=$(BATCH_EXEC_ROLE_ARN) \
		TASK_ROLE_ARN=$(BATCH_TASK_ROLE_ARN) \
		VCPU=$(BATCH_VCPU) \
		MEMORY=$(BATCH_MEMORY) \
		EPHEMERAL_STORAGE=$(BATCH_EPHEMERAL_STORAGE)

.PHONY: batch-submit-job
batch-submit-job:
	@$(MAKE) -C services/dataset-validator submit-job \
		PROFILE=$(BATCH_PROFILE) \
		AWS_REGION=$(BATCH_AWS_REGION) \
		JOB_QUEUE=$(BATCH_JOB_QUEUE) \
		JOB_DEF_NAME=$(BATCH_JOB_DEF_NAME)

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

# Multi-service orchestration targets
.PHONY: build-all
build-all:
	@echo "Running full multi-service build & test chain..."
	@$(MAKE) -C shared build
	@$(MAKE) -C services/entry-sheet-validator build-lambda-container PROFILE=excira
	@$(MAKE) -C services/dataset-validator build
	@$(MAKE) test-all
	@echo "✓ All services built and tested successfully"

.PHONY: test-all
test-all:
	@echo "Running all tests across services..."
	@$(MAKE) -C shared test-shared
	@$(MAKE) -C services/entry-sheet-validator test-lambda-container
	@$(MAKE) -C services/dataset-validator test
	@$(MAKE) -C services/cellxgene-validator test
	@$(MAKE) -C services/hca-schema-validator test
	@echo "✓ All tests passed"
