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

## Type Checking

Pyright covers `packages/hca-anndata-tools`, `packages/hca-anndata-mcp`, `packages/hca-schema-validator`, `services/dataset-validator`, and `services/hca-schema-validator`. Config is `pyrightconfig.json` at repo root. Runs one pass per venv since each has a disjoint dep set.

Note: `hca-anndata-tools` doesn't declare pyright as a dev dep — its files are checked from the `hca-anndata-mcp` venv (which depends on tools, so it's a superset). This asymmetry goes away when we migrate to uv workspaces (#248) and have one shared venv.

```bash
make typecheck
```

Pre-commit hook runs it on `git commit`. One-time setup: `pip install pre-commit && pre-commit install`.

For Pylance to match in-editor, open the repo via `hca-validation-tools.code-workspace` (File → Open Workspace from File). Each package/service becomes its own root with its own poetry venv, so imports resolve correctly per folder.

## Deployment Commands

```bash
# Lambda (Entry Sheet Validator) - ENV=dev by default, use ENV=prod for production
# PROFILE=excira is required for build (fetches AWS Lambda Extension layer via AWS API)
make build-lambda-container PROFILE=excira
make deploy-lambda-container ENV=dev
make invoke-lambda SHEET_ID=<google-sheet-id>

# Batch (Dataset Validator)
make batch-publish-container ENV=dev    # Build, tag, push to ECR, register job def
make batch-publish-container ENV=prod   # Same for production
make batch-submit-job ENV=dev
```

## Release Policy

All three publishable packages (`hca-schema-validator`, `hca-anndata-tools`, `hca-anndata-mcp`) are pre-1.0 and treated as still iterating. Two flags in `release-please-config.json` shape the bump behavior:

- **`bump-minor-pre-major: true`** — on a 0.x package, `feat!` (BREAKING CHANGE) produces a minor bump (`0.12.1` → `0.13.0`), not release-please's default `0.x` → `1.0.0` promotion.
- **`bump-patch-for-minor-pre-major: true`** — non-breaking `feat:` commits produce a patch bump (`0.12.1` → `0.12.2`), not the default minor. This keeps the minor bump as the explicit "breaking change" signal at 0.x.

Net effect on 0.x packages: `fix:` → patch, `feat:` → patch, `feat!:` → minor. The minor digit is the only signal that a release contains a breaking change; consumers pinning `>=0.12,<0.13` get automatic patches but block on minors.

**Cutting 1.0.0 is a deliberate manual act.** When a package is API-stable enough to graduate:

1. Land a commit with `Release-As: 1.0.0` in the footer (release-please will honor it), OR
2. Hand-edit `.release-please-manifest.json` to set the target version.

Before doing either, update `.github/workflows/release-please.yml` — the MCP publish step has sed substitutions that hard-cap sibling packages at `<1`. Those caps must be relaxed (e.g., `<2`) or the post-1.0 MCP wheel on PyPI will refuse to install. (Tracked in a follow-up issue.)

## Updating hca-schema-validator in the Batch Service

When a new version of `hca-schema-validator` is released (via release-please → PyPI):

1. Bump the version pin in `services/hca-schema-validator/pyproject.toml`
2. **Regenerate the lock file**: `cd services/hca-schema-validator && poetry lock`
3. Commit both `pyproject.toml` and `poetry.lock` together
4. After merge, rebuild the Docker image: `make batch-publish-container ENV=dev`

Forgetting step 2 will cause the Docker build to fail with "pyproject.toml changed significantly since poetry.lock was last generated."

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
