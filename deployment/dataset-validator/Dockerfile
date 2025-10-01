# Build stage
FROM python:3.11-slim-bookworm AS builder

# Install Poetry
RUN pip install poetry==1.8.3

# Set up the directory structure to match the expected paths
WORKDIR /build

# Copy services' Poetry configuration
COPY services/dataset-validator/pyproject.toml services/dataset-validator/poetry.lock* ./services/dataset-validator/
COPY services/cellxgene-validator/pyproject.toml services/cellxgene-validator/poetry.lock* ./services/cellxgene-validator/

# Change to dataset validator service directory for Poetry operations
WORKDIR /build/services/dataset-validator
# Configure Poetry to not create a virtual environment
RUN poetry config virtualenvs.create false
# Install dependencies
RUN poetry install --only main --no-root
# Export requirements for final stage
RUN poetry export --without-hashes -o /tmp/requirements.txt

# Change to CELLxGENE validator service directory for Poetry operations
WORKDIR /build/services/cellxgene-validator
# Configure Poetry to not create a virtual environment
RUN poetry config virtualenvs.create false
# Install dependencies
RUN poetry install --only main --no-root
# Export requirements for final stage
RUN poetry export --without-hashes -o /tmp/requirements_cellxgene.txt

# Final stage
FROM python:3.11-slim-bookworm

# Install runtime dependencies (if any)
# Install main requirements
COPY --from=builder /tmp/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
#Install CELLxGENE validator requirements
COPY --from=builder /tmp/requirements_cellxgene.txt /tmp/requirements_cellxgene.txt
RUN python -m venv /opt/venvs/cellxgene-validator \
  && /opt/venvs/cellxgene-validator/bin/pip install --no-cache-dir -r /tmp/requirements_cellxgene.txt

# Set environment variable for venv path
ENV CELLXGENE_VALIDATOR_VENV="/opt/venvs/cellxgene-validator"

# Copy application code
COPY services/dataset-validator/src/dataset_validator/ /app/dataset_validator/
COPY services/cellxgene-validator/src/cellxgene_validator/ /app/cellxgene_validator/

# Set working directory
WORKDIR /app

# Set the entrypoint to run our main script
ENTRYPOINT ["python", "/app/dataset_validator/main.py"]
