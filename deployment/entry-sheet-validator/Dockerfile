# Build stage
FROM --platform=linux/amd64 public.ecr.aws/lambda/python:3.10 AS builder

# Install Poetry
RUN pip install poetry==1.7.1

# Copy Poetry configuration files
COPY pyproject.toml poetry.lock* ./

# Configure Poetry to not create a virtual environment
RUN poetry config virtualenvs.create false

# Install dependencies (for wheel building, not runtime)
RUN poetry install --no-dev

# Export requirements and install with pip to /opt/python
RUN poetry export --without-hashes -o /tmp/requirements.txt && \
    pip install --no-cache-dir -r /tmp/requirements.txt --target /opt/python

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

# Copy application code
COPY src/hca_validation/ /var/task/hca_validation/

# Copy config.yaml for the AWS Parameters and Secrets Extension
COPY config.yaml /var/task/config.yaml

# Set the Lambda handler
CMD ["hca_validation.lambda_functions.entry_sheet_validator_lambda.handler.handler"]
