# Contract: the LinkML schema version, and what each bump means

**Status:** Proposed with #537 — for review by the schema owners
**Date:** 2026-10-27
**Prompted by:** #537 (version the LinkML schema meaningfully). Recording the version on files and in validator
reports is #802.

A version is only useful if a consumer can tell from it whether a file that passed before can fail now.

---

## 1. What is versioned

1.1 **One version, in `packages/hca-metadata-schema/src/hca_metadata_schema/core.yaml`.** No other schema file
    declares a `version:`. `core.yaml` imports every other schema file, so any change anywhere is a change to it.

1.2 The schema is the `hca-metadata-schema` package on PyPI (#350), and the package version is the schema version.
    The generated Pydantic module (`generated/core.py`), `__init__.py`'s `__version__` and `pyproject.toml` carry
    the same value. The package's `tests/test_package.py` fails if any of them differ.

1.3 **The schema is versioned on its own.** A schema release touches only the `hca-metadata-schema` package and
    releases no other. Each consumer adopts a new schema version in its own way: `shared` and `hca-anndata-tools`
    depend on the package with a bound capped at the next minor, so they take a patch release as soon as it is
    published and a minor (breaking) release only when their bound is widened; the data portal by bumping the tag
    it syncs from (DataBiosphere/data-portal#3263); the tracker by refreshing its dictionary. Until a consumer adopts
    a release, it reports the version it last adopted.

1.4 The bionetwork schemas have no version of their own. Nothing loads one on its own, and all of them feed the one
    published data dictionary. Revisit if Tier 2 (#790) makes networks change much faster than core.

1.5 `hca-schema-validator`'s `__schema_version__` ("HCA anndata schema version 1.0.0") is a different number for a
    different rule set: that validator does not load the LinkML schema. How the two relate is #802.

## 2. How the version moves

2.1 **Never edit the version by hand.** release-please owns it: the `hca-metadata-schema` component in
    `release-please-config.json` (path `packages/hca-metadata-schema`) bumps `pyproject.toml`, `__init__.py`,
    `core.yaml` and `generated/core.py`, writes the package's `CHANGELOG.md`, tags `hca-metadata-schema-vX.Y.Z`, and
    the release workflow publishes the package to PyPI. Releases up to 0.2.0 were tagged `hca-schema-vX.Y.Z`, before
    the schema became a package; 0.2.0 is the first version on PyPI.

2.2 **The bump comes from the conventional-commit type in the pull request title.** The repo squash-merges with a
    blank commit body, so the title is all release-please sees: a breaking change is marked with `!` in the title
    (`feat(schema)!: …`). A `BREAKING CHANGE:` footer in a commit or the PR body never reaches `main`.

2.3 **The type maps to a section below; the bump it gives at 0.x is CLAUDE.md's Release Policy**, as for the packages,
    including cutting 1.0.0 deliberately with a `Release-As: 1.0.0` footer typed into the squash message at merge:

| Commit type | Use for |
|---|---|
| `feat!:` | section 3 |
| `feat:` | section 4 |
| `fix:` | section 5 |
| `chore:`, `refactor:`, `test:` | changes that alter no schema meaning, e.g. a regeneration-only diff |

2.3.1 Every commit type above releases at least a patch: `release-please-config.json` makes all of them visible
      changelog sections. A schema-meaning-free change therefore still moves the version, and says so in the changelog.

2.4 Only commits that touch `packages/hca-metadata-schema/` count. A change to validator code alone (entry-sheet
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

4.2 Dictionary-only changes are additions, not text fixes: the portal and the tracker consume the dictionary, and a
    consumer pinned to a release tag (DataBiosphere/data-portal#3263) must see from the changelog that it changed.
    The dictionary itself does not yet state its version; recording it is #802.

## 5. Text: what is said about a slot, not what it allows

5.1 Descriptions, comments, notes, examples and titles. Commit these as `fix:` so they reach a release: the
    published data dictionary shows them.

## 6. The changelog

6.1 Each entry comes from its pull request title, so the title names what changed in the schema's terms: the slots,
    enums or classes involved, and the network when only some are affected.

6.2 `0.1.0` is a baseline, not one fixed schema; `CHANGELOG.md` explains why.
