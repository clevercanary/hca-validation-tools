# Build stage
FROM --platform=linux/amd64 python:3.11-slim AS builder

# Install Poetry
RUN pip install poetry==1.8.3

# Set up the directory structure to match the expected paths
WORKDIR /build

# Copy service Poetry configuration
COPY services/dataset-validator/pyproject.toml services/dataset-validator/poetry.lock* ./services/dataset-validator/

# Change to service directory for Poetry operations
WORKDIR /build/services/dataset-validator

# Configure Poetry to not create a virtual environment
RUN poetry config virtualenvs.create false

# Install dependencies
RUN poetry install --only main --no-root

# Export requirements for final stage
RUN poetry export --without-hashes -o /tmp/requirements.txt

# Final stage
FROM --platform=linux/amd64 python:3.11-slim

# Install runtime dependencies (if any)
COPY --from=builder /tmp/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy application code
COPY services/dataset-validator/src/dataset_validator/ /app/dataset_validator/

# Set working directory
WORKDIR /app

# Make the main script executable
RUN chmod +x /app/dataset_validator/main.py

# Set the entrypoint to run our main script
ENTRYPOINT ["python", "/app/dataset_validator/main.py"]
