# Build stage
FROM --platform=linux/amd64 public.ecr.aws/lambda/python:3.10 AS builder

# Bring in uv (pinned for reproducible builds — do not use :latest).
COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /bin/uv

# Set up the directory structure to match the expected paths
WORKDIR /build

# Copy shared library first (path dependency source)
COPY shared/ ./shared/

# Copy the service's uv project files
COPY services/entry-sheet-validator/pyproject.toml services/entry-sheet-validator/uv.lock ./services/entry-sheet-validator/

# Change to service directory for uv operations
WORKDIR /build/services/entry-sheet-validator

# Export the locked runtime dependency closure and install it into /opt/python.
#   --no-dev             the Lambda ships no test deps (pytest/moto/...)
#   --no-emit-project    entry-sheet is a virtual project — nothing to install
#   --no-emit-package …  shared is served as source from /var/task (final stage),
#                        so only its dependencies go into /opt/python, not shared itself
# The build-image python (3.10) is pinned so environment markers resolve for the
# runtime interpreter, not the builder's default.
RUN uv export --frozen --no-hashes --no-dev \
        --no-emit-project --no-emit-package hca-validation-shared \
        -o /tmp/requirements.txt && \
    uv pip install --no-cache --python /var/lang/bin/python --target /opt/python \
        -r /tmp/requirements.txt

# Download and unpack the AWS Parameters and Secrets Lambda Extension (v5) using a presigned URL
ARG EXT_URL
RUN yum install -y unzip file
RUN echo "EXT_URL=$EXT_URL"
RUN curl -s "$EXT_URL" -o /tmp/ps-ext.zip && \
    file /tmp/ps-ext.zip && \
    unzip -q /tmp/ps-ext.zip -d /opt && \
    chmod +x /opt/extensions/*

# Final stage
FROM --platform=linux/amd64 public.ecr.aws/lambda/python:3.10

# Copy dependencies from builder stage
COPY --from=builder /opt/python /opt/python

# Copy the extension from builder stage
COPY --from=builder /opt/extensions/ /opt/extensions/

# Copy Lambda function code
COPY services/entry-sheet-validator/src/entry_sheet_validator_lambda/ /var/task/entry_sheet_validator_lambda/
# Copy shared library to container
COPY shared/src/hca_validation/ /var/task/hca_validation/

# Copy config.yaml for the AWS Parameters and Secrets Extension
COPY deployment/entry-sheet-validator/config.yaml /var/task/config.yaml

# Set the Lambda handler
CMD ["entry_sheet_validator_lambda.handler.handler"]
