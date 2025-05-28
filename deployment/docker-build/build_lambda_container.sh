#!/bin/bash
set -e

# Directory containing this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

echo "Building Lambda container image..."

PROFILE_ARG=""
if [ -n "$1" ]; then
  PROFILE_ARG="--profile $1"
fi
REGION="${2:-us-east-1}"
LAYER_ARN="arn:aws:lambda:${REGION}:177933569100:layer:AWS-Parameters-and-Secrets-Lambda-Extension:17"

EXT_URL=$(aws $PROFILE_ARG lambda get-layer-version-by-arn \
    --region "$REGION" --arn "$LAYER_ARN" \
    --query 'Content.Location' --output text)
if [ -z "$EXT_URL" ]; then
  echo "Failed to resolve presigned extension URL. Aborting build." >&2
  exit 1
fi

docker build --platform=linux/amd64 --build-arg EXT_URL="$EXT_URL" -t hca-entry-sheet-validator -f deployment/docker-build/Dockerfile .