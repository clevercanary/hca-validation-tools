import functools
import json
import os

import zstandard as zstd
from cellxgene_ontology_guide import supported_versions
from cellxgene_ontology_guide.ontology_parser import OntologyParser

# Override CL ontology data with a newer version bundled in our ontology_data/ directory.
# The bundled cellxgene-ontology-guide v1.9.0 ships CL v2025-07-30, which predates several
# salivary gland cell types added in Aug 2025 (CL:4052065–4052069). We generated an updated
# CL data file (v2025-12-17) using CZI's open-source ontology-builder pipeline and override
# only the CL data here; all other ontologies continue using the package's bundled data.
#
# TODO: Remove this overlay once cellxgene-ontology-guide publishes a version with CL >= v2025-10-16.

_ONTOLOGY_DATA_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "ontology_data")

_original_load_ontology_file = supported_versions.load_ontology_file.__wrapped__
_original_load_supported_versions = supported_versions.load_supported_versions


@functools.cache
def _load_ontology_file_with_overlay(file_name: str):
    """Load ontology file from our overlay directory if present, otherwise fall back to package data."""
    overlay_path = os.path.join(_ONTOLOGY_DATA_DIR, file_name)
    if os.path.exists(overlay_path):
        with open(overlay_path, "rb") as f:
            dctx = zstd.ZstdDecompressor()
            with dctx.stream_reader(f) as reader:
                return json.load(reader)
    return _original_load_ontology_file(file_name)


def _load_supported_versions_with_overlay():
    """Load ontology_info.json from our overlay directory."""
    overlay_path = os.path.join(_ONTOLOGY_DATA_DIR, "ontology_info.json")
    if os.path.exists(overlay_path):
        with open(overlay_path) as f:
            return json.load(f)
    return _original_load_supported_versions()


# Clear the original cache and apply our overrides
supported_versions.load_ontology_file.cache_clear()
supported_versions.load_ontology_file = _load_ontology_file_with_overlay
supported_versions.load_supported_versions = _load_supported_versions_with_overlay

ONTOLOGY_PARSER = OntologyParser(schema_version="v7.0.0")
