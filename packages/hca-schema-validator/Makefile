.PHONY: help build test test-wheel clean

help:
	@echo "Available targets:"
	@echo "  build      - Build the package with uv"
	@echo "  test       - Run tests with pytest"
	@echo "  test-wheel - Build wheel, install in temp venv, run tests"
	@echo "  clean      - Remove Python cache files and build artifacts"

# Build the package
build:
	uv build

# Run tests
test:
	uv run pytest tests/ -v

# Build wheel and run tests against the installed package
test-wheel:
	@echo "Building wheel..."
	uv build --wheel
	@echo "Creating temp venv and installing wheel..."
	python3 -m venv /tmp/hca-test-wheel
	/tmp/hca-test-wheel/bin/pip install --quiet dist/hca_schema_validator-*.whl pytest
	@echo "Running tests against installed wheel..."
	/tmp/hca-test-wheel/bin/python -m pytest tests/ -v
	@echo "Cleaning up..."
	rm -rf /tmp/hca-test-wheel dist/

# Clean up Python cache and build artifacts
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf dist/ build/ .pytest_cache/
