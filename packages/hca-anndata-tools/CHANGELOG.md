# Changelog

## [0.4.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-tools-v0.3.1...hca-anndata-tools-v0.4.0) (2026-04-22)


### Features

* add check_schema_type tool to identify CellxGENE vs HCA layout ([#338](https://github.com/clevercanary/hca-validation-tools/issues/338)) ([5d3ae7b](https://github.com/clevercanary/hca-validation-tools/commit/5d3ae7b473fad13704a9fd32959b6ab7c62536d9))
* add check_x_normalization tool to classify X as raw-counts vs normalized ([#337](https://github.com/clevercanary/hca-validation-tools/issues/337)) ([940af43](https://github.com/clevercanary/hca-validation-tools/commit/940af43e96147fd534d583164c9bbbf4470ea34f))
* add compress_h5ad tool ([#319](https://github.com/clevercanary/hca-validation-tools/issues/319)) ([df0c223](https://github.com/clevercanary/hca-validation-tools/commit/df0c2233f039f2cd8ad033eb62b2d9c4497544fb))
* add normalize_raw tool for files with raw counts in X ([#321](https://github.com/clevercanary/hca-validation-tools/issues/321)) ([0d70dd9](https://github.com/clevercanary/hca-validation-tools/commit/0d70dd9b5044b17c238e78bf396bbb3659085bdd))
* add replace_placeholder_values tool ([#305](https://github.com/clevercanary/hca-validation-tools/issues/305)) ([b326d1b](https://github.com/clevercanary/hca-validation-tools/commit/b326d1be0b800b4c439f79304a92190392117669))
* add view_edit_log tool to inspect h5ad edit history ([#330](https://github.com/clevercanary/hca-validation-tools/issues/330)) ([3bd1580](https://github.com/clevercanary/hca-validation-tools/commit/3bd15801fb207d6415001cf07eb56be77f73e864))
* allow partial obs overlap in copy_cap_annotations ([#345](https://github.com/clevercanary/hca-validation-tools/issues/345)) ([f6a863c](https://github.com/clevercanary/hca-validation-tools/commit/f6a863c2ea79f18a78c4ce0cf78421cc45100f50))
* move ambient_count_correction and doublet_detection from uns to obs ([#349](https://github.com/clevercanary/hca-validation-tools/issues/349)) ([90b2b0b](https://github.com/clevercanary/hca-validation-tools/commit/90b2b0bea36500f7bb9a54961fd3dfc3f74c9cf9))


### Bug Fixes

* auto-resolve latest edit snapshot in all read-only tools ([#340](https://github.com/clevercanary/hca-validation-tools/issues/340)) ([9d441ce](https://github.com/clevercanary/hca-validation-tools/commit/9d441ce9d767479feda34e94845f0520476c7215))
* drop scanpy's empty uns['log1p'] stamp in normalize_raw ([#329](https://github.com/clevercanary/hca-validation-tools/issues/329)) ([c3a1d90](https://github.com/clevercanary/hca-validation-tools/commit/c3a1d90335dcfd7ff82df707f1f89821eddab511))
* filter description from uns field registry (workaround for [#343](https://github.com/clevercanary/hca-validation-tools/issues/343)) ([#347](https://github.com/clevercanary/hca-validation-tools/issues/347)) ([037731f](https://github.com/clevercanary/hca-validation-tools/commit/037731f68b36cc96b401b7405ca7c594b2e954ba))
* strip feature_is_filtered from raw.var in normalize_raw ([#328](https://github.com/clevercanary/hca-validation-tools/issues/328)) ([57dd4ba](https://github.com/clevercanary/hca-validation-tools/commit/57dd4bafa4a50221b6470a1bb2fabe7e64bb81bf))


### Miscellaneous Chores

* add pyright type checker ([#316](https://github.com/clevercanary/hca-validation-tools/issues/316)) ([7814796](https://github.com/clevercanary/hca-validation-tools/commit/78147967a207ffa067fdb79319099c17b5a8ac81))
* add ruff linter, fix unused imports and import sorting ([#312](https://github.com/clevercanary/hca-validation-tools/issues/312)) ([da1fc17](https://github.com/clevercanary/hca-validation-tools/commit/da1fc17f4e760bf904414e4443c9b68acbb43172))
* fix E501 (line-too-long) violations and enable rule ([#317](https://github.com/clevercanary/hca-validation-tools/issues/317)) ([77447d3](https://github.com/clevercanary/hca-validation-tools/commit/77447d31d5898fdfd9e0d53cbad5a39bc9a34919))


### Code Refactoring

* extract reusable primitives into _io.py ([#310](https://github.com/clevercanary/hca-validation-tools/issues/310)) ([d0a5b29](https://github.com/clevercanary/hca-validation-tools/commit/d0a5b29e24a0f05233d7776773dce7495dc42c62))
* shared factory for edit-log entries ([#325](https://github.com/clevercanary/hca-validation-tools/issues/325)) ([f91c78e](https://github.com/clevercanary/hca-validation-tools/commit/f91c78e93a33c952df2879f9273c542c1e5da6f4))

## [0.3.1](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-tools-v0.3.0...hca-anndata-tools-v0.3.1) (2026-04-15)


### Bug Fixes

* remove cell_type enrichment columns from copy_cap ([#291](https://github.com/clevercanary/hca-validation-tools/issues/291)) ([859f9a9](https://github.com/clevercanary/hca-validation-tools/commit/859f9a95697d421f34e63c6f9c5602f9c045ef42))


### Performance Improvements

* optimize convert_cellxgene_to_hca with copy-then-patch ([#287](https://github.com/clevercanary/hca-validation-tools/issues/287)) ([7b5378c](https://github.com/clevercanary/hca-validation-tools/commit/7b5378cfb7645b43d522eeb2fa58c032bac7c198))
* optimize copy_cap_annotations with copy-then-patch ([#286](https://github.com/clevercanary/hca-validation-tools/issues/286)) ([2cef50c](https://github.com/clevercanary/hca-validation-tools/commit/2cef50ce8a2b50833706756ce061f7d1d587853c))
* optimize validate_marker_genes with h5py direct reads ([#282](https://github.com/clevercanary/hca-validation-tools/issues/282)) ([7f998b9](https://github.com/clevercanary/hca-validation-tools/commit/7f998b91ef096f44675bd9dc9e09d13a849dfae6))


### Code Refactoring

* consolidate provenance into uns['provenance'] container ([#292](https://github.com/clevercanary/hca-validation-tools/issues/292)) ([a43817d](https://github.com/clevercanary/hca-validation-tools/commit/a43817d9d4c236d6fb5b6e703b31787e4d8b9117))
* move hca_edit_log to provenance/edit_history ([#294](https://github.com/clevercanary/hca-validation-tools/issues/294)) ([7c4663a](https://github.com/clevercanary/hca-validation-tools/commit/7c4663a8eb0be895febf754e15ee3310334d90a6))

## [0.3.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-tools-v0.2.0...hca-anndata-tools-v0.3.0) (2026-04-08)


### Features

* add CAP marker gene validation against var ([#259](https://github.com/clevercanary/hca-validation-tools/issues/259)) ([fcebd87](https://github.com/clevercanary/hca-validation-tools/commit/fcebd8789639e6ce67a4f9b6986c9ba6c4984257))
* add copy_cap_annotations tool ([#261](https://github.com/clevercanary/hca-validation-tools/issues/261)) ([1a68cd0](https://github.com/clevercanary/hca-validation-tools/commit/1a68cd02db491bcc5634e7ad727d3cc8bb33cb28))


### Bug Fixes

* correct release-please changelog-path to avoid double-nesting ([#250](https://github.com/clevercanary/hca-validation-tools/issues/250)) ([0ec58b7](https://github.com/clevercanary/hca-validation-tools/commit/0ec58b77ca1651cf350d346d04b1058b4a40971b))
* use cellannotation_metadata for annotation set detection ([#262](https://github.com/clevercanary/hca-validation-tools/issues/262)) ([d09878c](https://github.com/clevercanary/hca-validation-tools/commit/d09878c18546733f047e5abccebabcecf3990008))

## [0.2.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-tools-v0.1.0...hca-anndata-tools-v0.2.0) (2026-03-31)


### Features

* add -edit- prefix to timestamped output filenames ([#246](https://github.com/clevercanary/hca-validation-tools/issues/246)) ([4a12082](https://github.com/clevercanary/hca-validation-tools/commit/4a120824304c9a530b8bc477cc73beb92448f23f))
* add convert_cellxgene_to_hca tool ([#242](https://github.com/clevercanary/hca-validation-tools/issues/242)) ([47ba3d8](https://github.com/clevercanary/hca-validation-tools/commit/47ba3d860b0eaab624f55fd06ce040707b1b1dcb))
* add set_uns and list_uns_fields with HCA schema validation ([#237](https://github.com/clevercanary/hca-validation-tools/issues/237)) ([920ce03](https://github.com/clevercanary/hca-validation-tools/commit/920ce034ec3374f293756397e2e0e8980c76d426))
* add write_h5ad with timestamped naming and edit log ([#234](https://github.com/clevercanary/hca-validation-tools/issues/234)) ([0296947](https://github.com/clevercanary/hca-validation-tools/commit/02969473a6df55060243478ad301019e39ba34c4))
* extract hca-anndata-tools library from MCP server ([#224](https://github.com/clevercanary/hca-validation-tools/issues/224)) ([0ae4ced](https://github.com/clevercanary/hca-validation-tools/commit/0ae4cedfce6c4acc9912f4cb5a7df13a2b6abcdb))
* overwrite previous timestamped version, auto-detect latest ([#239](https://github.com/clevercanary/hca-validation-tools/issues/239)) ([ea0de47](https://github.com/clevercanary/hca-validation-tools/commit/ea0de477c277c98539be8984fcc45f7a62236e5a))
