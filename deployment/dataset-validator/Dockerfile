# Build stage
FROM python:3.11-slim-bookworm AS builder

# Install Poetry
RUN pip install poetry==2.2.1

# Set up the directory structure to match the expected paths
WORKDIR /build

# Copy shared library (path dep of dataset-validator)
COPY shared/ ./shared/

# Copy services' Poetry configuration
COPY services/dataset-validator/pyproject.toml services/dataset-validator/poetry.lock* ./services/dataset-validator/
COPY services/cellxgene-validator/pyproject.toml services/cellxgene-validator/poetry.lock* ./services/cellxgene-validator/
COPY services/hca-schema-validator/pyproject.toml services/hca-schema-validator/poetry.lock* ./services/hca-schema-validator/

RUN poetry self add poetry-plugin-export

# Change to dataset validator service directory for Poetry operations
WORKDIR /build/services/dataset-validator
# Install dependencies
RUN poetry install --only main --no-root
# Export requirements for final stage. Drop the editable hca-validation-shared
# path entry — the final stage receives the source via a direct COPY instead.
RUN poetry export --without-hashes -o /tmp/requirements.txt && \
    sed -i '/^-e file:.*shared/d' /tmp/requirements.txt

# Change to CELLxGENE validator service directory for Poetry operations
WORKDIR /build/services/cellxgene-validator
# Install dependencies
RUN poetry install
# Export requirements for final stage
RUN poetry export --without-hashes -o /tmp/requirements_cellxgene.txt

# Change to HCA schema validator service directory for Poetry operations
WORKDIR /build/services/hca-schema-validator
# Install dependencies
RUN poetry install
# Export requirements for final stage
RUN poetry export --without-hashes -o /tmp/requirements_hca_schema.txt

# Final stage
FROM python:3.11-slim-bookworm

# Install runtime dependencies (if any)
# Install main requirements
COPY --from=builder /tmp/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
# Install CELLxGENE validator requirements
COPY --from=builder /tmp/requirements_cellxgene.txt /tmp/requirements_cellxgene.txt
RUN python -m venv /opt/venvs/cellxgene-validator \
  && /opt/venvs/cellxgene-validator/bin/pip install --no-cache-dir -r /tmp/requirements_cellxgene.txt
# Install HCA schema validator requirements
COPY --from=builder /tmp/requirements_hca_schema.txt /tmp/requirements_hca_schema.txt
RUN python -m venv /opt/venvs/hca-schema-validator \
  && /opt/venvs/hca-schema-validator/bin/pip install --no-cache-dir -r /tmp/requirements_hca_schema.txt

# Set environment variables for CELLxGENE validator paths
ENV CELLXGENE_VALIDATOR_VENV="/opt/venvs/cellxgene-validator"
ENV CELLXGENE_VALIDATOR_SCRIPT="/app/cellxgene_validator/main.py"
# Set environment variables for HCA schema validator paths
ENV HCA_SCHEMA_VALIDATOR_VENV="/opt/venvs/hca-schema-validator"
ENV HCA_SCHEMA_VALIDATOR_SCRIPT="/app/hca_schema_validator/main.py"
# HCA cell annotation validator runs in the HCA schema validator venv (same package)
ENV HCA_CELL_ANNOTATION_VALIDATOR_SCRIPT="/app/hca_schema_validator/cell_annotation.py"
# CAP validator script runs in the main venv (no separate venv needed)
ENV CAP_VALIDATOR_SCRIPT="/app/dataset_validator/cap_validator_script.py"
# Make `import hca_validation.*` resolvable for the main entrypoint. Use a
# dedicated import root (/opt/python) rather than exposing /app — subprocess
# validators inherit PYTHONPATH and exposing /app would shadow their installed
# packages with the matching sibling dirs (e.g. /app/hca_schema_validator/
# would shadow the PyPI hca_schema_validator package).
#
# Note: no `${PYTHONPATH}` suffix to avoid leaving a trailing colon when the
# inherited value is empty (the usual case). Python 3 expands empty PYTHONPATH
# entries to cwd at startup, which would silently re-add /app to sys.path.
# Dockerfile ENV substitution is build-time only anyway, so the "compose with
# inherited value" pattern can't solve runtime composition — `docker run -e`
# always overrides ENV entirely.
ENV PYTHONPATH="/opt/python"

# Copy application code
COPY services/dataset-validator/src/dataset_validator/ /app/dataset_validator/
COPY services/cellxgene-validator/src/cellxgene_validator/ /app/cellxgene_validator/
COPY services/hca-schema-validator/src/hca_schema_validator_service/ /app/hca_schema_validator/
# Copy shared library source to a dedicated import root (referenced by
# PYTHONPATH above). Keeping this out of /app avoids shadowing subprocess
# validators' installed packages.
COPY shared/src/hca_validation/ /opt/python/hca_validation/

# Set working directory
WORKDIR /app

# Set the entrypoint to run our main script
ENTRYPOINT ["python", "/app/dataset_validator/main.py"]
