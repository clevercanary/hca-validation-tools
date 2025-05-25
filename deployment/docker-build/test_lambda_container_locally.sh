#!/bin/bash
set -e

echo "Testing Lambda container locally..."

# Directory containing this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Create a temporary directory for test files
TEST_DIR=$(mktemp -d)
echo "Created temporary test directory: $TEST_DIR"

# Create a test event file
cat > "$TEST_DIR/test_event.json" << EOF
{
  "sheet_id": "1oPFb6qb0Y2HeoQqjSGRe_TlsZPRLwq-HUlVF0iqtVlY",
  "sheet_index": 0
}
EOF

# Create a script to run the Lambda container
cat > "$TEST_DIR/run_lambda.sh" << EOF
#!/bin/bash
set -e

# Start the Lambda container
echo "Starting Lambda container..."
docker run -d --name lambda-test -p 9000:8080 hca-entry-sheet-validator:latest
echo "Lambda container started"

# Wait for the container to start
echo "Waiting for container to start..."
sleep 3

# Invoke the Lambda function
echo "Invoking Lambda function..."
curl -XPOST "http://localhost:9000/2015-03-31/functions/function/invocations" -d @test_event.json

# Stop and remove the container
echo "Stopping Lambda container..."
docker stop lambda-test
docker rm lambda-test
EOF

# Make the script executable
chmod +x "$TEST_DIR/run_lambda.sh"

# Ensure the output directory exists
mkdir -p "$SCRIPT_DIR/output"
# Copy the test event to the test directory
cp "$TEST_DIR/test_event.json" "$SCRIPT_DIR/output/test_event.json"
cp "$TEST_DIR/run_lambda.sh" "$SCRIPT_DIR/output/run_lambda.sh"

echo "Test files created at:"
echo "  $SCRIPT_DIR/output/test_event.json"
echo "  $SCRIPT_DIR/output/run_lambda.sh"

echo "To test the Lambda container locally, run:"
echo "  cd $SCRIPT_DIR/output && ./run_lambda.sh"

# Clean up
rm -rf "$TEST_DIR"
