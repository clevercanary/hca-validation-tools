"""Unit tests for metadata_coverage payload assembly (#405).

Tests use fabricated SimpleNamespace AnnData stand-ins — only `.obs` (DataFrame)
and `.uns` (dict) are needed by compute_metadata_coverage.
"""

from types import SimpleNamespace
from typing import Any, Dict, List

import pandas as pd
import pytest

from hca_validation.metadata_coverage import compute_metadata_coverage, SCHEMA_NAME
from hca_validation.metadata_coverage.metadata_coverage import _assert_invariant
from hca_validation.schema_utils import load_schemaview


@pytest.fixture(scope="module")
def schemaview():
    return load_schemaview()


def make_adata(obs: pd.DataFrame, uns: Dict[str, Any] | None = None):
    return SimpleNamespace(obs=obs, uns=uns or {})


def field_entry(result: Dict[str, Any], entity_class: str, field: str) -> Dict[str, Any]:
    for entry in result["field_coverage"]:
        if entry["entity_class"] == entity_class and entry["field"] == field:
            return entry
    raise AssertionError(
        f"missing field_coverage entry for ({entity_class}, {field}); "
        f"emitted: {[(e['entity_class'], e['field']) for e in result['field_coverage']]}"
    )


class TestEntities:
    def test_record_counts_use_distinct_identifier_values(self, schemaview):
        obs = pd.DataFrame({
            "donor_id":  ["D1", "D1", "D2", "D2", "D2"],
            "sample_id": ["S1", "S1", "S2", "S2", "S3"],
        })
        result = compute_metadata_coverage(make_adata(obs), schemaview)
        assert result["entities"]["obs"]["record_count"] == 5
        assert result["entities"]["dataset"]["record_count"] == 1
        assert result["entities"]["donor"]["record_count"] == 2
        assert result["entities"]["sample"]["record_count"] == 3

    def test_donor_count_excludes_cells_with_missing_donor_id(self, schemaview):
        obs = pd.DataFrame({
            "donor_id":  ["D1", "D1", None, None, "D2"],
            "sample_id": ["S1", "S1", "S2", "S2", "S3"],
        })
        result = compute_metadata_coverage(make_adata(obs), schemaview)
        assert result["entities"]["donor"]["record_count"] == 2

    def test_dataset_record_count_is_always_one(self, schemaview):
        obs = pd.DataFrame({"donor_id": ["D1"], "sample_id": ["S1"]})
        result = compute_metadata_coverage(make_adata(obs), schemaview)
        assert result["entities"]["dataset"]["record_count"] == 1


class TestObsGrainIdentifierCoverage:
    def test_full_donor_id_population_has_no_issues(self, schemaview):
        obs = pd.DataFrame({
            "donor_id":  ["D1", "D2", "D3"],
            "sample_id": ["S1", "S2", "S3"],
        })
        result = compute_metadata_coverage(make_adata(obs), schemaview)
        donor_id = field_entry(result, "obs", "donor_id")
        assert donor_id == {"entity_class": "obs", "field": "donor_id", "complete": 3, "issues": {}}

    def test_missing_donor_id_reported_at_obs_grain_only(self, schemaview):
        obs = pd.DataFrame({
            "donor_id":  ["D1", "D1", None, None, "D2"],
            "sample_id": ["S1", "S1", "S2", "S2", "S3"],
        })
        result = compute_metadata_coverage(make_adata(obs), schemaview)
        entry = field_entry(result, "obs", "donor_id")
        assert entry["complete"] == 3
        assert entry["issues"] == {"missing": 2}


class TestEntityPropertyCoverage:
    def test_complete_field_emits_empty_issues(self, schemaview):
        obs = pd.DataFrame({
            "donor_id":  ["D1", "D1", "D2"],
            "sample_id": ["S1", "S1", "S2"],
            "sex_ontology_term_id": ["PATO:0000383", "PATO:0000383", "PATO:0000384"],
        })
        result = compute_metadata_coverage(make_adata(obs), schemaview)
        entry = field_entry(result, "donor", "sex_ontology_term_id")
        assert entry == {
            "entity_class": "donor",
            "field": "sex_ontology_term_id",
            "complete": 2,
            "issues": {},
        }

    def test_partial_population_buckets_as_missing(self, schemaview):
        obs = pd.DataFrame({
            "donor_id":  ["D1", "D1", "D2", "D2"],
            "sample_id": ["S1", "S1", "S2", "S2"],
            "manner_of_death": ["1", "1", None, "3"],  # D2 has one null row
        })
        result = compute_metadata_coverage(make_adata(obs), schemaview)
        entry = field_entry(result, "donor", "manner_of_death")
        assert entry["complete"] == 1
        assert entry["issues"] == {"missing": 1}

    def test_disagreeing_values_bucket_as_inconsistent(self, schemaview):
        obs = pd.DataFrame({
            "donor_id":  ["D1", "D1", "D2", "D2"],
            "sample_id": ["S1", "S1", "S2", "S2"],
            "manner_of_death": ["1", "2", "3", "3"],  # D1 has two distinct values
        })
        result = compute_metadata_coverage(make_adata(obs), schemaview)
        entry = field_entry(result, "donor", "manner_of_death")
        assert entry["complete"] == 1
        assert entry["issues"] == {"inconsistent": 1}

    def test_inconsistent_wins_over_missing_for_same_field(self, schemaview):
        # D1 has both null and conflicting values (inconsistent precedence applies).
        # D2 has only nulls (missing).
        # D3 is complete.
        obs = pd.DataFrame({
            "donor_id":  ["D1", "D1", "D1", "D2", "D2", "D3", "D3"],
            "sample_id": ["S1", "S1", "S1", "S2", "S2", "S3", "S3"],
            "manner_of_death": ["1", "2", None, None, None, "0", "0"],
        })
        result = compute_metadata_coverage(make_adata(obs), schemaview)
        entry = field_entry(result, "donor", "manner_of_death")
        assert entry["complete"] == 1  # D3
        assert entry["issues"] == {"inconsistent": 1, "missing": 1}

    def test_field_absent_from_obs_reports_all_missing(self, schemaview):
        obs = pd.DataFrame({
            "donor_id":  ["D1", "D1", "D2"],
            "sample_id": ["S1", "S1", "S2"],
        })
        result = compute_metadata_coverage(make_adata(obs), schemaview)
        entry = field_entry(result, "donor", "manner_of_death")
        assert entry["complete"] == 0
        assert entry["issues"] == {"missing": 2}


class TestDatasetClassSlots:
    def test_uns_slot_complete_when_populated(self, schemaview):
        obs = pd.DataFrame({"donor_id": ["D1"], "sample_id": ["S1"]})
        uns = {"description": "An interesting dataset", "study_pi": ["Foo"]}
        result = compute_metadata_coverage(make_adata(obs, uns), schemaview)
        assert field_entry(result, "dataset", "description")["complete"] == 1
        assert field_entry(result, "dataset", "study_pi")["complete"] == 1

    def test_uns_slot_missing_when_absent(self, schemaview):
        obs = pd.DataFrame({"donor_id": ["D1"], "sample_id": ["S1"]})
        result = compute_metadata_coverage(make_adata(obs), schemaview)
        entry = field_entry(result, "dataset", "description")
        assert entry == {
            "entity_class": "dataset",
            "field": "description",
            "complete": 0,
            "issues": {"missing": 1},
        }

    def test_uns_slot_empty_string_treated_as_missing(self, schemaview):
        obs = pd.DataFrame({"donor_id": ["D1"], "sample_id": ["S1"]})
        result = compute_metadata_coverage(make_adata(obs, {"description": ""}), schemaview)
        assert field_entry(result, "dataset", "description")["complete"] == 0

    def test_dataset_obs_slot_complete_when_consistent(self, schemaview):
        # gene_annotation_version is annDataLocation=obs but owned by the Dataset class.
        obs = pd.DataFrame({
            "donor_id":  ["D1", "D1", "D2"],
            "sample_id": ["S1", "S1", "S2"],
            "gene_annotation_version": ["v1", "v1", "v1"],
        })
        result = compute_metadata_coverage(make_adata(obs), schemaview)
        entry = field_entry(result, "dataset", "gene_annotation_version")
        assert entry["complete"] == 1
        assert entry["issues"] == {}

    def test_dataset_obs_slot_inconsistent_across_cells(self, schemaview):
        obs = pd.DataFrame({
            "donor_id":  ["D1", "D2"],
            "sample_id": ["S1", "S2"],
            "gene_annotation_version": ["v1", "v2"],
        })
        result = compute_metadata_coverage(make_adata(obs), schemaview)
        entry = field_entry(result, "dataset", "gene_annotation_version")
        assert entry["complete"] == 0
        assert entry["issues"] == {"inconsistent": 1}


class TestSchemaMetadata:
    def test_schema_name_is_tier_1(self, schemaview):
        obs = pd.DataFrame({"donor_id": ["D1"], "sample_id": ["S1"]})
        result = compute_metadata_coverage(make_adata(obs), schemaview)
        assert result["schema_name"] == "tier_1"
        assert SCHEMA_NAME == "tier_1"

    def test_schema_version_pulled_from_linkml(self, schemaview):
        obs = pd.DataFrame({"donor_id": ["D1"], "sample_id": ["S1"]})
        result = compute_metadata_coverage(make_adata(obs), schemaview)
        assert result["schema_version"] == schemaview.schema.version


class TestInvariant:
    def test_passes_for_real_output(self, schemaview):
        obs = pd.DataFrame({
            "donor_id":  ["D1", "D1", "D2", None],
            "sample_id": ["S1", "S1", "S2", "S2"],
            "manner_of_death": ["1", "2", "3", "3"],
        })
        result = compute_metadata_coverage(make_adata(obs), schemaview)
        for entry in result["field_coverage"]:
            expected = result["entities"][entry["entity_class"]]["record_count"]
            assert entry["complete"] + sum(entry["issues"].values()) == expected, entry

    def test_violation_raises_assertion_error(self):
        entities = {"donor": {"record_count": 10}}
        bad: List[Dict[str, Any]] = [
            {"entity_class": "donor", "field": "x", "complete": 5, "issues": {"missing": 4}}
        ]
        with pytest.raises(AssertionError, match="invariant violated"):
            _assert_invariant(entities, bad)


class TestFieldCoverageEnumeration:
    def test_all_eligible_slots_emit_an_entry_even_when_data_absent(self, schemaview):
        obs = pd.DataFrame({"donor_id": ["D1"], "sample_id": ["S1"]})
        result = compute_metadata_coverage(make_adata(obs), schemaview)
        donor_fields = {e["field"] for e in result["field_coverage"] if e["entity_class"] == "donor"}
        # Real schema-driven assertion: known Donor entity-property slots show up.
        assert {"sex_ontology_term_id", "manner_of_death", "organism_ontology_term_id"} <= donor_fields

    def test_deprecated_slots_excluded(self, schemaview):
        obs = pd.DataFrame({"donor_id": ["D1"], "sample_id": ["S1"]})
        result = compute_metadata_coverage(make_adata(obs), schemaview)
        all_fields = {(e["entity_class"], e["field"]) for e in result["field_coverage"]}
        # `sex_ontology_term` and `assay_ontology_term` and `title` are deprecated.
        assert ("donor", "sex_ontology_term") not in all_fields
        assert ("dataset", "assay_ontology_term") not in all_fields
        assert ("dataset", "title") not in all_fields

    def test_foreign_key_slots_excluded(self, schemaview):
        obs = pd.DataFrame({"donor_id": ["D1"], "sample_id": ["S1"]})
        result = compute_metadata_coverage(make_adata(obs), schemaview)
        # dataset_id is a FK slot on Donor and Sample — should not appear at those grains.
        all_pairs = {(e["entity_class"], e["field"]) for e in result["field_coverage"]}
        assert ("donor", "dataset_id") not in all_pairs
        assert ("sample", "dataset_id") not in all_pairs
