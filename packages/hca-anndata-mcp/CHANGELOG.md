# Changelog

## [0.8.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-mcp-v0.7.4...hca-anndata-mcp-v0.8.0) (2026-08-25)


### ⚠ BREAKING CHANGES

* **hca-anndata-tools:** drop_obs_columns stops refusing schema-named columns ([#621](https://github.com/clevercanary/hca-validation-tools/issues/621))

### Features

* **hca-anndata-tools:** add merge_obs_categories for a typo-split category ([#625](https://github.com/clevercanary/hca-validation-tools/issues/625)) ([f7d4d72](https://github.com/clevercanary/hca-validation-tools/commit/f7d4d72e5251e22e0bdc8ad756e89ca079641872))
* **hca-anndata-tools:** add rename_obs_column for a column whose name misdescribes it ([#616](https://github.com/clevercanary/hca-validation-tools/issues/616)) ([4223165](https://github.com/clevercanary/hca-validation-tools/commit/4223165babcf6e673005577f2a4aa012cdc96b80))
* **hca-anndata-tools:** add set_producer_uns for nested, producer-owned uns fields ([#630](https://github.com/clevercanary/hca-validation-tools/issues/630)) ([680c48a](https://github.com/clevercanary/hca-validation-tools/commit/680c48afc32bd47ff8a8bf26e882f600c013ff11)), closes [#629](https://github.com/clevercanary/hca-validation-tools/issues/629)
* **hca-anndata-tools:** drop_obs_columns stops refusing schema-named columns ([#621](https://github.com/clevercanary/hca-validation-tools/issues/621)) ([7efd902](https://github.com/clevercanary/hca-validation-tools/commit/7efd9022ebf37c85f1ef38c42015bb3ed6c40451))

## [0.7.4](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-mcp-v0.7.3...hca-anndata-mcp-v0.7.4) (2026-08-21)


### Features

* **hca-anndata-tools:** add backfill_obs_from_source to recover metadata lost in integration ([#601](https://github.com/clevercanary/hca-validation-tools/issues/601)) ([f8d4cd1](https://github.com/clevercanary/hca-validation-tools/commit/f8d4cd12267f84aa16b9bb23f09442f963781df9))
* **hca-anndata-tools:** add rename_cell_ids to remedy collapsed cell IDs ([#599](https://github.com/clevercanary/hca-validation-tools/issues/599)) ([648fa95](https://github.com/clevercanary/hca-validation-tools/commit/648fa9517116630348d68a84e80b94bb782c9626))
* **hca-anndata-tools:** add strip_cap_annotations so CAP can be re-copied onto legacy-annotated files ([#603](https://github.com/clevercanary/hca-validation-tools/issues/603)) ([2ceb499](https://github.com/clevercanary/hca-validation-tools/commit/2ceb499405e8df7251fbc8d364245a1f5cea5816))


### Build System

* **hca-anndata-mcp:** widen the hca-schema-validator bound to &gt;=0.15,&lt;0.16 ([#591](https://github.com/clevercanary/hca-validation-tools/issues/591)) ([06b8d00](https://github.com/clevercanary/hca-validation-tools/commit/06b8d00e39d9d49c5b9026e7dd8690eec77294d5))

## [0.7.3](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-mcp-v0.7.2...hca-anndata-mcp-v0.7.3) (2026-08-18)


### Features

* **tools:** let normalize_raw proceed when raw.X duplicates X ([#573](https://github.com/clevercanary/hca-validation-tools/issues/573)) ([3e4adfc](https://github.com/clevercanary/hca-validation-tools/commit/3e4adfc6f71ce226ff4934d26bb0d2dee53a9f38))


### Bug Fixes

* **populator:** refuse instead of writing an all-NaN label column ([#586](https://github.com/clevercanary/hca-validation-tools/issues/586)) ([26a8539](https://github.com/clevercanary/hca-validation-tools/commit/26a8539223a5e97fe60f44e89e008673db6abb41))


### Documentation

* **curate-h5ad:** label with populate_labels, not label_h5ad ([#577](https://github.com/clevercanary/hca-validation-tools/issues/577)) ([863cd7f](https://github.com/clevercanary/hca-validation-tools/commit/863cd7fde8a841cb6f41921b9b06a5f847dd1758))

## [0.7.2](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-mcp-v0.7.1...hca-anndata-mcp-v0.7.2) (2026-07-31)


### Features

* **anndata-tools:** add drop_obs_columns for removing obs columns by name ([#539](https://github.com/clevercanary/hca-validation-tools/issues/539)) ([71b43a1](https://github.com/clevercanary/hca-validation-tools/commit/71b43a1b8f867611a83e682ac005c6cc35b669fb))


### Bug Fixes

* **anndata-tools:** refuse legacy-CAP-layout files in drop_obs_columns ([#554](https://github.com/clevercanary/hca-validation-tools/issues/554)) ([d6d712d](https://github.com/clevercanary/hca-validation-tools/commit/d6d712dadfff831840f5563321bd9e8c90a0f32b))


### Styles

* ruff format + lint sweep, enforce in CI ([#313](https://github.com/clevercanary/hca-validation-tools/issues/313)) ([#499](https://github.com/clevercanary/hca-validation-tools/issues/499)) ([d414d30](https://github.com/clevercanary/hca-validation-tools/commit/d414d309117c284a90cb32266d5c4b8036a86b3f))
* **ruff:** enable PTH (pathlib) and migrate os.path → pathlib (closes [#467](https://github.com/clevercanary/hca-validation-tools/issues/467)) ([#509](https://github.com/clevercanary/hca-validation-tools/issues/509)) ([383a5a8](https://github.com/clevercanary/hca-validation-tools/commit/383a5a80b880a92e7e6b2398d1ac0b675e66ac3b))


### Build System

* **packages:** stop tracking packages/*/uv.lock ([#483](https://github.com/clevercanary/hca-validation-tools/issues/483)) ([#490](https://github.com/clevercanary/hca-validation-tools/issues/490)) ([021e5ac](https://github.com/clevercanary/hca-validation-tools/commit/021e5accce76677389e60f998e2f743320d93ed7))

## [0.7.1](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-mcp-v0.7.0...hca-anndata-mcp-v0.7.1) (2026-07-14)


### Build System

* **packages:** migrate to uv and delete the release-please sed hack ([#472](https://github.com/clevercanary/hca-validation-tools/issues/472)) ([#479](https://github.com/clevercanary/hca-validation-tools/issues/479)) ([e695201](https://github.com/clevercanary/hca-validation-tools/commit/e695201005b6a86d0a50e7331fd6b378c9a5bc5b))

## [0.7.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-mcp-v0.6.0...hca-anndata-mcp-v0.7.0) (2026-07-10)


### ⚠ BREAKING CHANGES

* **hca-anndata-mcp:** delete check_cosmetic_labels_h5ad tool ([#455](https://github.com/clevercanary/hca-validation-tools/issues/455))
* **hca-schema-validator:** warn on cosmetic labels only when unverifiable ([#454](https://github.com/clevercanary/hca-validation-tools/issues/454))
* nest CAP metadata under uns['cap_metadata'] ([#453](https://github.com/clevercanary/hca-validation-tools/issues/453))

### Features

* **hca-anndata-mcp:** delete check_cosmetic_labels_h5ad tool ([#455](https://github.com/clevercanary/hca-validation-tools/issues/455)) ([6061c9f](https://github.com/clevercanary/hca-validation-tools/commit/6061c9fe9fe06a5144ed6dc02fae87f7ee48353f))
* **hca-schema-validator:** warn on cosmetic labels only when unverifiable ([#454](https://github.com/clevercanary/hca-validation-tools/issues/454)) ([d1518b1](https://github.com/clevercanary/hca-validation-tools/commit/d1518b1959a98750b4298cf383c259720f42888d))
* nest CAP metadata under uns['cap_metadata'] ([#453](https://github.com/clevercanary/hca-validation-tools/issues/453)) ([99c6ba0](https://github.com/clevercanary/hca-validation-tools/commit/99c6ba01efc18ca852e8996663a746b0d12e67a5))
* populate_labels — per-column fill/verify for HCA-tracker-imported files ([#421](https://github.com/clevercanary/hca-validation-tools/issues/421)) ([#439](https://github.com/clevercanary/hca-validation-tools/issues/439)) ([673e690](https://github.com/clevercanary/hca-validation-tools/commit/673e690a6320d31ce8493657cf06770aa1a4624e))
* **skills:** wire HCACellAnnotationValidator into curate-h5ad + evaluate-h5ad ([#423](https://github.com/clevercanary/hca-validation-tools/issues/423)) ([#429](https://github.com/clevercanary/hca-validation-tools/issues/429)) ([8f14772](https://github.com/clevercanary/hca-validation-tools/commit/8f147720e888af493edcad1deb894be0c0874c43))
* **strip:** strip_forbidden_obs_columns — SRE strip for HCA-layout files ([#434](https://github.com/clevercanary/hca-validation-tools/issues/434)) ([#435](https://github.com/clevercanary/hca-validation-tools/issues/435)) ([5e7925e](https://github.com/clevercanary/hca-validation-tools/commit/5e7925ec38da4eff43744a42ac04106512e1e267))

## [0.6.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-mcp-v0.5.1...hca-anndata-mcp-v0.6.0) (2026-05-25)


### ⚠ BREAKING CHANGES

* **hca-schema-validator:** forbid self_reported_ethnicity columns in obs ([#370](https://github.com/clevercanary/hca-validation-tools/issues/370)) (#409)

### Features

* **hca-schema-validator:** forbid self_reported_ethnicity columns in obs ([#370](https://github.com/clevercanary/hca-validation-tools/issues/370)) ([#409](https://github.com/clevercanary/hca-validation-tools/issues/409)) ([53c2fd8](https://github.com/clevercanary/hca-validation-tools/commit/53c2fd808af90611068738675de47fb24596b7c1))

## [0.5.1](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-mcp-v0.5.0...hca-anndata-mcp-v0.5.1) (2026-05-17)


### Miscellaneous Chores

* **mcp/label:** drop vestigial obs_label_cols_overwritten / var_feature_name_overwritten ([#395](https://github.com/clevercanary/hca-validation-tools/issues/395)) ([4b869cd](https://github.com/clevercanary/hca-validation-tools/commit/4b869cd5f7c56baf9afb32b64cba2eeb0b7702e9))

## [0.5.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-mcp-v0.4.1...hca-anndata-mcp-v0.5.0) (2026-04-24)


### Features

* HCALabeler reserved-column preflight ([#375](https://github.com/clevercanary/hca-validation-tools/issues/375)) ([ad9de18](https://github.com/clevercanary/hca-validation-tools/commit/ad9de18e68df3716b5f6e444aef4437bd17c2aa9))
* validate producer cosmetic obs columns vs ontology_term_id ([#378](https://github.com/clevercanary/hca-validation-tools/issues/378)) ([6e575eb](https://github.com/clevercanary/hca-validation-tools/commit/6e575eb711d96e81bdff4a59f070cd57efa2de4c))

## [0.4.1](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-mcp-v0.4.0...hca-anndata-mcp-v0.4.1) (2026-04-22)


### Bug Fixes

* rewrite hca-schema-validator path dep for hca-anndata-mcp publish ([#367](https://github.com/clevercanary/hca-validation-tools/issues/367)) ([38d0225](https://github.com/clevercanary/hca-validation-tools/commit/38d022597216edfb31d5dd06f2b76438161d6e0d))

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
