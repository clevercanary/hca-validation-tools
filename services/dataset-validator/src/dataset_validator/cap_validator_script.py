#!/usr/bin/env python3
"""
Standalone CAP validator script.

Invoked as a subprocess by the dataset validator so that the CAP validator's
peak memory is released when the process exits, preventing memory pressure
on subsequent validators.

Interface contract (same as cellxgene/hca-schema validator scripts):
  - Takes the file path as the first CLI argument
  - Prints a JSON object to stdout: {"valid": bool, "errors": [...], "warnings": [...]}
"""

import io
import json
import os
import sys

from cap_upload_validator import UploadValidator
from cap_upload_validator.errors import CapException, CapMultiException


def main() -> None:
    file_path = sys.argv[1]

    valid = False
    errors: list[str] = []

    # Redirect stdout during validation so that any prints from
    # UploadValidator don't corrupt our JSON output.
    real_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        uv = UploadValidator(file_path)
        uv.validate()
        valid = True
    except CapMultiException as multi_ex:
        errors.extend(str(e) for e in multi_ex.ex_list)
    except (Exception, CapException) as e:
        errors.append(
            f"Encountered an unexpected error while calling CAP validator: {e}"
        )
    finally:
        # Capture anything the validator printed, then restore stdout
        captured = sys.stdout.getvalue()
        sys.stdout = real_stdout
        if captured:
            print(captured, file=sys.stderr)

    print(json.dumps({"valid": valid, "errors": errors, "warnings": []}))


if __name__ == "__main__":
    main()
