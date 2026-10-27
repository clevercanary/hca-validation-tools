# Contract: the LinkML schema version, and what each bump means

**Status:** Proposed with #537 — for review by the schema owners
**Date:** 2026-10-27
**Prompted by:** #537 (version the LinkML schema meaningfully). Recording the version on files and in validator
reports is #802.

A version is only useful if a consumer can tell from it whether a file that passed before can fail now.

---

## 1. What is versioned

1.1 **One version, in `shared/src/hca_validation/schema/core.yaml`.** No other schema file declares a `version:`.
    `core.yaml` imports every other schema file, so any change anywhere is a change to it.

1.2 The generated Pydantic module (`generated/core.py`) and the bundled copy in `hca-anndata-tools`
    (`hca_anndata_tools/schema/core.py`) carry the same value. `test_schema.py` fails if any of the three differ.

1.3 The bionetwork schemas have no version of their own. Nothing loads one on its own, and all of them feed the one
    published data dictionary. Revisit if Tier 2 (#790) makes networks change much faster than core.

1.4 `hca-schema-validator`'s `__schema_version__` ("HCA anndata schema version 1.0.0") is a different number for a
    different rule set: that validator does not load the LinkML schema. How the two relate is #802.

## 2. How the version moves

2.1 **Never edit the version by hand.** release-please owns it: the `hca-schema` component in
    `release-please-config.json` (path `shared/src/hca_validation/schema`) bumps `core.yaml` and both generated
    files, writes `CHANGELOG.md` beside `core.yaml`, and tags `hca-schema-vX.Y.Z`. Nothing is published to PyPI.

2.2 **The bump comes from the conventional-commit type.** The repo squash-merges, so it is the **pull request
    title** that decides. A schema change's title type is chosen against sections 3 to 5, not by habit.

2.3 **At 0.x the repo's release policy applies** (CLAUDE.md, Release Policy):

| Commit type | 0.x bump | Use for |
|---|---|---|
| `feat!:` or a `BREAKING CHANGE:` footer | minor (`0.2.3` → `0.3.0`) | section 3 |
| `feat:` | patch | section 4 |
| `fix:` | patch | section 5 |
| `chore:`, `refactor:`, `test:` | none | changes that alter no schema meaning, e.g. a regeneration-only diff |

2.4 Cutting 1.0.0 is a deliberate act, done with a `Release-As: 1.0.0` footer, as for the packages.

2.5 Only commits that touch `shared/src/hca_validation/schema/` count. A change to validator code alone (entry-sheet
    validation, `hca-schema-validator`) is not a schema change and does not appear in this changelog.

## 3. Breaking: a file or entry sheet that passed can now fail

3.1 The test is the consumer's: **can anything that validated before fail now?** If yes, it is breaking.

3.2 Breaking changes include:
- removing or renaming a slot (a rename is a removal plus an addition)
- adding a **required** slot, or making an optional slot required
- removing a permissible value from an enum, or otherwise narrowing a slot's allowed values
- changing a slot's `range` or `annDataLocation`
- a stricter `pattern`
- changing identifiers or foreign keys, which drive the ID-uniqueness and referential checks

3.3 **A change that affects only some networks is still breaking** if it breaks those networks' files, for example
    a new required slot on `GutSample`. There is one version, so it bumps that version; the commit and changelog
    name the network.

## 4. Additions: nothing that passed can fail, but consumers see something new

4.1 Additions include:
- adding an optional slot, an enum value, or a class
- loosening a `pattern` or widening a `range`
- annotations that change only the published data dictionary or coverage reporting, such as `bioNetwork`, `tier`,
  or `annDataLocation` on a slot that had none

4.2 Dictionary-only changes are additions, not text fixes: the portal and the tracker consume the dictionary, and
    a consumer pinned to a version must be able to see that it changed.

## 5. Text: what is said about a slot, not what it allows

5.1 Descriptions, comments, notes, examples and titles. Commit these as `fix:` so they reach a release: the
    published data dictionary shows them.

## 6. The changelog

6.1 Each entry comes from its pull request title, so the title names what changed in the schema's terms: the slots,
    enums or classes involved, and the network when only some are affected.

6.2 `0.1.0` is a baseline, not one fixed schema: the schema changed under it from August 2025 without a bump.
    `CHANGELOG.md` records this.
