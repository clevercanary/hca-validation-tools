"""The tracker's own cases for CAP ingest and HCA Tier 1 status, ported one-to-one.

Sources in hca-atlas-tracker: ``__tests__/cap-ingest-status.utils.test.ts``
and ``__tests__/hca-tier1-validation-status.utils.test.ts``. Each test is
named after the tracker's ``it(...)`` string, so a case added there is easy
to find missing here. The tracker's fixtures default ``validationSummary`` to
None and (for source datasets) ``reprocessedStatus`` to ``Original``.
"""

import pytest

from hca_tracker_client.status import cap_status, tier1_status


def summary(**validators: dict) -> dict:
    return {"overallValid": all(v["valid"] for v in validators.values()), "validators": validators}


CAP_FAILED = {"errorCount": 3, "valid": False, "warningCount": 0}
CAP_OK = {"errorCount": 0, "valid": True, "warningCount": 0}
CAP_URL = "https://celltype.info/cellxgene/foo"

# -- getCapIngestStatus -------------------------------------------------------


def test_cap_not_required_for_reprocessed_source_datasets():
    assert cap_status(None, None, "Reprocessed") == "NOT_REQUIRED"


def test_cap_info_required_for_unspecified_reprocessed_status():
    assert cap_status(None, None, "Unspecified") == "INFO_REQUIRED"


def test_cap_needs_validation_when_validation_is_completed_without_summary():
    assert cap_status(None, None) == "NEEDS_VALIDATION"


def test_cap_validation_failed_when_cap_validator_is_unsuccessful_and_cap_url_is_not_set():
    assert cap_status(summary(cap=CAP_FAILED), None) == "CAP_VALIDATION_FAILED"


def test_cap_validation_failed_when_cap_validator_is_unsuccessful_and_cap_url_is_set():
    assert cap_status(summary(cap=CAP_FAILED), CAP_URL) == "CAP_VALIDATION_FAILED"


def test_cap_ready_when_cap_validator_is_successful_and_cap_url_is_not_set():
    assert cap_status(summary(cap=CAP_OK), None) == "CAP_READY"


def test_cap_published_when_cap_validator_is_successful_and_cap_url_is_set():
    assert cap_status(summary(cap=CAP_OK), CAP_URL) == "PUBLISHED"


def test_cap_needs_validation_when_completed_with_summary_but_no_cap_results():
    assert cap_status({"overallValid": False, "validators": {}}, None) == "NEEDS_VALIDATION"


def test_cap_needs_validation_when_validation_is_not_completed():
    # validationStatus "pending": the rule never looks at the status, only at the (absent) summary.
    assert cap_status(None, None) == "NEEDS_VALIDATION"


def test_cap_ready_when_status_is_requested_and_existing_summary_has_cap_successful():
    assert cap_status(summary(cap=CAP_OK), None) == "CAP_READY"


@pytest.mark.parametrize("reprocessed", ["Original", None])
def test_cap_original_source_datasets_and_integrated_objects_follow_the_cap_verdict(reprocessed):
    """``Original`` is the tracker fixture's default; the rule treats it like an integrated object."""
    assert cap_status(summary(cap=CAP_OK), CAP_URL, reprocessed) == "PUBLISHED"


# -- getHcaTier1ValidationStatus ----------------------------------------------


def test_tier1_unknown_when_validation_status_is_pending_with_no_existing_summary():
    assert tier1_status(None) == "UNKNOWN"


def test_tier1_unknown_when_validation_status_is_job_failed_with_no_existing_summary():
    assert tier1_status(None) == "UNKNOWN"


def test_tier1_unknown_when_validation_is_completed_without_a_summary():
    assert tier1_status(None) == "UNKNOWN"


def test_tier1_unknown_when_summary_has_no_hca_schema_entry():
    assert tier1_status({"overallValid": True, "validators": {}}) == "UNKNOWN"


def test_tier1_invalid_when_hca_schema_valid_is_false_and_nonzero_errors():
    assert tier1_status(summary(hcaSchema={"errorCount": 3, "valid": False, "warningCount": 5})) == "INVALID"


def test_tier1_valid_when_hca_schema_valid_is_true_and_zero_errors_regardless_of_warnings():
    assert tier1_status(summary(hcaSchema={"errorCount": 0, "valid": True, "warningCount": 7})) == "VALID"


def test_tier1_invalid_when_hca_schema_valid_is_false_even_with_error_count_zero():
    assert tier1_status(summary(hcaSchema={"errorCount": 0, "valid": False, "warningCount": 0})) == "INVALID"


def test_tier1_valid_when_status_is_job_failed_but_existing_summary_has_hca_schema_valid():
    assert tier1_status(summary(hcaSchema={"errorCount": 0, "valid": True, "warningCount": 0})) == "VALID"


def test_tier1_valid_when_status_is_requested_and_existing_summary_has_hca_schema_valid():
    assert tier1_status(summary(hcaSchema={"errorCount": 0, "valid": True, "warningCount": 0})) == "VALID"


def test_tier1_empty_hca_schema_entry_is_invalid_as_in_the_tracker():
    """JS truthiness: ``{}`` passes the tracker's ``!hcaSchema`` guard, then ``valid`` is undefined."""
    assert tier1_status({"overallValid": False, "validators": {"hcaSchema": {}}}) == "INVALID"
    assert cap_status({"overallValid": False, "validators": {"cap": {}}}, None) == "NEEDS_VALIDATION"


def test_tier1_ignores_the_other_validators():
    both = summary(cap=CAP_FAILED, hcaSchema={"errorCount": 0, "valid": True, "warningCount": 12})
    assert tier1_status(both) == "VALID"
    assert cap_status(both, None) == "CAP_VALIDATION_FAILED"
