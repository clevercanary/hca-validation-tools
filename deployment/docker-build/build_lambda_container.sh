#!/bin/bash
set -e

echo "Building Lambda container image..."

# Directory containing this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Create a temporary directory
BUILD_DIR=$(mktemp -d)
echo "Created temporary build directory: $BUILD_DIR"

# Create Dockerfile for the Lambda container
cat > "$BUILD_DIR/Dockerfile" << EOF
# Multi-stage build for AWS Lambda with Poetry

# Build stage
FROM public.ecr.aws/lambda/python:3.10 as builder

# Install Poetry
RUN pip install poetry==1.7.1

# Copy Poetry configuration files
COPY pyproject.toml poetry.lock* ./

# Configure Poetry to not create a virtual environment
RUN poetry config virtualenvs.create false

# Install dependencies
RUN poetry install --no-dev

# Install pydantic and pydantic-core explicitly to ensure C extensions are built correctly
RUN pip install pydantic==2.11.4 pydantic-core==2.33.2

# Final stage
FROM public.ecr.aws/lambda/python:3.10

# Copy dependencies from builder stage
COPY --from=builder /var/lang/lib/python3.10/site-packages /var/lang/lib/python3.10/site-packages

# Copy application code
COPY src/hca_validation/ /var/task/hca_validation/

# Set the Lambda handler
CMD ["hca_validation.lambda_functions.entry_sheet_validator_lambda.handler.handler"]
EOF

# We're using Poetry directly for dependency management

# Copy Poetry files for the build

# Copy Poetry files to the build directory
cp "$PROJECT_ROOT/pyproject.toml" "$BUILD_DIR/"
if [ -f "$PROJECT_ROOT/poetry.lock" ]; then
    cp "$PROJECT_ROOT/poetry.lock" "$BUILD_DIR/"
fi

# Copy application code to the build directory
mkdir -p "$BUILD_DIR/src"
cp -r "$PROJECT_ROOT/src" "$BUILD_DIR/"

# Build the Docker image
echo "Building Docker image for linux/amd64 platform..."
docker build --platform linux/amd64 -t hca-entry-sheet-validator "$BUILD_DIR"

echo "Docker image built: hca-entry-sheet-validator"
echo "You can push this image to ECR and deploy it to Lambda"

# Clean up
rm -rf "$BUILD_DIR"
echo "Build completed and temporary files cleaned up"

echo "IMPORTANT: This Lambda container includes all dependencies."
echo "To deploy to AWS, push this image to ECR and create a Lambda function from the container image."
echo ""
echo "Example commands:"
echo "  aws ecr get-login-password --region \$AWS_REGION | docker login --username AWS --password-stdin \$AWS_ACCOUNT_ID.dkr.ecr.\$AWS_REGION.amazonaws.com"
echo "  docker tag hca-entry-sheet-validator \$AWS_ACCOUNT_ID.dkr.ecr.\$AWS_REGION.amazonaws.com/hca-entry-sheet-validator:latest"
echo "  docker push \$AWS_ACCOUNT_ID.dkr.ecr.\$AWS_REGION.amazonaws.com/hca-entry-sheet-validator:latest"
echo "  aws lambda create-function --function-name hca-entry-sheet-validator --package-type Image --code ImageUri=\$AWS_ACCOUNT_ID.dkr.ecr.\$AWS_REGION.amazonaws.com/hca-entry-sheet-validator:latest --role \$LAMBDA_ROLE"
