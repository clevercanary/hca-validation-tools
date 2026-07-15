# CELLxGENE Validator Service Makefile
# Runs in the cellxgene-validator uv environment

.DEFAULT_GOAL := help
UV := uv


.PHONY: help
help:
	@echo "CELLxGENE Validator Service Commands:"
	@echo "  install     - Install dependencies"
	@echo "  test        - Run tests"
	@echo "  clean       - Clean up artifacts"

.PHONY: install
install:
	@echo "Installing cellxgene-validator dependencies..."
	@$(UV) sync

.PHONY: test
test:
	@echo "Running cellxgene-validator tests..."
	@$(UV) run pytest tests/ -v


.PHONY: clean
clean:
	@echo "Cleaning dataset-validator artifacts..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@rm -rf .pytest_cache 2>/dev/null || true
