"""Tests for the schema introspection helpers in schema/helpers.py.

These assert membership rather than exact set sizes. A hard count would turn
any upstream LinkML change into a red test with no explanation of what moved,
whereas these fail only when something meaningful changed — and the
non-membership assertions below are load-bearing safety properties, not
incidental facts.
"""

from pydantic import BaseModel

from hca_anndata_tools.schema.helpers import (
    _entity_classes,
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


def test_columns_538_made_visible_are_tiered():
    """#538 (PR #545) added the LinkML declarations these four depend on.

    Before it, `Cell` was a bare `pass` and two `Sample` slots carried no
    `annDataLocation`, so all four were invisible to this walk and `drop_obs_columns`
    deleted them without complaint. Asserted here as well as in test_drop because the
    two failures look different: here it means the bundled model went stale, there it
    means the guard stopped consulting it.

    `sample_collection_method` is required; the Cell pair and `is_primary_data` are
    optional, matching the h5ad validator's requirement levels.
    """
    assert "sample_collection_method" in _required()
    for col in ("cell_type_ontology_term_id", "author_cell_type", "is_primary_data"):
        assert col in _optional(), f"{col} should be schema-optional"


def test_cell_entity_contributes_obs_columns():
    """The `Cell` class is reachable from the entity walk and contributes columns.

    `Cell` was empty until #538, so this is the first thing that would break if a
    regeneration lost the class or the walk stopped reaching it — a silent failure
    otherwise, since the tiers would simply come back two columns lighter.
    """
    from hca_anndata_tools.schema.core import Cell

    assert Cell in _entity_classes()
    assert {"author_cell_type", "cell_type_ontology_term_id"} <= _optional()


def test_tiers_are_disjoint():
    """A column required by any entity is required, even where another class
    declares it optional — the stricter tier wins."""
    assert not (_required() & _optional())


def test_entity_classes_are_derived_not_enumerated():
    """`allowed_bionetwork_names` in shared declares 18 bionetworks against the 3
    that currently have schema classes. A hardcoded class list would silently go
    stale the first time one of the other 15 gains a subclass, and stale here
    means a required column quietly losing its guard in drop_obs_columns.

    Pins that the walk reaches every entity class in the module, so adding a
    bionetwork needs no change here."""
    from hca_anndata_tools.schema import core

    derived = {c.__name__ for c in _entity_classes()}
    # Every model class in core.py that subclasses one of the four entity bases
    # must be reachable. Compare against an independent scan of the module.
    bases = {"Dataset", "Donor", "Sample", "Cell"}
    expected = {
        name
        for name, obj in vars(core).items()
        if isinstance(obj, type)
        and issubclass(obj, BaseModel)
        and (name in bases or bases & {b.__name__ for b in obj.__mro__})
        and name not in ("ConfiguredBaseModel", "BaseModel")
    }
    assert derived == expected, f"unreachable entity classes: {expected - derived}"


def test_bionetwork_only_required_columns_are_collected():
    """ambient_count_correction and doublet_detection live on the bionetwork
    Dataset subclasses, not base Dataset. If the subclass walk stopped reaching
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
