# PRD: Multi-User Upload Versioning and Concurrency

**Status:** Draft
**Date:** 2026-05-05

> Note: this concerns the upload/versioning workflow used by the hca-atlas-tracker
> upload tool against the versioned S3 bucket holding integrated-object h5ad files.
> Filed in this repo because the surrounding tooling (hca-anndata-tools edit
> conventions, h5ad editing PRD) lives here.

## Problem

Multiple wranglers upload h5ad datasets to a versioned S3 bucket. Today:

- The S3 **key** identifies the dataset (e.g. `myfile.h5ad`).
- Re-uploading with the same key creates a new S3 version.
- On download the UI synthesizes a display name from the key plus the version count: `myfile-r1-wip-3.h5ad` (`r1` = release, `wip-3` = WIP version count).
- The hca-anndata-tools edit pipeline appends `-edit-YYYY-MM-DD-HH-MM-SS` when it writes a derived file (see [PRD: H5AD File Editing](prd-h5ad-editing.md)).

Two problems surface from this design:

1. **Stale display names after edit.** A user downloads `myfile-r1-wip-3.h5ad`, edits it locally; the filename still says `wip-3` but the content is post-wip-3. Asking users to rename before upload is unreliable.
2. **Lost-update / clobber risk.** If two users both download `wip-3` and both upload edits, the second upload silently writes a new S3 version on top of the first. Nothing is *lost* (the bucket is versioned) but the latest pointer reflects only the second uploader's work, and the first uploader may not realise their changes were buried.

We want a design that keeps multiple uploaders honest without imposing a heavy checkout/lock workflow.

## Non-Goals

- Three-way merge of h5ad content. h5ad files are effectively impossible to merge programmatically; conflict resolution will always be "one wins, the other rebases."
- Replacing the wip / edit naming conventions. Both stay; this PRD is about how the server treats them.

## Goals

1. **No silent clobbers.** A second uploader who didn't see the first uploader's changes must get a loud error, not a silent overwrite.
2. **Filenames are not load-bearing.** The server must work correctly regardless of how the user has renamed the file on disk.
3. **Provenance survives renames.** Knowing which prior version a given upload was derived from must not depend on the filename.
4. **No human checkout step.** Curators should be able to work in parallel; collisions are rare enough that pessimistic locking is overkill.

## Design

### 1. Filenames are cosmetic, not contracts

The S3 key is always the **bare** canonical name (`myfile.h5ad`). The `-rX-wipY` decoration is a UI concern, not a storage concern. The hca-anndata-tools `-edit-…` decoration is a local-bookkeeping concern, not a storage concern.

Two filename roles, both legitimate, both allowed to coexist on disk:

| Decoration | Role | Set by | Meaning |
|---|---|---|---|
| `-r1-wip-3` | Provenance hint, human-readable | Download UI | "You downloaded version 3 of release 1." |
| `-edit-2026-04-29-14-22-03` | Local bookkeeping | hca-anndata-tools on save | "This is my Nth local save of the working copy." |

A file mid-edit can legitimately carry both: `myfile-r1-wip-3-edit-2026-04-29-14-22-03.h5ad`. Neither piece is wrong; they answer different questions. Once the parent version-id is known via structured metadata (next section), neither decoration is required for correctness.

### 2. Carry parent version-id as structured metadata, not in the filename

At download time the upload tool writes a sidecar metadata file (or uses an OS extended attribute) capturing:

- `s3_key` — the canonical bucket key.
- `parent_version_id` — the S3 version-id the user is editing.
- `downloaded_at`, `downloaded_by`.

At upload time the upload tool sends:

- `key` — derived from the sidecar, **not** parsed from the on-disk filename.
- `parent_version_id` — from the sidecar.
- `original_filename` — whatever the user has on disk, for the audit log.
- The h5ad payload.

This decoupling means the user can rename to anything (`alice-final-FINAL.h5ad`) without breaking the upload, and the server doesn't need filename-parsing logic.

### 3. Optimistic concurrency on upload

The server enforces "is `parent_version_id` still the head of `s3_key`?" before accepting the new version.

Two implementation paths:

- **Native:** S3 `PutObject` with `If-Match: <etag-of-parent>`. Available in S3 since late 2024; one round trip; no extra state.
- **External:** A small metadata table tracks `(key → current_version_id)`; the upload handler does a conditional update there before calling `PutObject`. More moving parts, but lets us record additional context (uploader, timestamp, original filename) atomically.

On match → accept; S3 assigns a new version-id; UI displays as `wip-N+1`.

On mismatch → 409 Conflict with a message:

> Bob uploaded `myfile.h5ad` (now wip-4) two hours ago. Your file was edited from wip-3 and would overwrite his changes. Please re-download wip-4, reconcile your edits, and retry.

### 4. Audit log

Every accepted upload records:

| Field | Purpose |
|---|---|
| `s3_key` | bare canonical key |
| `version_id` | new S3 version-id this upload produced |
| `parent_version_id` | what the uploader was editing |
| `uploader` | who |
| `uploaded_at` | when |
| `original_filename` | what the user had on disk (audit only) |

This is what makes "who clobbered what?" answerable after the fact.

### 5. Server-side normalisation as defense in depth

Even though the upload tool sends the canonical key explicitly, the server should still:

- Strip any `-rX-wipY` and `-edit-…` decorations from the key it receives, in case a future client (web upload, curl, Postman) sends them.
- Reject keys with directory components, suspicious characters, or that don't end in `.h5ad`.

The client-side rename is the primary path; server normalisation is the safety net.

## Considered Alternatives

### Pessimistic locking ("checkout / checkin")

Download acquires an exclusive lock; upload releases it; concurrent downloaders see "Alice has this checked out since 14:02" until then. Common in DAM/CMS systems (AEM, SharePoint, Perforce).

Rejected because:

- Needs lock TTL + admin force-release.
- Serialises work unnecessarily — most parallel sessions wouldn't actually collide.
- Hostile to async collaboration when curators are in different timezones.
- Lock leakage is a constant operational burden.

Reconsider only if collisions become frequent in practice.

### Branches per uploader

Each uploader's edits live on a logical branch (`<dataset>/<uploader>/wip-N`); a curator promotes one branch to canonical.

Rejected as overbuilt for the current workload. May make sense later if exploratory parallel edits become a routine pattern.

### Asking users to rename before upload

Rejected. Filename hygiene cannot be a correctness mechanism — humans will forget.

## Implementation Outline

1. **Upload tool (client):**
   - On download, write a sidecar `<file>.meta.json` capturing `s3_key`, `parent_version_id`, `downloaded_at`, `downloaded_by`.
   - On upload, read the sidecar; send `key`, `parent_version_id`, `original_filename`, and the h5ad payload.
   - If no sidecar exists (file produced outside the tool), prompt the user: "Upload as a new baseline version?" — explicit acknowledgement, not silent.

2. **Server / upload handler:**
   - Validate `key` against bare-name regex; strip stray decorations.
   - Conditional PutObject (`If-Match: <parent etag>`) or conditional metadata-table update.
   - Write audit-log row on success.
   - Return 409 with a structured error body on conflict.

3. **Database:**
   - New table `dataset_upload_audit` with columns above.
   - Optional table `dataset_head` with `(s3_key → current_version_id)` if we go the external-metadata route for the conditional check.

4. **UI:**
   - On 409, show the conflict message with a one-click "re-download latest" action.
   - In dataset detail view, surface the audit log so wranglers can see who has been editing.

## Open Questions

- Should the sidecar be a separate `.meta.json` file or an h5ad-internal field (e.g. under `uns['_provenance']`)? Sidecar survives `cp`/`mv` cleanly; in-h5ad survives renames but requires writers to preserve it.
- Should "rebase onto someone else's edits" be a first-class UI flow, or do we just tell the user to download-merge-reupload manually?
- Do we want a soft warning (not 409) when the parent version-id is *N* hours old, even if it's still head — i.e. nudge the uploader to re-pull a recent baseline?
