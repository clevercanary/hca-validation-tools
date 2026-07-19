# HCA Entry Sheet Validator Lambda Deployment

This directory contains scripts for building, testing, and deploying the HCA Entry Sheet Validator Lambda function as a container image.

## Overview

The HCA Entry Sheet Validator is deployed as a containerized AWS Lambda function that validates Google Sheets against the HCA schema. The function can be accessed via API Gateway, allowing it to be called from web applications.

## Deployment Architecture

### Lambda Container

The Lambda function is deployed as a container image that includes all dependencies. This approach:

- Ensures consistent execution environments
- Simplifies dependency management with uv
- Properly handles C extensions (like pydantic_core)
- Avoids the Lambda deployment package size limit

### API Gateway Integration

The Lambda function is integrated with API Gateway to provide a RESTful API endpoint for validating Google Sheets. The API Gateway endpoint accepts POST requests with a JSON payload containing the Google Sheet ID.

## Scripts

### `build_lambda_container.sh`

Builds the Docker container image for the Lambda function. The script:

1. Resolves the AWS Parameters and Secrets Lambda Extension layer to a presigned URL via `aws lambda get-layer-version-by-arn` (using the optional AWS profile passed as its first argument)
2. Runs `docker build` against the committed `deployment/entry-sheet-validator/Dockerfile`, with the repo root as the build context and the presigned URL passed as the `EXT_URL` build arg, tagging the image `hca-entry-sheet-validator`

That Dockerfile is itself multi-stage on the `public.ecr.aws/lambda/python:3.10` base:
- The builder stage exports the locked dependencies with uv (`uv export --frozen`) and installs them into `/opt/python`
- The final stage copies `/opt/python`, the unpacked extension, and the service + `shared/` source into the Lambda image

Usage:

```bash
make build-lambda-container
```

### Local container smoke test

`make test-lambda-container` (in `services/entry-sheet-validator/`) starts the
built image in Docker and drives it through the Lambda Runtime Interface
Emulator with `pytest tests/test_lambda_container_smoke.py`. It loads the
repo-root `.env` so `GOOGLE_SERVICE_ACCOUNT` is present; with credentials the
happy-path test asserts a `200` and a boolean `valid`, and without them it
skips rather than passing on an auth failure.

Build the image first (the target refuses to run if it is missing):

```bash
make build-lambda-container   # produces hca-entry-sheet-validator:latest (AWS profile from .env.make)
make test-lambda-container
```

The real Secrets-Extension → Secrets-Manager credential path is an AWS
integration that only runs inside the deployed Lambda; verify it post-deploy
with `make invoke-lambda ENV=dev`, not locally.

### `test_api_endpoint.sh`

Tests the deployed API Gateway endpoint for the Lambda function:

1. Sends a POST request to the API Gateway endpoint
2. Includes the Google Sheet ID in the request payload
3. Displays the validation results returned by the Lambda function

Usage:

```bash
./deployment/entry-sheet-validator/test_api_endpoint.sh [SHEET_ID]
```

## Deployment Process

The deployment process is managed through the Makefile with the following targets:

### Building the Container

```bash
make build-lambda-container
```

This builds the Docker container image using the `build_lambda_container.sh` script.

### Testing the Container Locally

```bash
make test-lambda-container
```

This generates test files and provides instructions for testing the Lambda container locally.

### Deploying to AWS

The build profile comes from `LAMBDA_PROFILE` in `.env.make` (see the repo-root
README), so the build needs no profile on the command line. The **deploy**
profile is still supplied via the `AWS_PROFILE` env var — dev and prod use
different profiles. Sourcing the deploy profile from `.env.make` too is tracked
in #517.

```bash
make build-lambda-container                                       # profile from .env.make
AWS_PROFILE=<dev-profile>  make deploy-lambda-container ENV=dev
AWS_PROFILE=<prod-profile> make deploy-lambda-container ENV=prod
```

## API Request Format

```json
{
  "sheet_id": "YOUR_GOOGLE_SHEET_ID"
}
```

## API Response Format

```json
{
  "sheet_id": "YOUR_GOOGLE_SHEET_ID",
  "validation_errors": [
    {
      "row": 4,
      "message": "Validation error message",
      "field": "field_name",
      "value": "invalid_value"
    }
  ],
  "memory_usage": {
    "initial": {
      "memory_used_mb": 75.26,
      "memory_limit_mb": 512,
      "memory_utilization_percent": 14.7
    },
    "pre_validation": {
      "memory_used_mb": 75.26,
      "memory_limit_mb": 512,
      "memory_utilization_percent": 14.7
    },
    "post_validation": {
      "memory_used_mb": 121.03,
      "memory_limit_mb": 512,
      "memory_utilization_percent": 23.64
    }
  }
}
```

## Performance Considerations

The Lambda function demonstrates significant performance improvements on warm starts:

- **Cold Start**: ~13 seconds
- **Warm Start**: <1 second (34x faster)

Memory usage is monitored and reported in the response, showing approximately 24% utilization of the allocated 512MB (about 121MB used).

## Development Notes

- The `output` directory is excluded from Git to avoid committing generated test files
- The build process copies the service's uv project files (`services/entry-sheet-validator/{pyproject.toml,uv.lock}`) and the `shared/` source from their locations under the repo-root build context, ensuring the locked dependencies are used
- The container includes explicit installation of pydantic and pydantic-core to handle C extensions properly

## Troubleshooting

If you encounter issues with C extensions (like pydantic_core) in the Lambda environment:

1. Verify that the multi-stage build in `build_lambda_container.sh` is correctly configured
2. Check that all required shared libraries are included in the container image
3. Use the AWS Lambda container image locally for testing
