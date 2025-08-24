# HCA Validation Tools

A multi-service collection of tools for validating Human Cell Atlas (HCA) ingest data, built with LinkML schemas and deployed as AWS Lambda functions.

## Overview

This repository contains validation tools organized in a multi-service architecture:

- **Entry Sheet Validator**: Validates Google Sheets against LinkML schemas with AWS Lambda deployment
- **Data Dictionary Generator**: Creates data dictionaries from LinkML schema definitions
- **Schema Validation**: Validates LinkML schemas and generates Python models

## Project Structure

```
hca-validation-tools/
├── shared/                     # Shared library and schemas
│   ├── src/hca_validation/     # Core validation package
│   │   ├── entry_sheet_validator/  # Google Sheets validation
│   │   ├── data_dictionary/        # Dictionary generation
│   │   ├── validator/              # LinkML validation
│   │   └── schemas/                # LinkML schema definitions
│   └── tests/                  # Shared library tests
├── services/                   # Microservices
│   └── entry-sheet-validator/  # Lambda service for sheet validation
│       ├── src/                # Lambda function code
│       └── tests/              # Service-specific tests
├── deployment/                 # AWS deployment configurations
├── data_dictionaries/          # Generated data dictionaries
└── docs/                      # Documentation
```

## Quick Start

This project uses Poetry for dependency management and Make for build automation:

```bash
# Clone the repository
git clone https://github.com/your-org/hca-validation-tools.git
cd hca-validation-tools

# Build everything (schemas, data dictionaries, Docker images, run tests)
make build-all

# Or install shared library only
cd shared
poetry install --with dev
```

## Available Commands

### Build Commands
```bash
make build-all          # Build everything and run tests
make generate-schemas   # Generate Python models from LinkML schemas
make validate-schema    # Validate all LinkML schema files
make generate-data-dictionary  # Generate core data dictionary
make build-lambda-container    # Build Lambda Docker container
```

### Test Commands
```bash
make test-all          # Run all tests
make test-shared       # Run shared library tests only
make test-integration  # Run integration tests only (requires credentials)
make test-lambda-container     # Test Lambda container locally
```

### Deployment Commands
```bash
make deploy-lambda-dev   # Deploy to development environment
make deploy-lambda-prod  # Deploy to production environment
make test-lambda-dev     # Test deployed Lambda in development
```

## Configuration

### Environment Files
- **`.env`** - Contains `GOOGLE_SERVICE_ACCOUNT` credentials for Google Sheets API
- **`.env.make`** - Contains AWS deployment variables (account IDs, regions, etc.)

### Google Sheets Integration
To run integration tests or use the validator with private sheets:

1. Create a Google Service Account with Sheets API access
2. Download the service account JSON key
3. Add to `.env` file:
```bash
GOOGLE_SERVICE_ACCOUNT='{"type": "service_account", "project_id": "your-project", ...}'
```

## Development

### Multi-Service Architecture
- **`shared/`** - Core validation library used by all services
- **`services/entry-sheet-validator/`** - AWS Lambda service for sheet validation
- Each service has its own Poetry environment and test suite

### Adding New Services
1. Create new directory under `services/`
2. Add `pyproject.toml` with dependency on shared library
3. Update Makefile with service-specific commands

## Virtual Environment Management

This project uses Poetry's **cache directory** for virtual environments instead of in-project `.venv` directories:

- **Shared library**: `/Users/$USER/Library/Caches/pypoetry/virtualenvs/hca-validation-shared-*/`
- **Services**: Each service gets its own cached environment
- **Benefits**: Cleaner project structure, better IDE integration, shared dependencies across projects
- **VS Code**: Automatically discovers Poetry environments via `Ctrl+Shift+P` → "Python: Select Interpreter"

## License

See the [LICENSE](LICENSE) file for details.