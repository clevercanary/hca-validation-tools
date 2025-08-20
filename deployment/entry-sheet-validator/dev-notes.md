# Developer Notes: Lambda Container Build & Deployment

## Overview
This document summarizes the approach, technical decisions, and workflow for building and deploying the HCA Entry Sheet Validator as an AWS Lambda container image, including secure integration with the AWS Parameters and Secrets Lambda Extension.

---

## 1. Dependency Management: Poetry & pip
- **Development:** Poetry is used for dependency management and reproducible local environments.
- **Lambda Runtime:** The Dockerfile installs Poetry, uses it to install dependencies, and then exports them to a `requirements.txt` file. pip then installs these into `/opt/python` (the Lambda layer directory), ensuring compatibility with AWS Lambda's expectations.

**Why?** Poetry provides a modern workflow for development, but AWS Lambda expects dependencies in a pip-installable format and directory structure.

---

## 2. AWS Parameters and Secrets Lambda Extension
- **Purpose:** This extension allows the Lambda function to securely access secrets from AWS Secrets Manager and SSM Parameter Store at runtime.
- **Distribution:** The extension is distributed as a Lambda Layer, not a public file. It must be fetched using a presigned URL.

---

## 3. Fetching the Extension via Presigned URL
- The build script (`build_lambda_container.sh`) uses the AWS CLI to fetch a presigned URL for the extension layer:
  ```bash
  EXT_URL=$(aws $PROFILE_ARG lambda get-layer-version-by-arn \
      --region "$REGION" --arn "$LAYER_ARN" \
      --query 'Content.Location' --output text)
  ```
- The script allows specifying an AWS profile as its first argument, ensuring the correct credentials and permissions are used.
- The presigned URL is passed as a Docker build argument (`EXT_URL`).

---

## 4. Permissions Required
- The AWS CLI user/profile must have permission to call `lambda:get-layer-version-by-arn` for the extension layer ARN.
- If permissions are missing, the script will fail to obtain the presigned URL and abort the build.

---

## 5. Docker Build Orchestration
- The Dockerfile uses the `EXT_URL` build argument to download and unpack the extension ZIP at build time:
  ```dockerfile
  ARG EXT_URL
  RUN curl -sSL "$EXT_URL" -o /tmp/ps-ext.zip \
      && unzip -q /tmp/ps-ext.zip -d /opt \
      && chmod +x /opt/extensions/*
  ```
- The Docker build is invoked by the script, keeping orchestration and build logic separate for maintainability.

---

## 6. Automation & Deployment
- The Makefile provides targets to:
  - Build the container image (`make build-lambda-container`)
  - Push to ECR and deploy/update the Lambda function (`make deploy-lambda-container`)
- Environment variables (like `AWS_PROFILE`, `AWS_ACCOUNT_ID`, etc.) are used to control deployment and ensure flexibility.

---

## 7. Testing & Invocation
- Local testing is supported via Docker and helper scripts.
- Production testing can be done via the Lambda Function URL, e.g.:
  ```bash
  curl -X POST \
    -H "Content-Type: application/json" \
    -d '{"sheet_id": "YOUR_GOOGLE_SHEET_ID"}' \
    https://<your-lambda-function-url>
  ```

---

## 8. Key Design Decisions
- Use Poetry for local/dev, pip for Lambda runtime.
- Fetch AWS extension securely at build time using a presigned URL.
- Require correct IAM permissions for build-time resource access.
- Keep build logic (Dockerfile) and orchestration (shell script) separate.
- Automate with Makefile and scripts for reproducibility and ease of use.

---

## References
- [AWS Lambda Extensions Documentation](https://docs.aws.amazon.com/lambda/latest/dg/using-extensions.html)
- [AWS Lambda Function URLs](https://docs.aws.amazon.com/lambda/latest/dg/urls-invocation.html)
- [Poetry Documentation](https://python-poetry.org/docs/)

---

_Last updated: 2025-05-26_
