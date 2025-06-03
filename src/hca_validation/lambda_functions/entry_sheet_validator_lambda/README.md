# HCA Entry Sheet Validator Lambda Function

This AWS Lambda function validates Google Sheets using the HCA validation tools. It accepts a Google Sheet ID, validates the sheet against the HCA schema, and returns validation results as JSON.

## Deployment

### Prerequisites

- AWS CLI installed and configured
- Python 3.10
- An AWS IAM role with Lambda execution permissions

### Deployment Steps

#### 1. Build the minimal Lambda deployment package

```bash
# Build the Entry Sheet Validator Lambda package
make build-entry-sheet-validator-lambda
```

This creates a truly minimal deployment package (about 20KB) named `entry_sheet_validator_lambda.zip` that contains only your application code with no dependencies. All dependencies will be provided by AWS Lambda Layers.

#### 2. Build Lambda Layers for dependencies

To ensure compatibility with AWS Lambda, we'll use Docker with Amazon Linux to build the Lambda layers:

**Step 1: Use the AWS SDK for pandas Layer (Recommended)**

AWS provides an official Lambda Layer that includes both NumPy and pandas:
- `AWSSDKPandas-Python310`

This layer is maintained by AWS and available in all regions.

**Step 2: Build a Lambda Layer for linkml and other dependencies using Docker**

We've set up a Docker-based build process to ensure compatibility with the AWS Lambda environment:

```bash
# Build the LinkML dependencies layer
make build-linkml-dependencies-layer
```

This creates a Lambda layer with all the LinkML dependencies. The layer will be created at `deployment/layers/linkml_dependencies_layer.zip`.

The build process uses Docker with Amazon Linux to create a compatible Lambda layer containing:
- requests
- pyyaml
- linkml-runtime
- linkml-validator

**Step 3: Upload the linkml dependencies layer to AWS**

```bash
# Set your AWS account ID and region
export AWS_ACCOUNT_ID=<your-account-id>
export AWS_REGION=<your-region>

# Upload the layer to AWS
aws lambda publish-layer-version \
  --layer-name linkml-dependencies \
  --description "LinkML and other dependencies for Python 3.10" \
  --zip-file fileb://deployment/layers/linkml_dependencies_layer.zip \
  --compatible-runtimes python3.10 \
  --region $AWS_REGION
```

#### 3. Deploy the Lambda function with the Layers

We've added a convenient make target to deploy the Lambda function with both layers:

```bash
# Set required environment variables
export AWS_ACCOUNT_ID=<your-account-id>
export AWS_REGION=<your-region>
export LAMBDA_ROLE=arn:aws:iam::<your-account-id>:role/lambda-execution-role

# Deploy the Lambda function
make deploy-lambda
```

This will:
1. Build the minimal Lambda package
2. Build the linkml dependencies layer using Docker
3. Deploy the function with both the AWSSDKPandas-Python310 and linkml-dependencies layers

If the function already exists, it will update the function code and configuration.

#### 4. Update the Lambda function (for subsequent deployments)

```bash
aws lambda update-function-code \
  --function-name hca-entry-sheet-validator \
  --zip-file fileb://deployment/entry_sheet_validator_lambda.zip
```

## Usage

The Lambda function accepts the following parameters:

- `sheet_id` (required): The ID of the Google Sheet to validate

### Example Event

```json
{
  "sheet_id": "1oPFb6qb0Y2HeoQqjSGRe_TlsZPRLwq-HUlVF0iqtVlY"
}
```

### Example Response

```json
{
  "statusCode": 200,
  "body": {
    "sheet_id": "1oPFb6qb0Y2HeoQqjSGRe_TlsZPRLwq-HUlVF0iqtVlY",
    "valid": false,
    "errors": [
      {
        "row": 4,
        "message": "Validation error: Missing required field 'title'",
        "field": "title",
        "value": null
      }
    ]
  }
}
```

## Local Testing

You can test the Lambda function locally:

```bash
cd /path/to/hca-validation-tools
python -m hca_validation.lambda_functions.entry_sheet_validator_lambda.handler
```

This will run the `handler` function with a sample event and print the results.

## API Gateway Integration

To expose the Lambda function as an HTTP endpoint, you can integrate it with Amazon API Gateway:

1. Create a new REST API in API Gateway
2. Create a new resource (e.g., `/validate`)
3. Create a POST method for the resource
4. Set the Integration type to "Lambda Function"
5. Select the `hca-entry-sheet-validator` function
6. Deploy the API to a stage (e.g., `prod`)

The endpoint will be available at:
```
https://<api-id>.execute-api.<region>.amazonaws.com/<stage>/validate
```

You can then send a POST request to this endpoint with a JSON body containing the `sheet_id` parameter.
