# Entry Sheet Validator Service Makefile
# Tasks specific to the entry sheet validator Lambda service

# Variables
POETRY := poetry run

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
	@$(POETRY) pytest tests/test_lambda_container_smoke.py -v

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

	@echo "Checking that ECR repository $(REPO_NAME) exists..."
	@aws ecr describe-repositories --repository-names $(REPO_NAME) --region $(AWS_REGION) > /dev/null 2>&1 || { \
		echo "Error: ECR repository $(REPO_NAME) not found in account $(AWS_ACCOUNT_ID). Please create it manually before deploying."; \
		exit 1; \
	}

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
