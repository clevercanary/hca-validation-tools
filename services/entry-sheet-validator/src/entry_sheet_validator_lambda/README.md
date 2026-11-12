# HCA Entry Sheet Validator Lambda Function

This AWS Lambda function validates Google Sheets using the HCA validation tools. It accepts a Google Sheet ID, validates the sheet against the HCA schema, and returns validation results as JSON.

## Deployment

The function runs as a container image. To build, deploy and invoke it, see
[Deploying to AWS](../../../../deployment/entry-sheet-validator/README.md#deploying-to-aws).
The deploy only updates an existing function; creating the function is a one-time
setup step.

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
    "sheet_title": "Test Copy of AgaceHelmsley_HCA_tier 1_metadata",
    "last_updated": {
      "date": "2025-05-14T07:39:12.419Z",
      "by": "foo",
      "by_email": "foo@example.com"
    },
    "errors": [
      {
        "entity_type": "dataset",
        "worksheet_id": 1895379728,
        "message": "Input should be a valid list",
        "row": 7,
        "column": "batch_condition",
        "cell": "F8",
        "primary_key": "dataset_id:AgaceHelmsley3",
        "input": "donor_id"
      }
    ],
    "valid": false,
    "error_code": "validation_error",
    "summary": {
      "dataset_count": 3,
      "donor_count": 11,
      "sample_count": 44,
      "error_count": 1
    },
    "memory_usage": {
      "initial": {
        "memory_used_mb": 80.5,
        "memory_limit_mb": 0,
        "memory_utilization_percent": null
      },
      "pre_validation": {
        "memory_used_mb": 80.53,
        "memory_limit_mb": 0,
        "memory_utilization_percent": null
      },
      "post_validation": {
        "memory_used_mb": 87.62,
        "memory_limit_mb": 0,
        "memory_utilization_percent": null
      }
    }
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
