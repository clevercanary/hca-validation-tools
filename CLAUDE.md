# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

HCA Validation Tools is a multi-service validation system for Human Cell Atlas (HCA) ingest data. It uses LinkML schemas for data definition and deploys as AWS Lambda (lightweight sheet validation) and AWS Batch (heavy H5AD file validation) services.

## Build Commands

```bash
# Full build across all services
make build-all              # Build shared lib + containers + run all tests

# Shared library (run from root or shared/)
cd shared && make build     # Validate schemas, generate Python models, generate data dictionary
cd shared && make validate-schema    # Validate LinkML YAML files only
cd shared && make gen-schema         # Generate Pydantic models from schemas
```

## Test Commands

```bash
# Run all tests
make test-all

# Shared library tests
cd shared && poetry run pytest tests/ -v
cd shared && poetry run pytest tests/test_validator.py -v          # Validator only
cd shared && poetry run pytest tests/test_entry_sheet_validator.py -v  # Entry sheet only
cd shared && poetry run pytest tests/ -m integration -v            # Integration tests (needs creds)
cd shared && poetry run pytest tests/ -m "not integration" -v      # Skip integration tests

# Service-specific tests
cd services/entry-sheet-validator && make test-lambda-container
cd services/dataset-validator && poetry run pytest tests/ -v
cd services/cellxgene-validator && poetry run pytest tests/ -v
cd services/hca-schema-validator && poetry run pytest tests/ -v
```

## Deployment Commands

```bash
# Lambda (Entry Sheet Validator) - ENV=dev by default, use ENV=prod for production
make build-lambda-container
make deploy-lambda-container ENV=dev
make invoke-lambda SHEET_ID=<google-sheet-id>

# Batch (Dataset Validator)
make batch-publish-container ENV=dev    # Build, tag, push to ECR, register job def
make batch-submit-job ENV=dev
```

## Architecture

**Multi-Service Structure:**
- `shared/` - Core library with LinkML schemas, Pydantic validation, entry sheet logic. All services depend on this via Poetry path dependency.
- `services/entry-sheet-validator/` - AWS Lambda service for Google Sheets validation
- `services/dataset-validator/` - AWS Batch service for H5AD file validation using cap-upload-validator
- `services/hca-schema-validator/` - Service wrapper for the published PyPI package
- `services/cellxgene-validator/` - Wrapper for cellxgene-schema validator
- `packages/hca-schema-validator/` - Publishable PyPI package (automated releases via release-please)
- `deployment/` - Dockerfiles and deployment configs per service

**Schema-Driven Validation:**
- LinkML YAML schemas in `shared/src/hca_validation/schema/` define entities (Dataset, Donor, Sample, Cell)
- `make gen-schema` generates Pydantic models to `shared/src/hca_validation/schema/generated/core.py`
- Bionetwork-specific schemas (adipose, gut, musculoskeletal) extend the core schema

**Service Independence:**
- Each service has its own `pyproject.toml` and Poetry environment
- Services reference shared via: `hca-validation-shared = {path = "../../shared", develop = true}`
- Different deployment targets allow for different dependency profiles (Lambda is lightweight, Batch has heavy scientific stack)

## Environment Configuration

- `.env` - Google Service Account JSON credentials for Sheets API access
- `.env.make` - AWS deployment settings (account IDs, regions, role ARNs for dev/prod)

## Key Technologies

- Poetry for dependency management (environments cached in `~/Library/Caches/pypoetry/virtualenvs/`)
- LinkML for schema definition
- Pydantic for runtime validation
- gspread for Google Sheets API
- anndata for H5AD file handling
- Docker multi-stage builds for AWS deployments

## Git Workflow

When starting work on a change:

1. Create a GitHub issue first: `gh issue create --title "..." --body "..."`
2. Create a feature branch using the format: `<github-username>/<issue-number>-<short-description>` (e.g., `noopdog/181-fix-package-publish`)
3. Make changes and commit to the feature branch
4. Push and open a PR linking the issue: `gh pr create --title "..." --body "Closes #<issue-number>"`
