# Dataset Validator — Batch Service Checks

The dataset validator runs as an AWS Batch job. It makes its own integrity checks, then runs three validators on the file: CAP, HCA schema and HCA cell annotation. The standalone CELLxGENE validator is not run. This document covers what the Batch service adds; what the CELLxGENE and HCA schema validators check is in the [`hca-schema-validator` README](../packages/hca-schema-validator/README.md#what-this-validator-checks).

Source files:
- Orchestrator: `services/dataset-validator/src/dataset_validator/main.py`
- CAP wrapper: `services/dataset-validator/src/dataset_validator/cap_validator_script.py`
- CELLxGENE wrapper: `services/cellxgene-validator/src/cellxgene_validator/main.py`
- HCA wrapper: `services/hca-schema-validator/src/hca_schema_validator_service/main.py`
- HCA cell annotation validator: `packages/hca-schema-validator/src/hca_schema_validator/cell_annotation_validator.py`
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

## 3. CELLxGENE validator (not run)

`main.py` does not run the standalone CELLxGENE validator. The Tracker UI hides the CELLxGENE tab, so its results were never seen and crowded out visible warnings under SNS truncation. The job sends an empty, passing stub under `tool_reports.cellxgene` so the SNS payload schema stays satisfied (#382). The core CELLxGENE checks still run inside the HCA schema validator.

---

## 4. HCA schema validator (`HCAValidator`)

Runs `HCAValidator` from the `hca-schema-validator` package. Every check it makes — the core CELLxGENE checks, the HCA overrides and the HCA extensions — is listed, with the reason for each, in the [package README](../packages/hca-schema-validator/README.md#what-this-validator-checks). This document does not repeat them.

---

## 5. HCA cell annotation validator (`HCACellAnnotationValidator`)

Runs `HCACellAnnotationValidator` from the same package, in the HCA schema validator's environment. Structural checks on the CAP annotations under `uns['cap_metadata']`, all errors:

- At least one CAP annotation set is present (`uns['cap_metadata']['cellannotation_metadata']` is a non-empty dict).
- `uns['cap_metadata']['cellannotation_schema_version']` is present and well-formed.
- `cellannotation_metadata` is a dict, and each annotation set's value is a dict.
- Each annotation set has the per-set `obs` columns CAP requires.
- The old top-level layout (`uns['cellannotation_metadata']`, `uns['cellannotation_schema_version']`) is rejected (#452).

The per-set required fields, marker-gene coverage and Cell Ontology term validity are left to CAP's own validator.

---

## Cross-reference

| Stage | Source | Fail mode |
|---|---|---|
| Env & S3 integrity | `main.py` | Hard fail, no tool reports |
| Metadata summary | `main.py:read_metadata` | Exception → failure message |
| CAP | `cap_validator_script.py` | `tool_reports.cap.errors` |
| CELLxGENE | Not run; empty passing stub | `tool_reports.cellxgene` |
| HCA | `services/hca-schema-validator` → `HCAValidator` | `tool_reports.hcaSchema` |
| HCA cell annotation | `services/hca-schema-validator` → `HCACellAnnotationValidator` | `tool_reports.hcaCellAnnotation` |
