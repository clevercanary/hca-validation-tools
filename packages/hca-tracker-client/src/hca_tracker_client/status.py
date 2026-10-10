"""The CAP ingest and HCA Tier 1 statuses the tracker shows in its lists but does not serve from its API.

Ported from hca-atlas-tracker ``app/apis/catalog/hca-atlas-tracker/common/utils.ts``
(``getCapIngestStatusFromParameters``, ``getHcaTier1ValidationStatus``); the tracker's
test cases are in ``tests/test_status.py``. A change to either rule there must be made here.
"""

# FILE_VALIDATOR_NAMES in the tracker, with the names the client returns them under.
VALIDATORS = {
    "cap": "cap",
    "cellxgene": "cellxgene",
    "hcaSchema": "hca_schema",
    "hcaCellAnnotation": "hca_cell_annotation",
}


def cap_status(summary: dict | None, cap_url: str | None, reprocessed_status: str | None = None) -> str:
    """The tracker's CAP ingest status, from the raw ``validationSummary``, ``capUrl`` and (source
    datasets only) ``reprocessedStatus``."""
    if reprocessed_status == "Reprocessed":
        return "NOT_REQUIRED"
    if reprocessed_status == "Unspecified":
        return "INFO_REQUIRED"
    cap = ((summary or {}).get("validators") or {}).get("cap")
    if cap is None or "valid" not in cap:
        return "NEEDS_VALIDATION"
    if cap["valid"]:
        return "PUBLISHED" if cap_url is not None else "CAP_READY"
    return "CAP_VALIDATION_FAILED"


def tier1_status(summary: dict | None) -> str:
    """The tracker's HCA Tier 1 status: the hcaSchema validator's verdict, UNKNOWN without one."""
    hca_schema = ((summary or {}).get("validators") or {}).get("hcaSchema")
    if hca_schema is None:
        return "UNKNOWN"
    return "VALID" if hca_schema.get("valid") else "INVALID"
