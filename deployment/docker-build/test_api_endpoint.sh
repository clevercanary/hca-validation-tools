#!/bin/bash
set -e

# API Gateway endpoint URL
API_URL="https://yhdq3bmvmg.execute-api.us-east-1.amazonaws.com/prod/validate"

# Default sheet ID (can be overridden with command line argument)
SHEET_ID="1oPFb6qb0Y2HeoQqjSGRe_TlsZPRLwq-HUlVF0iqtVlY"

# Check if a sheet ID was provided as a command line argument
if [ "$1" != "" ]; then
    SHEET_ID="$1"
fi

echo "Testing API endpoint with sheet ID: $SHEET_ID"

# Call the API endpoint with curl
curl -X POST \
  "$API_URL" \
  -H 'Content-Type: application/json' \
  -d "{\"sheet_id\": \"$SHEET_ID\", \"sheet_index\": 0}"

echo -e "\n\nDone!"
