# HCA Schema Validator Service Makefile
# Runs in the hca-schema-validator service's uv environment

.DEFAULT_GOAL := help
UV := uv


.PHONY: help
help:
	@echo "HCA Schema Validator Service Commands:"
	@echo "  install     - Install dependencies"
	@echo "  test        - Run tests"
	@echo "  clean       - Clean up artifacts"

.PHONY: install
install:
	@echo "Installing hca-schema-validator dependencies..."
	@$(UV) sync

.PHONY: test
test:
	@echo "Running hca-schema-validator tests..."
	@$(UV) run pytest tests/ -v


.PHONY: clean
clean:
	@echo "Cleaning hca-schema-validator artifacts..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@rm -rf .pytest_cache 2>/dev/null || true
