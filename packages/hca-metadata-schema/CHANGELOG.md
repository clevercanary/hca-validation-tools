# Changelog

## [0.3.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-metadata-schema-v0.2.0...hca-metadata-schema-v0.3.0) (2026-11-11)


### ⚠ BREAKING CHANGES

* **hca-metadata-schema:** make Dataset title required for h5ad files, but not entry sheets ([#836](https://github.com/clevercanary/hca-validation-tools/issues/836)) (#852)

### Features

* **data-dictionary:** emit bioNetworks and fold bionetwork subclass fields into their base class ([#759](https://github.com/clevercanary/hca-validation-tools/issues/759)) ([#800](https://github.com/clevercanary/hca-validation-tools/issues/800)) ([a9d0c3c](https://github.com/clevercanary/hca-validation-tools/commit/a9d0c3cd87cd37b6ba98157603d03144190a851e))
* **hca-metadata-schema:** give dissociation_protocol (AdiposeSample, GutSample) and radial_tissue_term (GutSample) annDataLocation obs and tier Tier 1 ([#824](https://github.com/clevercanary/hca-validation-tools/issues/824)) ([#825](https://github.com/clevercanary/hca-validation-tools/issues/825)) ([1f95db6](https://github.com/clevercanary/hca-validation-tools/commit/1f95db635a1ad2858459e66b612281c186c34137))
* **hca-metadata-schema:** give the eight unlocated slots annDataLocation obs ([#604](https://github.com/clevercanary/hca-validation-tools/issues/604)) ([#819](https://github.com/clevercanary/hca-validation-tools/issues/819)) ([3b353ba](https://github.com/clevercanary/hca-validation-tools/commit/3b353ba4a95b8b2d3d50fc77b726f36aba482a20))
* **hca-metadata-schema:** make Dataset title required for h5ad files, but not entry sheets ([#836](https://github.com/clevercanary/hca-validation-tools/issues/836)) ([#852](https://github.com/clevercanary/hca-validation-tools/issues/852)) ([d6498e4](https://github.com/clevercanary/hca-validation-tools/commit/d6498e48160b38f5e1cd7fe6d8869b8c468cb5b5))
* **hca-metadata-schema:** make library_preparation_batch and library_sequencing_run strongly recommended, and emit "strongly recommended" in the data dictionary ([#761](https://github.com/clevercanary/hca-validation-tools/issues/761)) ([#842](https://github.com/clevercanary/hca-validation-tools/issues/842)) ([626d8f2](https://github.com/clevercanary/hca-validation-tools/commit/626d8f20de44644c2da4cfb4d1411c3d1300cbd3))


### Bug Fixes

* **hca-metadata-schema:** back-port the portal's field text into the schema ([#762](https://github.com/clevercanary/hca-validation-tools/issues/762)) ([#858](https://github.com/clevercanary/hca-validation-tools/issues/858)) ([f0f9947](https://github.com/clevercanary/hca-validation-tools/commit/f0f99473819533a6fd34319b8d7db996e6711d22))


### Miscellaneous Chores

* **schema:** fix the 27 LinkML lint errors and run validate and lint in CI ([#546](https://github.com/clevercanary/hca-validation-tools/issues/546)) ([#816](https://github.com/clevercanary/hca-validation-tools/issues/816)) ([8d122cf](https://github.com/clevercanary/hca-validation-tools/commit/8d122cf568119a4f958178d3b68754d59f353a4d))


### Continuous Integration

* measure test coverage in CI with a floor per project, and test generate_dictionary ([#548](https://github.com/clevercanary/hca-validation-tools/issues/548)) ([#817](https://github.com/clevercanary/hca-validation-tools/issues/817)) ([bf8d382](https://github.com/clevercanary/hca-validation-tools/commit/bf8d3829ee85d70b46d3ca17ca92d7c73b42e645))

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
