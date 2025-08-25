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

.PHONY: clean
clean:
	@echo "Cleaning dataset-validator artifacts..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@rm -rf .pytest_cache 2>/dev/null || true
