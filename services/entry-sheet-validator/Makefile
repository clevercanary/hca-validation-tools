# Entry Sheet Validator Service Makefile
# Tasks specific to the entry sheet validator Lambda service

# Variables
UV := uv run

# The image is tagged with the HEAD commit SHA so a running Lambda can always be
# traced back to a commit (see #484). TAG can be overridden but defaults to HEAD.
SHA := $(shell git rev-parse --short HEAD)
TAG ?= $(SHA)

.PHONY: help
help:
	@echo "Entry Sheet Validator Service Tasks:"
	@echo "  test-lambda-container  - Test the Lambda container locally (uses .env for credentials)"
	@echo "  test-lambda            - Alias for test-lambda-container"
	@echo "  build-lambda-container - Build the entry sheet validator Lambda container image"
	@echo "  deploy-lambda-container - Deploy the Lambda container image to AWS"

# Test Lambda function locally
.PHONY: test-lambda-container
test-lambda-container:
	@echo "Running pytest smoke test against Lambda container..."
	@$(UV) pytest tests/test_lambda_container_smoke.py -v

# Test Lambda function locally
.PHONY: test-lambda
test-lambda: test-lambda-container
	@echo "Redirecting to test-lambda-container target"

# Lambda function targets (Docker-based)
.PHONY: build-lambda-container
build-lambda-container:
	@echo "Building Lambda container image..."
	@cd ../.. && ./deployment/entry-sheet-validator/build_lambda_container.sh $(PROFILE)
	@echo "✓ Lambda container image built: hca-entry-sheet-validator"

# Refuses to publish an image whose tag would misdescribe its contents. `docker
# build` copies from the working tree, but TAG defaults to the HEAD commit — so a
# dirty tree produces an image tagged with a commit that does not contain what is
# inside it, and checking out that SHA rebuilds something different.
#
# NOTE: this guard is deliberately DUPLICATED from services/dataset-validator's
# Makefile for #474. It is slated to be extracted into a shared make include as
# part of #475 (which re-verifies the Batch deploy path anyway) — do not "fix"
# the duplication here in isolation.
#
# Three things below are load-bearing and look optional:
#
#   --untracked-files=all   `git status` honours status.showUntrackedFiles; a user
#                           who set it to `no` would get an empty listing and the
#                           guard would pass while shipping untracked files.
#
#   exit-status check       A bare `$(git status)` substitution is empty when git
#                           errors, and empty reads as clean — failing open in
#                           exactly the cases where provenance is unverifiable.
#
#   no TAG exemption        A hand-picked tag does not make unreproducible content
#                           acceptable, and exempting it would quietly become the
#                           override flag this guard is designed not to have.
#
# .dockerignore excludes *ignored* artifacts from the context, which is what makes
# `git status` a sufficient test — but it does not make this guard redundant: an
# untracked, non-ignored file reaches the image and git flags it `??`.
.PHONY: check-clean
check-clean:
	@if ! git rev-parse --git-dir >/dev/null 2>&1; then \
		echo "Error: not a git repository, so the tree cannot be verified."; \
		echo "  Refusing to publish an image whose provenance cannot be established."; \
		exit 1; \
	fi; \
	dirty=$$(git status --porcelain --untracked-files=all) || { \
		echo "Error: 'git status' failed, so the tree cannot be verified."; \
		echo "  Refusing to publish an image whose provenance cannot be established."; \
		exit 1; \
	}; \
	if [ -n "$$dirty" ]; then \
		echo "Error: refusing to publish from a dirty working tree."; \
		echo ""; \
		echo "  The image would contain these uncommitted changes, but be published"; \
		echo "  as :$(TAG), which does not have them. The tag would be a lie."; \
		echo ""; \
		printf '%s\n' "$$dirty" | sed 's/^/    /'; \
		echo ""; \
		echo "  Commit and merge first, then rebuild."; \
		exit 1; \
	fi

.PHONY: deploy-lambda-container
deploy-lambda-container: check-clean
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

	@echo "Checking that ECR repository $(REPO_NAME) exists..."
	@aws ecr describe-repositories --repository-names $(REPO_NAME) --region $(AWS_REGION) > /dev/null 2>&1 || { \
		echo "Error: ECR repository $(REPO_NAME) not found in account $(AWS_ACCOUNT_ID). Please create it manually before deploying."; \
		exit 1; \
	}

	@echo "Tagging and pushing container image to ECR as :$(TAG) (and :latest)..."
	@docker tag hca-entry-sheet-validator:latest $(ECR_REPO):$(TAG)
	@docker tag hca-entry-sheet-validator:latest $(ECR_REPO):latest
	@docker push $(ECR_REPO):$(TAG)
	@docker push $(ECR_REPO):latest

	@echo "Deploying Lambda function from the immutable :$(TAG) image..."
	@if aws lambda get-function --function-name $(LAMBDA_FUNCTION) --region $(AWS_REGION) > /dev/null 2>&1; then \
		echo "Updating existing Lambda function..."; \
		aws lambda update-function-code \
			--function-name $(LAMBDA_FUNCTION) \
			--image-uri $(ECR_REPO):$(TAG) \
			--region $(AWS_REGION); \
	else \
		echo "Creating new Lambda function..."; \
		aws lambda create-function \
			--function-name $(LAMBDA_FUNCTION) \
			--package-type Image \
			--code ImageUri=$(ECR_REPO):$(TAG) \
			--role $(LAMBDA_ROLE) \
			--timeout 30 \
			--memory-size 256 \
			--region $(AWS_REGION); \
	fi
	@echo "✓ Lambda function deployed successfully from image :$(TAG)"
