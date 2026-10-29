# Changelog

## [0.2.1](https://github.com/clevercanary/hca-validation-tools/compare/hca-metadata-schema-v0.2.0...hca-metadata-schema-v0.2.1) (2026-10-29)


### Build System

* publish the LinkML schema to PyPI as hca-metadata-schema ([#350](https://github.com/clevercanary/hca-validation-tools/issues/350)) ([#811](https://github.com/clevercanary/hca-validation-tools/issues/811)) ([0240690](https://github.com/clevercanary/hca-validation-tools/commit/02406900b4e649ba61c37af86de4fe42aa8f67d1))

## [0.2.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-schema-v0.1.0...hca-schema-v0.2.0) (2026-10-28)


### Features

* add 10th and 11th decade development stages ([#202](https://github.com/clevercanary/hca-validation-tools/issues/202)) ([775091e](https://github.com/clevercanary/hca-validation-tools/commit/775091ebff3033f526e5d434fd9da3f0cce5dc0c))
* add musculoskeletal dataset schema ([#172](https://github.com/clevercanary/hca-validation-tools/issues/172)) ([#173](https://github.com/clevercanary/hca-validation-tools/issues/173)) ([4ff848b](https://github.com/clevercanary/hca-validation-tools/commit/4ff848b1b63db0da66558c852544e6ff96809fa1))
* move ambient_count_correction and doublet_detection from uns to obs ([#349](https://github.com/clevercanary/hca-validation-tools/issues/349)) ([90b2b0b](https://github.com/clevercanary/hca-validation-tools/commit/90b2b0bea36500f7bb9a54961fd3dfc3f74c9cf9))
* **schema:** give the LinkML schema its own version, bumped by release-please ([#537](https://github.com/clevercanary/hca-validation-tools/issues/537)) ([#803](https://github.com/clevercanary/hca-validation-tools/issues/803)) ([d016fa3](https://github.com/clevercanary/hca-validation-tools/commit/d016fa3a4e14abe9d99fadfe2d3c8164f7d85b96))


### Bug Fixes

* **schema:** make three obs columns visible to annDataLocation discovery ([#545](https://github.com/clevercanary/hca-validation-tools/issues/545)) ([2f4679b](https://github.com/clevercanary/hca-validation-tools/commit/2f4679b87424e3c2c6ea0c5f408106c466843b36))


### Code Refactoring

* update file structure to support multiple independent services ([#124](https://github.com/clevercanary/hca-validation-tools/issues/124)) ([ef1782a](https://github.com/clevercanary/hca-validation-tools/commit/ef1782a247af1fe9f562a12256b8ebc8e3ff657f))

## 0.1.0 (unversioned baseline)

`0.1.0` does not name one fixed schema. The schema was first given this version in
August 2025 (#124) and changed many times afterwards without a bump, including the
musculoskeletal bionetwork schema (December 2025) and the `Cell` class (#538). A file
or report that says `0.1.0` was checked against some schema from that period, but which
one cannot be told from the version alone.

From 0.2.0 on, `core.yaml`'s `version:` is bumped by release-please according to
`docs/schema-version-contract.md`, and every change is listed here (#537). The 0.2.0 entry
also lists the earlier, unversioned changes, since no release marked where they ended.
