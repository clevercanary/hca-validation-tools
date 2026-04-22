# Changelog

## [0.4.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-mcp-v0.3.0...hca-anndata-mcp-v0.4.0) (2026-04-22)


### Features

* add check_schema_type tool to identify CellxGENE vs HCA layout ([#338](https://github.com/clevercanary/hca-validation-tools/issues/338)) ([5d3ae7b](https://github.com/clevercanary/hca-validation-tools/commit/5d3ae7b473fad13704a9fd32959b6ab7c62536d9))
* add check_x_normalization tool to classify X as raw-counts vs normalized ([#337](https://github.com/clevercanary/hca-validation-tools/issues/337)) ([940af43](https://github.com/clevercanary/hca-validation-tools/commit/940af43e96147fd534d583164c9bbbf4470ea34f))
* add compress_h5ad tool ([#319](https://github.com/clevercanary/hca-validation-tools/issues/319)) ([df0c223](https://github.com/clevercanary/hca-validation-tools/commit/df0c2233f039f2cd8ad033eb62b2d9c4497544fb))
* add label_h5ad MCP tool and wire into /curate-h5ad ([#355](https://github.com/clevercanary/hca-validation-tools/issues/355)) ([2fdc6e6](https://github.com/clevercanary/hca-validation-tools/commit/2fdc6e693e9c02b2b7c14455a241c64e45e4e0f0))
* add normalize_raw tool for files with raw counts in X ([#321](https://github.com/clevercanary/hca-validation-tools/issues/321)) ([0d70dd9](https://github.com/clevercanary/hca-validation-tools/commit/0d70dd9b5044b17c238e78bf396bbb3659085bdd))
* add replace_placeholder_values tool ([#305](https://github.com/clevercanary/hca-validation-tools/issues/305)) ([b326d1b](https://github.com/clevercanary/hca-validation-tools/commit/b326d1be0b800b4c439f79304a92190392117669))
* add validate_schema MCP tool wrapping HCAValidator ([#342](https://github.com/clevercanary/hca-validation-tools/issues/342)) ([b3d7b27](https://github.com/clevercanary/hca-validation-tools/commit/b3d7b27aa310c4642b23f18d463f459271ccf5bd))
* add view_edit_log tool to inspect h5ad edit history ([#330](https://github.com/clevercanary/hca-validation-tools/issues/330)) ([3bd1580](https://github.com/clevercanary/hca-validation-tools/commit/3bd15801fb207d6415001cf07eb56be77f73e864))


### Miscellaneous Chores

* add pyright type checker ([#316](https://github.com/clevercanary/hca-validation-tools/issues/316)) ([7814796](https://github.com/clevercanary/hca-validation-tools/commit/78147967a207ffa067fdb79319099c17b5a8ac81))
* add ruff linter, fix unused imports and import sorting ([#312](https://github.com/clevercanary/hca-validation-tools/issues/312)) ([da1fc17](https://github.com/clevercanary/hca-validation-tools/commit/da1fc17f4e760bf904414e4443c9b68acbb43172))

## [0.3.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-mcp-v0.2.0...hca-anndata-mcp-v0.3.0) (2026-04-08)


### Features

* add CAP marker gene validation against var ([#259](https://github.com/clevercanary/hca-validation-tools/issues/259)) ([fcebd87](https://github.com/clevercanary/hca-validation-tools/commit/fcebd8789639e6ce67a4f9b6986c9ba6c4984257))
* add copy_cap_annotations tool ([#261](https://github.com/clevercanary/hca-validation-tools/issues/261)) ([1a68cd0](https://github.com/clevercanary/hca-validation-tools/commit/1a68cd02db491bcc5634e7ad727d3cc8bb33cb28))


### Bug Fixes

* correct release-please changelog-path to avoid double-nesting ([#250](https://github.com/clevercanary/hca-validation-tools/issues/250)) ([0ec58b7](https://github.com/clevercanary/hca-validation-tools/commit/0ec58b77ca1651cf350d346d04b1058b4a40971b))

## [0.2.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-mcp-v0.1.0...hca-anndata-mcp-v0.2.0) (2026-03-31)


### Features

* add convert_cellxgene_to_hca tool ([#242](https://github.com/clevercanary/hca-validation-tools/issues/242)) ([47ba3d8](https://github.com/clevercanary/hca-validation-tools/commit/47ba3d860b0eaab624f55fd06ce040707b1b1dcb))
* add hca-anndata-mcp server for h5ad exploration ([#223](https://github.com/clevercanary/hca-validation-tools/issues/223)) ([613d337](https://github.com/clevercanary/hca-validation-tools/commit/613d337944bb5a495fde5eb2a3c5e37153fa835c))
* add set_uns and list_uns_fields with HCA schema validation ([#237](https://github.com/clevercanary/hca-validation-tools/issues/237)) ([920ce03](https://github.com/clevercanary/hca-validation-tools/commit/920ce034ec3374f293756397e2e0e8980c76d426))
* extract hca-anndata-tools library from MCP server ([#224](https://github.com/clevercanary/hca-validation-tools/issues/224)) ([0ae4ced](https://github.com/clevercanary/hca-validation-tools/commit/0ae4cedfce6c4acc9912f4cb5a7df13a2b6abcdb))
