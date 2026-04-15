# Changelog

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
