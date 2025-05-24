#!/bin/bash
set -e

# Directory containing this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Create a temporary directory for testing
TEST_DIR=$(mktemp -d)
echo "Created temporary directory: $TEST_DIR"

# Copy Lambda package and layers to test directory
cp "$PROJECT_ROOT/deployment/entry_sheet_validator_lambda.zip" "$TEST_DIR/"
cp "$PROJECT_ROOT/deployment/layers/linkml_dependencies_layer.zip" "$TEST_DIR/"
cp "$PROJECT_ROOT/deployment/layers/aws_sdk_pandas_layer.zip" "$TEST_DIR/"

# Extract files
cd "$TEST_DIR"
mkdir -p lambda
unzip -q entry_sheet_validator_lambda.zip -d lambda
mkdir -p lambda/python
unzip -q linkml_dependencies_layer.zip -d lambda
mkdir -p lambda/aws_sdk_pandas
unzip -q aws_sdk_pandas_layer.zip -d lambda/aws_sdk_pandas

# Create test script
cat > "$TEST_DIR/test_imports.py" << EOF
#!/usr/bin/env python
import sys
import os

# Print Python path
print("Python path:")
for path in sys.path:
    print(f"  {path}")

# Try importing pydantic
print("\nTrying to import pydantic...")
try:
    import pydantic
    print(f"Successfully imported pydantic {pydantic.__version__}")
    
    import pydantic_core
    print(f"Successfully imported pydantic_core {pydantic_core.__version__}")
    print("Pydantic imports successful!")
except Exception as e:
    print(f"Error importing pydantic: {e}")
    import traceback
    traceback.print_exc()

# Try importing handler
print("\nTrying to import handler...")
try:
    from hca_validation.lambda_functions.entry_sheet_validator_lambda.handler import handler
    print("Successfully imported handler")
except Exception as e:
    print(f"Error importing handler: {e}")
    import traceback
    traceback.print_exc()
EOF

# Create a shell script to run inside the container
cat > "$TEST_DIR/container_shell.sh" << EOF
#!/bin/bash
export PYTHONPATH=/var/task:/opt/python:/opt/aws_sdk_pandas
cd /var/task
echo "Welcome to the AWS Lambda Python 3.10 environment"
echo "The Lambda function code is mounted at /var/task"
echo "The LinkML dependencies layer is mounted at /opt/python"
echo "The AWS SDK for pandas layer is mounted at /opt/aws_sdk_pandas"
echo "PYTHONPATH is set to include all layers"
echo ""
echo "You can run 'python test_imports.py' to test imports"
echo "or start an interactive Python shell with 'python'"
bash
EOF
chmod +x "$TEST_DIR/container_shell.sh"

# Print instructions
echo "Starting interactive AWS Lambda container..."
echo "The Lambda function and layers are mounted in the container."
echo "Run 'python test_imports.py' to test imports."
echo ""

# Run interactive container
docker run -it --rm \
  -v "$TEST_DIR/lambda:/var/task" \
  -v "$TEST_DIR/lambda/python:/opt/python" \
  -v "$TEST_DIR/lambda/aws_sdk_pandas:/opt/aws_sdk_pandas" \
  -v "$TEST_DIR/test_imports.py:/var/task/test_imports.py" \
  -v "$TEST_DIR/container_shell.sh:/var/task/container_shell.sh" \
  --entrypoint "/var/task/container_shell.sh" \
  public.ecr.aws/lambda/python:3.10

# Clean up
rm -rf "$TEST_DIR"
echo "Test completed and temporary files cleaned up."
