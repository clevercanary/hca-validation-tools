"""The package's one version and the files it ships (docs/schema-version-contract.md §1)."""

import json
import re
from importlib.metadata import version
from pathlib import Path

import hca_metadata_schema
import yaml
from hca_metadata_schema import CORE_SCHEMA_PATH, TIER_2_SCHEMA_PATH
from hca_metadata_schema.generated import core

_PACKAGE_DIR = Path(hca_metadata_schema.__file__).parent
_NPM_PACKAGE_JSON = Path(__file__).parents[1] / "data_dictionaries" / "package.json"
_MARKED_VERSION = re.compile(r'^version = "[^"]*"  # x-release-please-version$', flags=re.M)


def _core_yaml_version() -> str:
    return str(yaml.safe_load(CORE_SCHEMA_PATH.read_text())["version"])


def test_schema_paths_are_shipped_in_the_package():
    assert CORE_SCHEMA_PATH.is_file()
    assert CORE_SCHEMA_PATH.parent == _PACKAGE_DIR
    assert TIER_2_SCHEMA_PATH.is_file()
    assert TIER_2_SCHEMA_PATH.is_relative_to(_PACKAGE_DIR)


def test_only_the_two_roots_declare_a_version():
    declaring = sorted(
        str(path.relative_to(_PACKAGE_DIR))
        for path in _PACKAGE_DIR.rglob("*.yaml")
        if "version" in (yaml.safe_load(path.read_text()) or {})
    )
    assert declaring == ["core.yaml", "tier_2/tier_2.yaml"]


def test_every_copy_of_the_version_agrees():
    """release-please bumps all six; a missed marker would leave one behind, and npm out of step with PyPI."""
    versions = {
        "tier_2/tier_2.yaml": str(yaml.safe_load(TIER_2_SCHEMA_PATH.read_text())["version"]),
        "generated/core.py": core.version,
        "__init__.py": hca_metadata_schema.__version__,
        "pyproject.toml": version("hca-metadata-schema"),
        "data_dictionaries/package.json": json.loads(_NPM_PACKAGE_JSON.read_text())["version"],
    }
    assert versions == dict.fromkeys(versions, _core_yaml_version())


def test_generated_version_line_carries_the_release_please_marker():
    """`make gen-schema` adds the marker with sed; a gen-pydantic output change would silently drop it."""
    assert _MARKED_VERSION.search(Path(core.__file__).read_text())
