#!/usr/bin/env python3
"""
expand_schema.py  –  Flatten a LinkML schema into one JSON document for data dictionary generation.

• Resolves/merges all imports
• Keeps every class, slot, type and enum definition
• Works with local paths, relative paths or remote URLs
• Emits to STDOUT (default) or to a file you name

Requires:  pip install linkml linkml-runtime
"""

from __future__ import annotations
import sys
import json
from pathlib import Path
from typing import Union

from linkml_runtime.utils.schemaview import SchemaView          # introspection
from linkml_runtime.utils.schema_as_dict import schema_as_dict   # serialize


def expand(schema_source: Union[str, Path]) -> dict:
    """
    Load *schema_source* (file path or URL), merge its import closure,
    and return a plain-Python dictionary that can be dumped as JSON.
    """
    sv = SchemaView(str(schema_source), merge_imports=True)  # ← merges imports
    expanded = schema_as_dict(sv.schema)                     # dataclass → dict
    return expanded


def main() -> None:
    if len(sys.argv) < 2:
        sys.stderr.write("Usage:  python expand_schema.py <schema.yaml|URL> [output.json]\n")
        sys.exit(1)

    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else None

    schema_dict = expand(src)

    if dst:
        with open(dst, "w", encoding="utf-8") as fh:
            json.dump(schema_dict, fh, indent=2)
    else:
        json.dump(schema_dict, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
