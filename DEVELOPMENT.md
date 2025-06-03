# HCA Validation Tools Development Guide

## Project Structure

The HCA Validation Tools project follows a src-based layout:

```
src/hca_validation/
├── entry_sheet_validator/ - Validates entry sheets against schemas
├── data_dictionary/ - Generates data dictionaries from schemas
├── lambda_functions/ - AWS Lambda deployment for validators
└── schema/ - LinkML schema definitions
```

## Key Commands

### Building and Testing

```bash
# Build the Lambda container
make build-lambda-container

# Test the Lambda container locally
make test-lambda-container

# Deploy the Lambda container to AWS
make deploy-lambda-container

# Run the validation on a Google Sheet
make validate-sheet-id SHEET_ID=your-sheet-id
```

### Schema Management

```bash
# Validate all schemas
make validate-schema

# Generate derived schema models (e.g. Pydantic classes)
make gen-schema

# Generate data dictionary
make generate-data-dictionary
```

## Development Workflow

1. Make changes to the code or schemas
2. Run appropriate validation tests
3. Build and test locally
4. Deploy to AWS when ready

## Dependencies

This project uses Poetry for dependency management:

```bash
# Install dependencies
poetry install

# Add a new dependency
poetry add package-name

# Update dependencies
poetry update
```

## Testing

Tests are located in the `tests/` directory and can be run with:

```bash
poetry run pytest
```
