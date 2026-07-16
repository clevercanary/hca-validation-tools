# CLAUDE.md

<!-- Shared sections (Team roster through GitHub API discipline) are seeded from
     cc-claude-tools templates/CLAUDE.template.md; keep them in sync with the
     plugin. The repo-specific sections above them are this repo's own content. -->

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
cd shared && uv run pytest tests/ -v
cd shared && uv run pytest tests/test_validator.py -v          # Validator only
cd shared && uv run pytest tests/test_entry_sheet_validator.py -v  # Entry sheet only
cd shared && uv run pytest tests/ -m integration -v            # Integration tests (needs creds)
cd shared && uv run pytest tests/ -m "not integration" -v      # Skip integration tests

# Service-specific tests
cd services/entry-sheet-validator && make test-lambda-container
cd services/dataset-validator && uv run pytest tests/ -v
cd services/cellxgene-validator && uv run pytest tests/ -v
cd services/hca-schema-validator && uv run pytest tests/ -v
```

## Type Checking

Pyright covers `packages/hca-anndata-tools`, `packages/hca-anndata-mcp`, `packages/hca-schema-validator`, `services/dataset-validator`, and `services/hca-schema-validator`. Config is `pyrightconfig.json` at repo root. Runs one pass per venv since each has a disjoint dep set.

Note: `hca-anndata-tools` doesn't declare pyright as a dev dep — its files are checked from the `hca-anndata-mcp` venv (which depends on tools, so it's a superset). This asymmetry persists under uv: the uv migration (#248) deliberately does **not** use a workspace, so each project keeps its own venv rather than sharing one.

```bash
make typecheck
```

Pre-commit hook runs it on `git commit`. One-time setup: `pip install pre-commit && pre-commit install`.

For Pylance to match in-editor, open the repo via `hca-validation-tools.code-workspace` (File → Open Workspace from File). Each package/service becomes its own root with its own venv (uv `.venv/` under `packages/`, poetry elsewhere), so imports resolve correctly per folder.

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

**Cutting 1.0.0 is a deliberate manual act.** When a package is API-stable enough to graduate, land a commit with `Release-As: 1.0.0` in the footer:

```
chore(<package>): graduate to 1.0.0

Release-As: 1.0.0
```

This is release-please's supported override mechanism — it overrides the auto-computed bump for the package whose path the commit touches. Don't hand-edit `.release-please-manifest.json`: that file is a back-reference to the last released version per path and editing it doesn't reliably cut a release; it can also desync from the git tags release-please uses for compare links.

Before tagging 1.0.0, widen the sibling bounds in `packages/hca-anndata-mcp/pyproject.toml`. They are capped at the next minor (`hca-anndata-tools>=0.6,<0.7`) because at 0.x a minor bump signals a breaking change; once a sibling reaches 1.0 that cap must become `<2`, or the MCP wheel will refuse to install alongside it.

`scripts/check_sibling_deps.py` runs in the publish workflow and fails the build if a sibling is declared without a bound, as a direct `file://` reference, or with a bound that excludes the sibling's current version. None of these are visible locally: `[tool.uv.sources]` resolves siblings from the checkout, so `uv sync`, pytest, and pyright all pass regardless of what the bound says.

**Minor-bumping a package means updating the bound in every sibling that depends on it.** release-please bumps a package's own version but has no Python plugin that rewrites dependents' constraints, so it will not do this for you. Concretely: if `hca-anndata-tools` goes `0.6.x` → `0.7.0` while `hca-anndata-mcp` still declares `hca-anndata-tools>=0.6,<0.7`, nothing breaks locally — but `hca-anndata-mcp`'s **next release will fail** at the `check_sibling_deps.py` step, because the wheel would tell consumers to install a version the package was never built against. That failure is intentional; fix it by widening the bound in `packages/hca-anndata-mcp/pyproject.toml`, not by bypassing the check.

## Updating hca-schema-validator in the Batch Service

The Docker image installs from `uv.lock` (via `uv export`), so **the lock is what decides which version ships** — not the constraint in `pyproject.toml`. Which of the two you touch depends on where the new release lands.

**A patch release inside the existing constraint** (e.g. `0.14.0` → `0.14.1`, against `>=0.14.0,<0.15.0`):

1. `cd services/hca-schema-validator && uv lock --upgrade-package hca-schema-validator`
2. Commit `uv.lock`

No pin bump is needed — the constraint already admits it. But a bare `uv lock` **will not pick the new version up**: it re-resolves conservatively and keeps the existing locked version. Only `uv lock --upgrade-package <package>` moves the lock. That failure is **silent** — the build succeeds and the image just keeps shipping the old validator.

**A release that crosses the constraint** (e.g. `0.14.x` → `0.15.0`):

1. Bump the version pin in `services/hca-schema-validator/pyproject.toml`
2. `cd services/hca-schema-validator && uv lock`
3. Commit `pyproject.toml` and `uv.lock` together

Here `uv lock` is enough, because the constraint changed.

Either way, confirm the lock actually moved before building:

```bash
grep -A1 'name = "hca-schema-validator"' services/hca-schema-validator/uv.lock
```

### Only build the image from a clean tree

```bash
make batch-publish-container ENV=dev     # then ENV=prod, from main
```

**The image's contents and its tag come from different places.** `docker build` copies from the **working tree**, so it picks up uncommitted edits; the tag is `git rev-parse --short HEAD`, i.e. the **last commit**. Build with a dirty tree and you publish an image whose tag names a commit that does not contain what is inside it — nobody can then tell what is deployed, because checking out that SHA reproduces a *different* image. `make publish-batch` refuses to run from a dirty tree for this reason; do not work around it.

**Dev may be built from a branch.** A clean branch commit is a real commit, so the tag still reproduces the image — that is how a change is validated on dev before it merges. **Prod should be built from `main`**, so that what is running in production is on the mainline and not on a branch that may never land.

## Architecture

**Multi-Service Structure:**
- `shared/` - Core library with LinkML schemas, Pydantic validation, entry sheet logic. All services depend on this via a uv path dependency (`[tool.uv.sources]`).
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
- Each service has its own `pyproject.toml` and uv environment (project-local `.venv/`)
- Services declare `hca-validation-shared` in `[project].dependencies`; `[tool.uv.sources] hca-validation-shared = { path = "../../shared", editable = true }` redirects that dependency to the local checkout for development
- Different deployment targets allow for different dependency profiles (Lambda is lightweight, Batch has heavy scientific stack)

## Environment Configuration

- `.env` - Google Service Account JSON credentials for Sheets API access
- `.env.make` - AWS deployment settings (account IDs, regions, role ARNs for dev/prod)

## Key Technologies

- uv for dependency management across `packages/`, `shared/`, and `services/` (project-local `.venv/`, its own `uv.lock` per project — no workspace, see #248). Service locks are committed; library locks under `packages/` and `shared/` are gitignored (see #483). The Poetry→uv migration (#248) is complete.
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

## Team roster

| Name   | GitHub handle |
|--------|---------------|
| Dave   | NoopDog       |
| Fran   | frano-m       |
| Hunter | hunterckx     |
| Mim    | MillenniumFalconMechanic |

"Assign to Fran" always means the GitHub handle in this table. Never guess a
handle. If someone is not in this table, ask.

## Error handling philosophy

Validate at trust boundaries only, and trust everything inside them.

- The trust boundaries are: user input, network responses, file contents,
  environment variables, CLI arguments, and data crossing a public API.
  Validate at the boundary, once, and fail with a clear error that names
  what was wrong.
- Inside the boundary, where our functions call our functions, do NOT check
  for null, undefined, or wrong types. A caller passing bad input is a bug
  in the caller, so let the code throw. A stack trace at the real call site
  is what enables the fix. A defensive fallback hides the bug.
- Never silently coerce, default, or catch-and-continue to "handle" bad
  input. Do not use `?? defaultValue` to paper over a missing value. Do not
  write a try/catch whose handler just logs and proceeds.
- A crash with a good message is the correct behavior for a contract
  violation.

When a reviewer, Copilot or human, suggests defensive handling of internal
inputs, decline the suggestion and cite this section. The `/cc:auto-review`
skill describes how to decline on the pull request thread.

## Python conventions

Ruff and Pyright enforce the mechanical rules in CI, so do not re-argue
formatting or import order in review. For judgment-level style, the canon is
*Effective Python* (Brett Slatkin, 3rd ed.); cite item numbers in reviews
and declines the way this section is cited.

## Auto-review

When you believe a coding task is complete, announce that the code is done
and run `/cc:auto-review`. The skill defines the only moments to interrupt
the user. Clean review rounds proceed silently.

## Surprises

You may encounter an environment, tool, dependency, or constraint that the
user never mentioned and that changes your approach. Examples: a conda
environment, an unexpected framework, or a missing credential. When that
happens, STOP and ask before proceeding. Do not work around the surprise
silently.

## Communication

- Do not use analogies or metaphors.
- Lead with the outcome in one sentence.
- Keep status updates to one line.
- Flag your assumptions explicitly.

## GitHub API discipline

- Never enumerate a full project board, and never paginate more than two
  pages to find one item. If you do not have an ID, look in
  `.claude/github-projects.md`. If the ID is not there, fetch it once and
  add it to that file.
- Never fetch issues or pull requests in a loop. Use a single search or
  list call with filters instead.
- If you get a rate-limit response, STOP and tell the user. Do not retry.
