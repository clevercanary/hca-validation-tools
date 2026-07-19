# HCA Validation Tools

A multi-service collection of tools for validating Human Cell Atlas (HCA) ingest data, built with LinkML schemas and deployed as AWS Lambda functions.

## Overview

This repository contains validation tools organized in a multi-service architecture:

- **Entry Sheet Validator**: Validates Google Sheets against LinkML schemas with AWS Lambda deployment
- **Data Dictionary Generator**: Creates data dictionaries from LinkML schema definitions
- **Schema Validation**: Validates LinkML schemas and generates Python models

## Repository Layout

Top-level directories and their roles (each package/service has its own
`pyproject.toml`, uv environment, and `tests/`):

- **`shared/`** — core validation library (LinkML schemas, generated Pydantic models, entry-sheet logic) that the services depend on via a uv path dependency
- **`packages/`** — publishable PyPI packages: `hca-schema-validator`, `hca-anndata-tools`, `hca-anndata-mcp`
- **`services/`** — deployable services: `entry-sheet-validator` (Lambda), `dataset-validator` (Batch), and the `cellxgene-validator` / `hca-schema-validator` wrappers
- **`deployment/`** — Dockerfiles and per-service deployment configs
- **`data_dictionaries/`** — generated data dictionaries

## Quick Start

This project uses uv for dependency management and Make for build automation.

Install uv first (it also provisions the required Python version, so you don't
need to install Python yourself) — see the
[uv install docs](https://docs.astral.sh/uv/getting-started/installation/):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```bash
# Clone the repository
git clone https://github.com/clevercanary/hca-validation-tools.git
cd hca-validation-tools

# Build everything (schemas, data dictionaries, Docker images, run tests)
# Note: build-all builds the Lambda container, so it needs Docker running and an
# AWS profile with access to the Lambda Extension layer (passed as PROFILE=...).
make build-all

# Or just install the shared library (no Docker/AWS needed)
cd shared
uv sync
```

## Available Commands

### Build Commands
```bash
make build-all                 # Build shared lib + containers and run tests (needs Docker + AWS)
make build-lambda-container PROFILE=<profile>  # Build the entry-sheet Lambda image (AWS profile with Extension-layer access)
```

Schema and data-dictionary generation live in the shared library's Makefile:

```bash
cd shared
make gen-schema                # Generate Pydantic models from LinkML schemas
make validate-schema           # Validate all LinkML schema files
make generate-data-dictionary  # Generate the core data dictionary
make build                     # All of the above in one step
```

### Test Commands

Each package and service has its own uv environment, so tests are run per
project with `uv run pytest`. Each line below is self-contained (run from the
repo root):

```bash
(cd shared                        && uv run pytest tests/ -m "not integration")  # shared library (unit)
(cd packages/hca-anndata-tools    && uv run pytest tests/)
(cd packages/hca-anndata-mcp      && uv run pytest tests/)
(cd packages/hca-schema-validator && uv run pytest tests/)
(cd services/dataset-validator    && uv run pytest tests/)
(cd services/cellxgene-validator  && uv run pytest tests/)
(cd services/hca-schema-validator && uv run pytest tests/)
```

These seven suites are exactly what CI runs on every pull request. Type
checking runs separately:

```bash
make typecheck   # pyright across every typed project (one pass per venv)
```

Integration tests (which hit live Google Sheets and need credentials in `.env`)
are marked `integration`. The unit-test command above excludes them with
`-m "not integration"`; a bare `pytest tests/` would run them. Run only the
integration tests with:

```bash
cd shared && uv run pytest tests/ -m integration
```

`make test-all` runs the shared and service suites in one go, **but note two
gaps**: it invokes the entry-sheet container smoke test, so it **requires Docker
and a built image** (and fails without them), and it **does not cover the
`packages/` suites** — run those directly with the commands above.

The **entry-sheet-validator container smoke test** is not part of the commands
above; it boots the built Lambda image in Docker (so it needs a built image),
and its happy-path assertion additionally needs `GOOGLE_SERVICE_ACCOUNT` in the
environment — without it that assertion skips. See
[deployment/entry-sheet-validator/README.md](deployment/entry-sheet-validator/README.md).

### Checks (mirror CI)

Before pushing, run the same lint, format, and type checks CI gates on. Ruff is
pinned to match CI exactly:

```bash
uvx ruff@0.11.8 check .          # lint
uvx ruff@0.11.8 format --check . # formatting
make typecheck                   # pyright
```

Optionally install the pre-commit hook so equivalent checks run automatically on
`git commit` — it applies `ruff --fix` and formatting and runs `make typecheck`
(the auto-fixing counterparts of the read-only checks above). It is opt-in and
does nothing until installed:

```bash
pip install pre-commit && pre-commit install
```

### Deployment Commands

The environment is selected with `ENV=dev` (default) or `ENV=prod`:

```bash
make deploy-lambda-container ENV=dev    # Deploy the entry-sheet Lambda (dev)
make deploy-lambda-container ENV=prod   # Deploy the entry-sheet Lambda (prod)
make invoke-lambda SHEET_ID=<id>        # Invoke the deployed Lambda

# Dataset-validator Batch service
make batch-publish-container ENV=dev    # Build, push to ECR, register the job def
make batch-submit-job ENV=dev           # Submit a Batch validation job
```

See [CLAUDE.md](CLAUDE.md) for the full deployment and release workflow.

## Configuration

### Environment Files
Both are **gitignored** — keep credentials and machine-specific values out of the repo.

- **`.env`** - Contains `GOOGLE_SERVICE_ACCOUNT` credentials for Google Sheets API
- **`.env.make`** - AWS deployment variables (account IDs, regions, roles) and the
  AWS CLI profile used to build the Lambda image

One-time AWS setup — copy the committed template and fill in your values:

```bash
cp .env.make.example .env.make
# then edit .env.make: set LAMBDA_PROFILE to an AWS CLI profile that can fetch
# the Lambda Extension layer (and fill in the account/region/role vars for deploy)
```

With `.env.make` in place, `make build-lambda-container` and `make build-all`
pick up the profile automatically — no `PROFILE=` argument needed (pass
`PROFILE=<name>` only to override).

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
- Each service has its own uv environment and test suite

### Adding New Services
1. Create new directory under `services/`
2. Add `pyproject.toml` with dependency on shared library
3. Update Makefile with service-specific commands

## Virtual Environment Management

This project uses uv, which creates a **project-local `.venv/`** directory in each package/service:

- **Shared library**: `shared/.venv/`
- **Services**: Each service gets its own `.venv/` alongside its `pyproject.toml`
- **Reproducibility**: uv resolves dependencies into a `uv.lock`; `uv sync --frozen` installs exactly those versions without re-resolving (a plain `uv sync` may update the lock). The services commit their `uv.lock`, so `--frozen` works there; the library projects (`shared/`, `packages/*`) gitignore their lock (see #483), so a fresh clone re-resolves from `pyproject.toml`
- **VS Code**: Open `hca-validation-tools.code-workspace` so each folder resolves its own `.venv`, or select the interpreter via `Ctrl+Shift+P` → "Python: Select Interpreter"

## License

See the [LICENSE](LICENSE) file for details.