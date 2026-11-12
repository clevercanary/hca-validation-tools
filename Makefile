# HCA Validation Tools Makefile
# This Makefile orchestrates the multi-service build; schema targets live in packages/hca-metadata-schema/Makefile
# (shared/Makefile forwards to them).

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
override ENV_PREFIX := PROD
AWS_ACCOUNT_ID   ?= $(PROD_AWS_ACCOUNT_ID)
REPO_NAME        ?= $(PROD_REPO_NAME)
LAMBDA_FUNCTION  ?= $(PROD_LAMBDA_FUNCTION)
AWS_REGION       ?= $(PROD_AWS_REGION)
LAMBDA_DEPLOY_PROFILE ?= $(PROD_LAMBDA_DEPLOY_PROFILE)
else # dev
override ENV_PREFIX := DEV
AWS_ACCOUNT_ID   ?= $(DEV_AWS_ACCOUNT_ID)
REPO_NAME        ?= $(DEV_REPO_NAME)
LAMBDA_FUNCTION  ?= $(DEV_LAMBDA_FUNCTION)
AWS_REGION       ?= $(DEV_AWS_REGION)
LAMBDA_DEPLOY_PROFILE ?= $(DEV_LAMBDA_DEPLOY_PROFILE)
endif

# AWS CLI profile for the entry-sheet Lambda build (fetches the Extension
# layer). The build is env-agnostic — it produces one image — so this is a
# single profile, not dev/prod. From LAMBDA_PROFILE in .env.make; override
# with PROFILE=... .
PROFILE ?= $(LAMBDA_PROFILE)

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

# Arguments for the dataset-validator publish-batch and register-jd sub-makes.
override BATCH_JD_ARGS = \
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

# invoke-lambda's aws call goes through this; override stops a command-line
# LAMBDA_AWS=... dropping the profile.
override LAMBDA_AWS = aws --profile $(LAMBDA_DEPLOY_PROFILE)

# Deploy, invoke and Batch profiles may only come from .env.make. Stops the
# target when PROFILE, $(1) or $(ENV_PREFIX)_$(1) is set on the command line
# or in the environment. Root targets only: the service Makefiles receive
# PROFILE on their command line by design.
require_env_make_profile = $(foreach v,PROFILE $(1) $(ENV_PREFIX)_$(1),$(if $(filter command environment,$(firstword $(origin $(v)))),$(error $(v) comes from the $(origin $(v)); a deploy profile may only come from .env.make: set $(ENV_PREFIX)_$(1) there)))

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
	@$(call require_env_make_profile,LAMBDA_DEPLOY_PROFILE)
	@$(MAKE) -C services/entry-sheet-validator deploy-lambda-container \
		PROFILE=$(LAMBDA_DEPLOY_PROFILE) \
		AWS_ACCOUNT_ID=$(AWS_ACCOUNT_ID) \
		AWS_REGION=$(AWS_REGION) \
		LAMBDA_FUNCTION=$(LAMBDA_FUNCTION) \
		REPO_NAME=$(REPO_NAME) \
		ECR_REGISTRY=$(ECR_REGISTRY) \
		ECR_REPO=$(ECR_REPO) \
		ENV=$(ENV)

# ----- Batch orchestrator targets (delegate to dataset-validator service) -----
.PHONY: batch-publish-container
batch-publish-container:
	@$(call require_env_make_profile,BATCH_PROFILE)
	@$(MAKE) -C services/dataset-validator publish-batch $(BATCH_JD_ARGS) \
		$(if $(TAG),TAG=$(TAG))
	@$(MAKE) -C services/dataset-validator register-jd $(BATCH_JD_ARGS) \
		$(if $(TAG),TAG=$(TAG))

.PHONY: batch-register-jd
batch-register-jd:
	@$(call require_env_make_profile,BATCH_PROFILE)
	@$(MAKE) -C services/dataset-validator register-jd $(BATCH_JD_ARGS)

.PHONY: batch-submit-job
batch-submit-job:
	@$(call require_env_make_profile,BATCH_PROFILE)
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
	@$(call require_env_make_profile,LAMBDA_DEPLOY_PROFILE)
	@echo "Invoking Lambda function..."
	@if [ -z "$(LAMBDA_DEPLOY_PROFILE)" ] || [ -z "$(LAMBDA_FUNCTION)" ] || [ -z "$(AWS_REGION)" ]; then \
		echo "Error: LAMBDA_DEPLOY_PROFILE, LAMBDA_FUNCTION and AWS_REGION are required"; \
		echo "Set $(ENV_PREFIX)_LAMBDA_DEPLOY_PROFILE, $(ENV_PREFIX)_LAMBDA_FUNCTION and $(ENV_PREFIX)_AWS_REGION in .env.make"; \
		exit 1; \
	fi
	@out=$$($(LAMBDA_AWS) lambda invoke \
		--function-name $(LAMBDA_FUNCTION) \
		--region $(AWS_REGION) \
		--cli-binary-format raw-in-base64-out \
		--payload '$(if $(SHEET_ID),{"sheet_id": "$(SHEET_ID)"},{})' \
		--output json \
		response.json) || exit $$?; \
	echo "$$out"; \
	echo "Response saved to response.json"; \
	cat response.json; \
	if printf '%s' "$$out" | grep -q '"FunctionError"'; then \
		echo; echo "Error: the Lambda function raised an error; see response.json"; \
		exit 1; \
	fi

# Multi-service orchestration targets
.PHONY: build-all
build-all:
	@echo "Running full multi-service build & test chain..."
	@$(MAKE) -C shared build
	@$(MAKE) -C services/entry-sheet-validator build-lambda-container PROFILE=$(PROFILE)
	@$(MAKE) -C services/dataset-validator build
	@$(MAKE) test-all
	@echo "✓ All services built and tested successfully"

.PHONY: test-all
test-all:
	@echo "Running all tests across services..."
	@$(MAKE) -C packages/hca-metadata-schema test
	@$(MAKE) -C shared test-shared
	@$(MAKE) -C services/entry-sheet-validator test-lambda-container
	@$(MAKE) -C services/dataset-validator test
	@$(MAKE) -C services/cellxgene-validator test
	@$(MAKE) -C services/hca-schema-validator test
	@echo "✓ All tests passed"

.PHONY: typecheck
typecheck:
	@echo "Running pyright (hca-metadata-schema, hca-anndata-tools, hca-anndata-mcp)..."
	@cd packages/hca-anndata-mcp && uv run pyright --project ../.. ../hca-metadata-schema/src ../hca-anndata-tools/src ../hca-anndata-mcp/src
	@echo "Running pyright (hca-tracker-client, hca-tracker-mcp)..."
	@cd packages/hca-tracker-mcp && uv run pyright --project ../.. ../hca-tracker-client/src ../hca-tracker-mcp/src
	@echo "Running pyright (hca-schema-validator)..."
	@cd packages/hca-schema-validator && uv run pyright --project ../.. src
	@echo "Running pyright (dataset-validator)..."
	@cd services/dataset-validator && uv run pyright --project ../../ src
	@echo "Running pyright (hca-schema-validator service)..."
	@cd services/hca-schema-validator && uv run pyright --project ../../ src
