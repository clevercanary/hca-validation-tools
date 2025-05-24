# HCA Entry Sheet Validator Lambda Deployment

This directory contains scripts for building, testing, and deploying the HCA Entry Sheet Validator Lambda function as a container image.

## Overview

The HCA Entry Sheet Validator is deployed as a containerized AWS Lambda function that validates Google Sheets against the HCA schema. The function can be accessed via API Gateway, allowing it to be called from web applications.

## Deployment Architecture

### Lambda Container

The Lambda function is deployed as a container image that includes all dependencies. This approach:
- Ensures consistent execution environments
- Simplifies dependency management with Poetry
- Properly handles C extensions (like pydantic_core)
- Avoids the Lambda deployment package size limit

### API Gateway Integration

The Lambda function is integrated with API Gateway to provide a RESTful API endpoint for validating Google Sheets. The API Gateway endpoint accepts POST requests with a JSON payload containing the Google Sheet ID.

## Scripts

### `build_lambda_container.sh`

Builds a Docker container image for the Lambda function using a multi-stage build process:

1. Creates a temporary build directory
2. Generates a Dockerfile with a multi-stage build:
   - First stage installs Poetry and dependencies
   - Second stage copies only the necessary files
3. Copies Poetry files from the project root
4. Builds the container for the AWS Lambda Python 3.10 runtime
5. Cleans up the temporary directory

Usage:
```bash
make build-lambda-container
```

### `test_lambda_container_locally.sh`

Tests the Lambda container locally by running it in Docker and invoking it with a test event:

1. Creates a temporary directory for test files
2. Generates a test event with a Google Sheet ID
3. Creates a script to run the Lambda container
4. Copies these files to the `output` directory

Usage:
```bash
make test-lambda-container
```

After running this script, you can test the Lambda function locally with:
```bash
cd deployment/docker-build/output && ./run_lambda.sh
```

### `test_api_endpoint.sh`

Tests the deployed API Gateway endpoint for the Lambda function:

1. Sends a POST request to the API Gateway endpoint
2. Includes the Google Sheet ID in the request payload
3. Displays the validation results returned by the Lambda function

Usage:
```bash
./deployment/docker-build/test_api_endpoint.sh [SHEET_ID]
```

### `interactive_lambda_test.sh`

Provides an interactive environment for testing and debugging the Lambda function locally:

1. Creates a Docker container that simulates the AWS Lambda runtime
2. Sets up the correct PYTHONPATH to include all dependencies
3. Provides an interactive shell for testing imports and debugging issues

Usage:
```bash
./deployment/docker-build/interactive_lambda_test.sh
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

```bash
AWS_PROFILE=excira make deploy-lambda-container AWS_ACCOUNT_ID=708377107803 AWS_REGION=us-east-1 LAMBDA_ROLE=arn:aws:iam::708377107803:role/dev-lambda-entry-sheet-validator-exec-role
```

This target:
1. Authenticates with ECR
2. Creates the ECR repository if it doesn't exist
3. Tags and pushes the container image to ECR
4. Updates the Lambda function to use the new image

## API Request Format

```json
{
  "sheet_id": "YOUR_GOOGLE_SHEET_ID",
  "sheet_index": 0
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
- The build process copies Poetry files from the project root, ensuring the latest dependencies are used
- The container includes explicit installation of pydantic and pydantic-core to handle C extensions properly

## Troubleshooting

If you encounter issues with C extensions (like pydantic_core) in the Lambda environment:

1. Use the `interactive_lambda_test.sh` script to debug dependency issues
2. Verify that the multi-stage build in `build_lambda_container.sh` is correctly configured
3. Check that all required shared libraries are included in the container image
