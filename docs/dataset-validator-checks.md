# Dataset Validator — Batch Service Checks

The dataset validator runs as an AWS Batch job. It makes its own integrity checks, then runs three validators (CAP, CELLxGENE, HCA schema) on the file. This document covers what the Batch service adds; what the CELLxGENE and HCA schema validators check is in the [`hca-schema-validator` README](../packages/hca-schema-validator/README.md#what-this-validator-checks).

Source files:
- Orchestrator: `services/dataset-validator/src/dataset_validator/main.py`
- CAP wrapper: `services/dataset-validator/src/dataset_validator/cap_validator_script.py`
- CELLxGENE wrapper: `services/cellxgene-validator/src/cellxgene_validator/main.py`
- HCA wrapper: `services/hca-schema-validator/src/hca_schema_validator_service/main.py`
- HCA validator: `packages/hca-schema-validator/src/hca_schema_validator/validator.py`
- Vendored core: `packages/hca-schema-validator/src/hca_schema_validator/_vendored/cellxgene_schema/`

---

## 1. Orchestration-level checks (`main.py`)

Run before any schema validator:

- **Required env vars present** — `S3_BUCKET`, `S3_KEY`, `FILE_ID`, `SNS_TOPIC_ARN`, `AWS_BATCH_JOB_ID` (bypassed when `LOCAL_FILE` is set).
- **S3 object has `source-sha256` metadata** — hard-fail if missing.
- **File integrity** — SHA256 computed on the downloaded file must match the S3 metadata hash.
- **Metadata summary readable** — opens the h5ad in backed mode and extracts `uns.title`, `obs.assay`, `obs.suspension_type`, `obs.tissue`, `obs.disease`, `n_obs`, `n_vars`.

Each downstream validator runs as a subprocess (memory isolation) and its result is aggregated under `tool_reports.{cap, cellxgene, hcaSchema}`.

---

## 2. CAP validator (`cap_upload_validator.UploadValidator`)

Runs the external `cap_upload_validator` package against the file. Validates CAP's cell-annotation-platform upload contract: cell label tables, marker genes, and annotation provenance structures in `obs`/`uns`. `CapException` / `CapMultiException` messages are surfaced as errors; warnings are not captured.

---

## 3. CELLxGENE validator (vendored `cellxgene_schema.validate.validate`)

Runs the vendored CELLxGENE validator against the unmodified CELLxGENE schema. The rules are the [core CELLxGENE checks](../packages/hca-schema-validator/README.md#core-cellxgene-checks), without the HCA overrides or extensions.

---

## 4. HCA schema validator (`HCAValidator`)

Runs `HCAValidator` from the `hca-schema-validator` package. Every check it makes — the core CELLxGENE checks, the HCA overrides and the HCA extensions — is listed, with the reason for each, in the [package README](../packages/hca-schema-validator/README.md#what-this-validator-checks). This document does not repeat them.

---

## Cross-reference

| Stage | Source | Fail mode |
|---|---|---|
| Env & S3 integrity | `main.py` | Hard fail, no tool reports |
| Metadata summary | `main.py:read_metadata` | Exception → failure message |
| CAP | `cap_validator_script.py` | `tool_reports.cap.errors` |
| CELLxGENE | `services/cellxgene-validator` → vendored `validate()` | `tool_reports.cellxgene` |
| HCA | `services/hca-schema-validator` → `HCAValidator` | `tool_reports.hcaSchema` |
