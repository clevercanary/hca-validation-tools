.PHONY: help build test clean

help:
	@echo "Available targets:"
	@echo "  build  - Build the package with Poetry"
	@echo "  test   - Run tests with pytest"
	@echo "  clean  - Remove Python cache files and build artifacts"

# Build the package
build:
	poetry build

# Run tests
test:
	poetry run pytest tests/ -v

# Clean up Python cache and build artifacts
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf dist/ build/ .pytest_cache/
