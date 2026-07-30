"""Tests for the schema introspection helpers in schema/helpers.py.

These assert membership rather than exact set sizes. A hard count would turn
any upstream LinkML change into a red test with no explanation of what moved,
whereas these fail only when something meaningful changed — and the
non-membership assertions below are load-bearing safety properties, not
incidental facts.
"""

from hca_anndata_tools.schema.helpers import (
    build_obs_column_tiers,
    obs_column_tiers,
    uns_field_registry,
)


def _required():
    return obs_column_tiers()[0]


def _optional():
    return obs_column_tiers()[1]


# How the breast-v1 source datasets carry ethnicity. None is a schema field.
_ETHNICITY_ALIASES = (
    "self_reported_ethnicity_label",
    "ethnicity_verbatim",
    "ethnicity_grouped",
    "reported_ethnicity",
    "race",
)

# Columns HCA forbids outright for privacy — schema-*forbidden*, so they appear
# in neither tier.
_FORBIDDEN = (
    "self_reported_ethnicity",
    "self_reported_ethnicity_ontology_term_id",
)

# Derived label outputs, regenerable by populate_labels from the matching
# *_ontology_term_id column.
_DERIVED_LABELS = (
    "tissue",
    "cell_type",
    "assay",
    "disease",
    "sex",
    "organism",
    "development_stage",
)


def test_required_tier_contains_known_required_columns():
    required = _required()
    for col in (
        "donor_id",
        "sample_id",
        "library_id",
        "library_sequencing_run",
        "organism_ontology_term_id",
        "tissue_ontology_term_id",
    ):
        assert col in required, f"{col} should be schema-required"


def test_optional_tier_contains_known_optional_columns():
    optional = _optional()
    for col in ("author_batch_notes", "tissue_free_text", "sequencing_platform"):
        assert col in optional, f"{col} should be schema-optional"


def test_tiers_are_disjoint():
    """A column required by any entity is required, even where another class
    declares it optional — the stricter tier wins."""
    assert not (_required() & _optional())


def test_bionetwork_only_required_columns_are_collected():
    """ambient_count_correction and doublet_detection live on the bionetwork
    Dataset subclasses, not base Dataset. If _OBS_CLASSES stopped walking the
    subclasses these would silently vanish from the guard."""
    required = _required()
    assert "ambient_count_correction" in required
    assert "doublet_detection" in required


def test_ethnicity_aliases_are_in_neither_tier():
    """The safety property drop_obs_columns depends on: if any alias were
    schema-named, the guard would refuse the drop this tool exists to perform."""
    named = _required() | _optional()
    for col in _ETHNICITY_ALIASES:
        assert col not in named, f"{col} must not be schema-named"


def test_forbidden_privacy_columns_are_in_neither_tier():
    """HCA forbids these outright, so they are absent from the schema rather
    than declared optional — meaning the guard cannot block stripping them."""
    named = _required() | _optional()
    for col in _FORBIDDEN:
        assert col not in named, f"{col} is forbidden, not schema-named"


def test_derived_label_columns_are_in_neither_tier():
    """Derived labels carry no guard because they are regenerable. That holds
    only while they stay absent from both tiers."""
    named = _required() | _optional()
    for col in _DERIVED_LABELS:
        assert col not in named, f"{col} is a derived label, not a schema obs field"


def test_obs_tiers_and_uns_registry_do_not_overlap():
    """A field is obs or uns by its annDataLocation, never both. An overlap
    would mean the introspection is misreading the annotation."""
    named_obs = _required() | _optional()
    assert not (named_obs & set(uns_field_registry()))


def test_tiers_are_cached():
    """The builder walks model_fields across nine Pydantic classes, so the
    result is cached. Identity, not equality — two equal frozensets built
    fresh each call would pass an equality check while losing the cache."""
    assert obs_column_tiers() is obs_column_tiers()
    # The uncached builder is what the cache wraps; it must agree with it.
    assert build_obs_column_tiers() == obs_column_tiers()
