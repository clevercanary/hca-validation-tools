# Changelog

## [0.11.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-schema-validator-v0.10.2...hca-schema-validator-v0.11.0) (2026-04-22)


### Features

* add HCALabeler for post-curate label generation ([#353](https://github.com/clevercanary/hca-validation-tools/issues/353)) ([06c7399](https://github.com/clevercanary/hca-validation-tools/commit/06c7399d76495ab6bda05131e37317e82328ebdc))
* add label_h5ad MCP tool and wire into /curate-h5ad ([#355](https://github.com/clevercanary/hca-validation-tools/issues/355)) ([2fdc6e6](https://github.com/clevercanary/hca-validation-tools/commit/2fdc6e693e9c02b2b7c14455a241c64e45e4e0f0))
* HCA Cell Annotation validator — Phase 1 (structural checks) ([#366](https://github.com/clevercanary/hca-validation-tools/issues/366)) ([872107f](https://github.com/clevercanary/hca-validation-tools/commit/872107fb98fbe365ebab318ae0ca0bf358902bd5))


### Miscellaneous Chores

* add pyright type checker ([#316](https://github.com/clevercanary/hca-validation-tools/issues/316)) ([7814796](https://github.com/clevercanary/hca-validation-tools/commit/78147967a207ffa067fdb79319099c17b5a8ac81))
* add ruff linter, fix unused imports and import sorting ([#312](https://github.com/clevercanary/hca-validation-tools/issues/312)) ([da1fc17](https://github.com/clevercanary/hca-validation-tools/commit/da1fc17f4e760bf904414e4443c9b68acbb43172))

## [0.10.2](https://github.com/clevercanary/hca-validation-tools/compare/hca-schema-validator-v0.10.1...hca-schema-validator-v0.10.2) (2026-04-15)


### Bug Fixes

* change library_id back to required in HCA schema ([#298](https://github.com/clevercanary/hca-validation-tools/issues/298)) ([8df7bbe](https://github.com/clevercanary/hca-validation-tools/commit/8df7bbe4620a7b403646d6b73971e418ac9bb62f))
* make cell_type_ontology_term_id optional ([#300](https://github.com/clevercanary/hca-validation-tools/issues/300)) ([80c8be7](https://github.com/clevercanary/hca-validation-tools/commit/80c8be7ad8eba38899959dd3cf404cb16bed19d7))
* reorder feature ID warnings in Batch service ([#296](https://github.com/clevercanary/hca-validation-tools/issues/296)) ([70edc51](https://github.com/clevercanary/hca-validation-tools/commit/70edc513737184e1c4517cd9e439a7981e73ebb8))

## [0.10.1](https://github.com/clevercanary/hca-validation-tools/compare/hca-schema-validator-v0.10.0...hca-schema-validator-v0.10.1) (2026-04-10)


### Bug Fixes

* reorder warnings so feature ID warnings come last ([#278](https://github.com/clevercanary/hca-validation-tools/issues/278)) ([71d21b1](https://github.com/clevercanary/hca-validation-tools/commit/71d21b1ed3dcc6947c8ede3882c56d8bc0382bef))

## [0.10.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-schema-validator-v0.9.2...hca-schema-validator-v0.10.0) (2026-04-10)


### Features

* add requirement_level and blocklist for library fields ([#269](https://github.com/clevercanary/hca-validation-tools/issues/269)) ([28b329d](https://github.com/clevercanary/hca-validation-tools/commit/28b329d198bc74536d66d673cee7eb2f61590e30))


### Bug Fixes

* improve gene ID warning to include GENCODE version ([#272](https://github.com/clevercanary/hca-validation-tools/issues/272)) ([a31c9f2](https://github.com/clevercanary/hca-validation-tools/commit/a31c9f257effd87904a1a2013ab9fab561a9fe59))

## [0.9.2](https://github.com/clevercanary/hca-validation-tools/compare/hca-schema-validator-v0.9.1...hca-schema-validator-v0.9.2) (2026-04-08)


### Bug Fixes

* correct release-please changelog-path to avoid double-nesting ([#250](https://github.com/clevercanary/hca-validation-tools/issues/250)) ([0ec58b7](https://github.com/clevercanary/hca-validation-tools/commit/0ec58b77ca1651cf350d346d04b1058b4a40971b))
* default ignore_labels=True in HCAValidator ([#268](https://github.com/clevercanary/hca-validation-tools/issues/268)) ([4cbcda1](https://github.com/clevercanary/hca-validation-tools/commit/4cbcda12e4814f31c67d1cfa71a478a5eaea7f0b))

## [0.9.1](https://github.com/clevercanary/hca-validation-tools/compare/hca-schema-validator-v0.9.0...hca-schema-validator-v0.9.1) (2026-03-31)


### Bug Fixes

* retry raw validation when skipped due to unrelated errors ([#244](https://github.com/clevercanary/hca-validation-tools/issues/244)) ([bc8d1bf](https://github.com/clevercanary/hca-validation-tools/commit/bc8d1bf9ab2e50f0e674cf709cc64928362870e1))

## [0.9.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-schema-validator-v0.8.1...hca-schema-validator-v0.9.0) (2026-03-18)


### Features

* allow multiple semicolon-separated cell_enrichment values ([#216](https://github.com/clevercanary/hca-validation-tools/issues/216)) ([f00ed75](https://github.com/clevercanary/hca-validation-tools/commit/f00ed7543684273cb62da19b69360c0157b96316))

## [0.8.1](https://github.com/clevercanary/hca-validation-tools/compare/hca-schema-validator-v0.8.0...hca-schema-validator-v0.8.1) (2026-03-18)


### Bug Fixes

* initialize error state in HCAValidator.__init__ ([#211](https://github.com/clevercanary/hca-validation-tools/issues/211)) ([28c23dc](https://github.com/clevercanary/hca-validation-tools/commit/28c23dc619a300597be952448daf3953597dbfb6))

## [0.8.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-schema-validator-v0.7.0...hca-schema-validator-v0.8.0) (2026-03-17)


### Features

* allow empty string for manner_of_death regardless of development stage ([#206](https://github.com/clevercanary/hca-validation-tools/issues/206)) ([abc4fc9](https://github.com/clevercanary/hca-validation-tools/commit/abc4fc962fa76f3f6956c4a240633d8483e59ff1))

## [0.7.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-schema-validator-v0.6.0...hca-schema-validator-v0.7.0) (2026-03-03)


### Features

* allow empty manner_of_death for prenatal development stages ([#194](https://github.com/clevercanary/hca-validation-tools/issues/194)) ([9b885a1](https://github.com/clevercanary/hca-validation-tools/commit/9b885a1bb6afa866af7c1cfb6098e5d54b10f164))

## [0.6.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-schema-validator-v0.5.0...hca-schema-validator-v0.6.0) (2026-02-28)


### Features

* bump CL ontology to v2025-12-17 for salivary gland cell types ([#191](https://github.com/clevercanary/hca-validation-tools/issues/191)) ([75bd55c](https://github.com/clevercanary/hca-validation-tools/commit/75bd55c63093af0eecf9a9ebf0c053ad64b6e582))


### Bug Fixes

* batch validator failing on large files ([#188](https://github.com/clevercanary/hca-validation-tools/issues/188)) ([94b19a7](https://github.com/clevercanary/hca-validation-tools/commit/94b19a7ddd9da9f8862825e8d51390042424839f))

## [0.5.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-schema-validator-v0.4.0...hca-schema-validator-v0.5.0) (2026-01-28)


### Features

* human-readable pattern validation errors ([#180](https://github.com/clevercanary/hca-validation-tools/issues/180)) ([861ef0d](https://github.com/clevercanary/hca-validation-tools/commit/861ef0d65fbe486c4b48a0e05ff5b65938a4479b))

## [0.4.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-schema-validator-v0.3.0...hca-schema-validator-v0.4.0) (2026-01-28)


### Features

* add HCA tier-1 validation fields ([#177](https://github.com/clevercanary/hca-validation-tools/issues/177)) ([2af5e2e](https://github.com/clevercanary/hca-validation-tools/commit/2af5e2e86ecb674960144d3f868ba0013111f19e))

## [0.3.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-schema-validator-v0.2.0...hca-schema-validator-v0.3.0) (2025-11-26)


### Features

* make ensembl id mismatches warnings instead of errors ([#167](https://github.com/clevercanary/hca-validation-tools/issues/167)) ([#168](https://github.com/clevercanary/hca-validation-tools/issues/168)) ([a47561e](https://github.com/clevercanary/hca-validation-tools/commit/a47561e07db0401746f811eefe1b76849c2c3c3e))

## [0.2.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-schema-validator-v0.1.0...hca-schema-validator-v0.2.0) (2025-10-28)


### Features

* added hca-schema-validator package ([#152](https://github.com/clevercanary/hca-validation-tools/issues/152)) ([#153](https://github.com/clevercanary/hca-validation-tools/issues/153)) ([3dd9f6b](https://github.com/clevercanary/hca-validation-tools/commit/3dd9f6b7639f80e2968351cc4cc4b9e541c4d1ec))
