# Dataset Validator Service Makefile
# Runs in the dataset-validator Poetry environment

.DEFAULT_GOAL := help
POETRY := poetry


.PHONY: help
help:
	@echo "Dataset Validator Service Commands:"
	@echo "  install     - Install dependencies"
	@echo "  test        - Run tests"
	@echo "  test-docker - Run Docker container smoke tests"
	@echo "  run         - Run the dataset validator"
	@echo "  build       - Build Docker container"
	@echo "  ecr-login   - Login Docker to AWS ECR (PROFILE/AWS_REGION required)"
	@echo "  build-batch - Build AWS Batch container for linux/amd64 (uses deployment/Dockerfile)"
	@echo "  tag-batch   - Tag local image for ECR (uses TAG, AWS_ACCOUNT_ID, AWS_REGION, ECR_REPO)"
	@echo "  push-batch  - Push tagged image to ECR"
	@echo "  publish-batch - Convenience: login, build-batch, tag-batch, push-batch"
	@echo "  register-jd - Register a new AWS Batch Job Definition revision (uses TAG)"
	@echo "  submit-job  - Submit a job to the Batch queue using latest JD revision"
	@echo "  clean       - Clean up artifacts"

.PHONY: install
install:
	@echo "Installing dataset-validator dependencies..."
	@$(POETRY) install

.PHONY: test
test:
	@echo "Running dataset-validator tests..."
	@$(POETRY) run pytest tests/ -v

.PHONY: test-docker
test-docker:
	@echo "Running dataset-validator Docker smoke tests..."
	@$(POETRY) run pytest tests/test_docker_smoke.py -v

.PHONY: run
run:
	@echo "Running dataset validator..."
	@$(POETRY) run python src/dataset_validator/main.py

.PHONY: build
build:
	@echo "Building dataset-validator Docker container..."
	@cd ../.. && docker build -f deployment/dataset-validator/Dockerfile -t hca-dataset-validator:latest .

# ----- AWS Batch ECR publishing helpers -----
# Defaults can be overridden on the command line by the root Makefile.

SHA := $(shell git rev-parse --short HEAD)
TAG ?= $(SHA)
PROFILE ?=
AWS_REGION ?=
DOCKER_REGISTRY := $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com
LOCAL_IMAGE ?= validator-batch:$(TAG)
REMOTE_IMAGE := $(DOCKER_REGISTRY)/$(ECR_REPO):$(TAG)

.PHONY: ecr-login
ecr-login:
	@if [ -z "$(PROFILE)" ] || [ -z "$(AWS_REGION)" ] || [ -z "$(AWS_ACCOUNT_ID)" ]; then \
		echo "Error: PROFILE, AWS_REGION, and AWS_ACCOUNT_ID are required"; \
		echo "Example: make ecr-login PROFILE=excira AWS_REGION=us-east-1 AWS_ACCOUNT_ID=123456789012"; \
		exit 1; \
	fi
	@aws ecr get-login-password --profile $(PROFILE) --region $(AWS_REGION) | docker login --username AWS --password-stdin $(DOCKER_REGISTRY)

.PHONY: build-batch
build-batch:
	@echo "Building AWS Batch image for linux/amd64: $(LOCAL_IMAGE)"
	@cd ../.. && docker build --platform linux/amd64 -f deployment/dataset-validator/Dockerfile -t $(LOCAL_IMAGE) .

.PHONY: tag-batch
tag-batch:
	@if [ -z "$(AWS_ACCOUNT_ID)" ] || [ -z "$(AWS_REGION)" ] || [ -z "$(ECR_REPO)" ]; then \
		echo "Error: AWS_ACCOUNT_ID, AWS_REGION, and ECR_REPO are required"; \
		exit 1; \
	fi
	@echo "Tagging $(LOCAL_IMAGE) as $(REMOTE_IMAGE)"
	@docker tag $(LOCAL_IMAGE) $(REMOTE_IMAGE)

.PHONY: push-batch
push-batch:
	@if [ -z "$(AWS_ACCOUNT_ID)" ] || [ -z "$(AWS_REGION)" ] || [ -z "$(ECR_REPO)" ]; then \
		echo "Error: AWS_ACCOUNT_ID, AWS_REGION, and ECR_REPO are required"; \
		exit 1; \
	fi
	@echo "Pushing $(REMOTE_IMAGE)"
	@docker push $(REMOTE_IMAGE)

.PHONY: publish-batch
publish-batch: ecr-login build-batch tag-batch push-batch
 

# ----- AWS Batch Job Definition and Submission -----
# Variables must be provided by the root Makefile or CLI:
#   JOB_DEF_NAME, JOB_QUEUE, LOG_GROUP, EXEC_ROLE_ARN, TASK_ROLE_ARN, VCPU, MEMORY
JOB_NAME ?= validator-smoke

.PHONY: register-jd
register-jd:
	@if [ -z "$(PROFILE)" ] || [ -z "$(AWS_REGION)" ] || [ -z "$(AWS_ACCOUNT_ID)" ] || [ -z "$(TAG)" ]; then \
		echo "Error: PROFILE, AWS_REGION, AWS_ACCOUNT_ID, and TAG are required"; \
		echo "Example: make register-jd PROFILE=excira AWS_REGION=us-east-1 AWS_ACCOUNT_ID=123456789012 TAG=dev-abcdef1"; \
		exit 1; \
	fi
	@if [ -z "$(ECR_REPO)" ] || [ -z "$(JOB_DEF_NAME)" ] || [ -z "$(LOG_GROUP)" ] || [ -z "$(EXEC_ROLE_ARN)" ] || [ -z "$(TASK_ROLE_ARN)" ] || [ -z "$(VCPU)" ] || [ -z "$(MEMORY)" ]; then \
		echo "Error: ECR_REPO, JOB_DEF_NAME, LOG_GROUP, EXEC_ROLE_ARN, TASK_ROLE_ARN, VCPU, and MEMORY are required"; \
		exit 1; \
	fi
	@echo "Registering Job Definition $(JOB_DEF_NAME) with image $(DOCKER_REGISTRY)/$(ECR_REPO):$(TAG)"
	@aws batch register-job-definition \
		--profile $(PROFILE) \
		--region $(AWS_REGION) \
		--job-definition-name $(JOB_DEF_NAME) \
		--type container \
		--platform-capabilities FARGATE \
		--container-properties "{\"image\":\"$(DOCKER_REGISTRY)/$(ECR_REPO):$(TAG)\",\"executionRoleArn\":\"$(EXEC_ROLE_ARN)\",\"jobRoleArn\":\"$(TASK_ROLE_ARN)\",\"logConfiguration\":{\"logDriver\":\"awslogs\",\"options\":{\"awslogs-group\":\"$(LOG_GROUP)\",\"awslogs-region\":\"$(AWS_REGION)\",\"awslogs-stream-prefix\":\"validator\"}},\"resourceRequirements\":[{\"type\":\"VCPU\",\"value\":\"$(VCPU)\"},{\"type\":\"MEMORY\",\"value\":\"$(MEMORY)\"}],\"networkConfiguration\":{\"assignPublicIp\":\"DISABLED\"}}"

.PHONY: submit-job
submit-job:
	@if [ -z "$(PROFILE)" ] || [ -z "$(AWS_REGION)" ]; then \
		echo "Error: PROFILE and AWS_REGION are required"; \
		echo "Example: make submit-job PROFILE=excira AWS_REGION=us-east-1"; \
		exit 1; \
	fi
	@if [ -z "$(JOB_QUEUE)" ] || [ -z "$(JOB_DEF_NAME)" ]; then \
		echo "Error: JOB_QUEUE and JOB_DEF_NAME are required"; \
		exit 1; \
	fi
	@echo "Submitting job to $(JOB_QUEUE) using JD $(JOB_DEF_NAME)"
	@job_name="$(JOB_NAME)-$$(date +%s)"; \
	aws batch submit-job \
		--profile $(PROFILE) \
		--region $(AWS_REGION) \
		--job-name "$$job_name" \
		--job-queue $(JOB_QUEUE) \
		--job-definition $(JOB_DEF_NAME) \
		--container-overrides "environment=[{name=BATCH_JOB_NAME,value=$$job_name}]"


.PHONY: clean
clean:
	@echo "Cleaning dataset-validator artifacts..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@rm -rf .pytest_cache 2>/dev/null || true
