import json
import os
import sys

if __name__ == "__main__":
    # Allow tests to inject an error via environment variable
    error = os.environ.get("CAP_MOCK_ERROR")
    if error:
        print(json.dumps({"valid": False, "errors": [f"Encountered an unexpected error while calling CAP validator: {error}"], "warnings": []}))
    else:
        print(json.dumps({"valid": True, "errors": [], "warnings": []}))
