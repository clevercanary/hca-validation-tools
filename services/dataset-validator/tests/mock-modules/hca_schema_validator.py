import json
import sys

if __name__ == "__main__":
    # Like the real service script, refuse to run without a file path and an object kind
    if len(sys.argv) != 3 or sys.argv[2] not in ("source", "integrated"):
        sys.exit(f"mock hca_schema_validator expected <file_path> <object_kind>, got {sys.argv[1:]}")
    # Echo the kind, so a test can see which one reached the validator
    print(
        json.dumps({"valid": False, "warnings": [f"WARNING: test bar ({sys.argv[2]})"], "errors": ["ERROR: test bar"]})
    )
