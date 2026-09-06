# Changelog

## [0.7.1](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-tools-v0.7.0...hca-anndata-tools-v0.7.1) (2026-09-06)


### Features

* **hca-anndata-tools:** check_donor_sex returns verdict_counts and omits agreeing donors ([#704](https://github.com/clevercanary/hca-validation-tools/issues/704)) ([f5b7f2b](https://github.com/clevercanary/hca-validation-tools/commit/f5b7f2b5f83a0dec124bc6aed01eeeac0c1ab163))
* **hca-anndata-tools:** count gate — one streaming pass over the raw count matrix ([#690](https://github.com/clevercanary/hca-validation-tools/issues/690)) ([da36e02](https://github.com/clevercanary/hca-validation-tools/commit/da36e02a0dd84dc437af60cbaf6990e2652ac2fe))
* **hca-anndata-tools:** duplicate cells by raw count content hash — a port of Lattice's evaluate_dup_counts ([#691](https://github.com/clevercanary/hca-validation-tools/issues/691)) ([f10e5c0](https://github.com/clevercanary/hca-validation-tools/commit/f10e5c024fcc3049134b8134ed198cbd902ad078))
* **hca-anndata-tools:** embedding gate — every obsm array is finite and non-degenerate ([#694](https://github.com/clevercanary/hca-validation-tools/issues/694)) ([17ac589](https://github.com/clevercanary/hca-validation-tools/commit/17ac58941d80c00b27fa389c91024274c1c967b4))
* **hca-anndata-tools:** find_source_datasets — which tracker source datasets an integrated object is built from ([#706](https://github.com/clevercanary/hca-validation-tools/issues/706)) ([a386a6f](https://github.com/clevercanary/hca-validation-tools/commit/a386a6f4bcdadf3871b2560bedb07b9c74e87222))
* **hca-anndata-tools:** infer donor sex from expression and compare with the annotation — a port of Lattice's evaluate_donors_sex ([#695](https://github.com/clevercanary/hca-validation-tools/issues/695)) ([61e36c7](https://github.com/clevercanary/hca-validation-tools/commit/61e36c7f4d85d833bc99e4ee688cba9391daf497))
* **hca-anndata-tools:** normalize nullable strings on write — every write fixes the format in its own path ([#649](https://github.com/clevercanary/hca-validation-tools/issues/649)) ([fa1dd12](https://github.com/clevercanary/hca-validation-tools/commit/fa1dd12f2374caee10b028418cb37d9dc394ff40))
* **hca-anndata-tools:** report dataframe string encodings in get_storage_info ([#639](https://github.com/clevercanary/hca-validation-tools/issues/639)) ([36e6032](https://github.com/clevercanary/hca-validation-tools/commit/36e6032cef62b424536fecb0c358d54a94bcaaa7))
* **hca-anndata-tools:** report which cells carry a 10x barcode in the obs index — a port of Lattice's extract_barcodes ([#697](https://github.com/clevercanary/hca-validation-tools/issues/697)) ([c872a7c](https://github.com/clevercanary/hca-validation-tools/commit/c872a7cf4abedc2ee2c91168e4ee8f185b201c10)), closes [#679](https://github.com/clevercanary/hca-validation-tools/issues/679)


### Bug Fixes

* **hca-anndata-tools:** carry the traceback out of copy_cap's broad handler ([#673](https://github.com/clevercanary/hca-validation-tools/issues/673)) ([2ed6bfa](https://github.com/clevercanary/hca-validation-tools/commit/2ed6bfafecccec81eedc2f48667b682632e09972))
* **hca-anndata-tools:** open through anndata in every tool that touches a file ([#667](https://github.com/clevercanary/hca-validation-tools/issues/667)) ([8d1a0da](https://github.com/clevercanary/hca-validation-tools/commit/8d1a0da52a548f58599791d46b7a91666cc001b4)), closes [#661](https://github.com/clevercanary/hca-validation-tools/issues/661)
* **hca-anndata-tools:** read string elements through anndata's registry, not hand-rolled slices ([#642](https://github.com/clevercanary/hca-validation-tools/issues/642)) ([d602072](https://github.com/clevercanary/hca-validation-tools/commit/d60207293ec6da4f2f209516d6cbfd61aaef1bc0))
* **hca-anndata-tools:** scope read_element's object coercion to strings ([#670](https://github.com/clevercanary/hca-validation-tools/issues/670)) ([c2277ba](https://github.com/clevercanary/hca-validation-tools/commit/c2277ba3a22de57c3db8afe9a153b646df6014ee)), closes [#668](https://github.com/clevercanary/hca-validation-tools/issues/668)


### Documentation

* **hca-anndata-tools:** say we don't operate on files anndata can't open ([#660](https://github.com/clevercanary/hca-validation-tools/issues/660)) ([7102467](https://github.com/clevercanary/hca-validation-tools/commit/71024679761dad1950df0946f85ebe2b27581238)), closes [#656](https://github.com/clevercanary/hca-validation-tools/issues/656)

## [0.7.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-tools-v0.6.4...hca-anndata-tools-v0.7.0) (2026-08-25)


### ⚠ BREAKING CHANGES

* **hca-anndata-tools:** drop_obs_columns stops refusing schema-named columns ([#621](https://github.com/clevercanary/hca-validation-tools/issues/621))

### Features

* **hca-anndata-tools:** add merge_obs_categories for a typo-split category ([#625](https://github.com/clevercanary/hca-validation-tools/issues/625)) ([f7d4d72](https://github.com/clevercanary/hca-validation-tools/commit/f7d4d72e5251e22e0bdc8ad756e89ca079641872))
* **hca-anndata-tools:** add rename_obs_column for a column whose name misdescribes it ([#616](https://github.com/clevercanary/hca-validation-tools/issues/616)) ([4223165](https://github.com/clevercanary/hca-validation-tools/commit/4223165babcf6e673005577f2a4aa012cdc96b80))
* **hca-anndata-tools:** add set_producer_uns for nested, producer-owned uns fields ([#630](https://github.com/clevercanary/hca-validation-tools/issues/630)) ([680c48a](https://github.com/clevercanary/hca-validation-tools/commit/680c48afc32bd47ff8a8bf26e882f600c013ff11)), closes [#629](https://github.com/clevercanary/hca-validation-tools/issues/629)
* **hca-anndata-tools:** drop_obs_columns stops refusing schema-named columns ([#621](https://github.com/clevercanary/hca-validation-tools/issues/621)) ([7efd902](https://github.com/clevercanary/hca-validation-tools/commit/7efd9022ebf37c85f1ef38c42015bb3ed6c40451))


### Bug Fixes

* **hca-anndata-tools:** decode np.bytes_ and finish bytes inside arrays ([#634](https://github.com/clevercanary/hca-validation-tools/issues/634)) ([ca2492b](https://github.com/clevercanary/hca-validation-tools/commit/ca2492b3d37b80b9a031126405e4827cd7751c50)), closes [#632](https://github.com/clevercanary/hca-validation-tools/issues/632)
* **hca-anndata-tools:** narrow every uns read through read_uns ([#618](https://github.com/clevercanary/hca-validation-tools/issues/618)) ([021e08b](https://github.com/clevercanary/hca-validation-tools/commit/021e08b573ba5dcf3c9121f8f3bd48cd2a41c9f2))
* **hca-anndata-tools:** remap the palette when a category is dropped ([#627](https://github.com/clevercanary/hca-validation-tools/issues/627)) ([f1e08c2](https://github.com/clevercanary/hca-validation-tools/commit/f1e08c2079b5ecc2701e80131e2db22d7f47bed3))
* **hca-anndata-tools:** stop same-second snapshot collisions from destroying the previous snapshot ([#609](https://github.com/clevercanary/hca-validation-tools/issues/609)) ([4dd3dc4](https://github.com/clevercanary/hca-validation-tools/commit/4dd3dc406df6d3208629b845ab0f802e85018849)), closes [#598](https://github.com/clevercanary/hca-validation-tools/issues/598)


### Code Refactoring

* **hca-anndata-tools:** adopt the shared snapshot helper in the five hand-rolled tools ([#628](https://github.com/clevercanary/hca-validation-tools/issues/628)) ([b00d8be](https://github.com/clevercanary/hca-validation-tools/commit/b00d8bed183a4655237684d07f19d26d935248ae))
* **hca-anndata-tools:** extract shared structural invariants and the obs-reference detector ([#623](https://github.com/clevercanary/hca-validation-tools/issues/623)) ([e07c03a](https://github.com/clevercanary/hca-validation-tools/commit/e07c03ab4bb1398595dd5a85fbbd242da6f2251c))
* **hca-anndata-tools:** one definition of the non-producer uns roots ([#633](https://github.com/clevercanary/hca-validation-tools/issues/633)) ([6e09a19](https://github.com/clevercanary/hca-validation-tools/commit/6e09a19772f756f23b8c59d9f9aa1deeb51418e1)), closes [#631](https://github.com/clevercanary/hca-validation-tools/issues/631)

## [0.6.4](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-tools-v0.6.3...hca-anndata-tools-v0.6.4) (2026-08-21)


### Features

* **hca-anndata-tools:** add backfill_obs_from_source to recover metadata lost in integration ([#601](https://github.com/clevercanary/hca-validation-tools/issues/601)) ([f8d4cd1](https://github.com/clevercanary/hca-validation-tools/commit/f8d4cd12267f84aa16b9bb23f09442f963781df9))
* **hca-anndata-tools:** add rename_cell_ids to remedy collapsed cell IDs ([#599](https://github.com/clevercanary/hca-validation-tools/issues/599)) ([648fa95](https://github.com/clevercanary/hca-validation-tools/commit/648fa9517116630348d68a84e80b94bb782c9626))
* **hca-anndata-tools:** add strip_cap_annotations so CAP can be re-copied onto legacy-annotated files ([#603](https://github.com/clevercanary/hca-validation-tools/issues/603)) ([2ceb499](https://github.com/clevercanary/hca-validation-tools/commit/2ceb499405e8df7251fbc8d364245a1f5cea5816))

## [0.6.3](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-tools-v0.6.2...hca-anndata-tools-v0.6.3) (2026-08-18)


### Features

* **tools:** let normalize_raw proceed when raw.X duplicates X ([#573](https://github.com/clevercanary/hca-validation-tools/issues/573)) ([3e4adfc](https://github.com/clevercanary/hca-validation-tools/commit/3e4adfc6f71ce226ff4934d26bb0d2dee53a9f38))

## [0.6.2](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-tools-v0.6.1...hca-anndata-tools-v0.6.2) (2026-07-31)


### Features

* **anndata-tools:** add drop_obs_columns for removing obs columns by name ([#539](https://github.com/clevercanary/hca-validation-tools/issues/539)) ([71b43a1](https://github.com/clevercanary/hca-validation-tools/commit/71b43a1b8f867611a83e682ac005c6cc35b669fb))


### Bug Fixes

* **anndata-tools:** refuse legacy-CAP-layout files in drop_obs_columns ([#554](https://github.com/clevercanary/hca-validation-tools/issues/554)) ([d6d712d](https://github.com/clevercanary/hca-validation-tools/commit/d6d712dadfff831840f5563321bd9e8c90a0f32b))
* **schema:** make three obs columns visible to annDataLocation discovery ([#545](https://github.com/clevercanary/hca-validation-tools/issues/545)) ([2f4679b](https://github.com/clevercanary/hca-validation-tools/commit/2f4679b87424e3c2c6ea0c5f408106c466843b36))


### Styles

* ruff format + lint sweep, enforce in CI ([#313](https://github.com/clevercanary/hca-validation-tools/issues/313)) ([#499](https://github.com/clevercanary/hca-validation-tools/issues/499)) ([d414d30](https://github.com/clevercanary/hca-validation-tools/commit/d414d309117c284a90cb32266d5c4b8036a86b3f))
* **ruff:** enable flake8-bugbear (B) and fix violations ([#467](https://github.com/clevercanary/hca-validation-tools/issues/467)) ([#502](https://github.com/clevercanary/hca-validation-tools/issues/502)) ([bbb8cb9](https://github.com/clevercanary/hca-validation-tools/commit/bbb8cb953b691b41b73c76bbe70faae8addbd87a))
* **ruff:** enable PTH (pathlib) and migrate os.path → pathlib (closes [#467](https://github.com/clevercanary/hca-validation-tools/issues/467)) ([#509](https://github.com/clevercanary/hca-validation-tools/issues/509)) ([383a5a8](https://github.com/clevercanary/hca-validation-tools/commit/383a5a80b880a92e7e6b2398d1ac0b675e66ac3b))
* **ruff:** enable RET/SIM/C4/PIE/RUF small families ([#503](https://github.com/clevercanary/hca-validation-tools/issues/503)) ([#506](https://github.com/clevercanary/hca-validation-tools/issues/506)) ([52657cf](https://github.com/clevercanary/hca-validation-tools/commit/52657cf97a0315a1cf5bd988fecce42dd04bc207))
* **ruff:** enable UP (pyupgrade) and apply autofixes (part of [#467](https://github.com/clevercanary/hca-validation-tools/issues/467)) ([#508](https://github.com/clevercanary/hca-validation-tools/issues/508)) ([e1f162f](https://github.com/clevercanary/hca-validation-tools/commit/e1f162f01f92b022b55c7e866c7723d1f02146af))


### Build System

* **packages:** stop tracking packages/*/uv.lock ([#483](https://github.com/clevercanary/hca-validation-tools/issues/483)) ([#490](https://github.com/clevercanary/hca-validation-tools/issues/490)) ([021e5ac](https://github.com/clevercanary/hca-validation-tools/commit/021e5accce76677389e60f998e2f743320d93ed7))

## [0.6.1](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-tools-v0.6.0...hca-anndata-tools-v0.6.1) (2026-07-14)


### Build System

* **packages:** migrate to uv and delete the release-please sed hack ([#472](https://github.com/clevercanary/hca-validation-tools/issues/472)) ([#479](https://github.com/clevercanary/hca-validation-tools/issues/479)) ([e695201](https://github.com/clevercanary/hca-validation-tools/commit/e695201005b6a86d0a50e7331fd6b378c9a5bc5b))

## [0.6.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-tools-v0.5.1...hca-anndata-tools-v0.6.0) (2026-07-10)


### ⚠ BREAKING CHANGES

* nest CAP metadata under uns['cap_metadata'] ([#453](https://github.com/clevercanary/hca-validation-tools/issues/453))

### Features

* nest CAP metadata under uns['cap_metadata'] ([#453](https://github.com/clevercanary/hca-validation-tools/issues/453)) ([99c6ba0](https://github.com/clevercanary/hca-validation-tools/commit/99c6ba01efc18ca852e8996663a746b0d12e67a5))
* populate_labels — per-column fill/verify for HCA-tracker-imported files ([#421](https://github.com/clevercanary/hca-validation-tools/issues/421)) ([#439](https://github.com/clevercanary/hca-validation-tools/issues/439)) ([673e690](https://github.com/clevercanary/hca-validation-tools/commit/673e690a6320d31ce8493657cf06770aa1a4624e))
* **strip:** strip_forbidden_obs_columns — SRE strip for HCA-layout files ([#434](https://github.com/clevercanary/hca-validation-tools/issues/434)) ([#435](https://github.com/clevercanary/hca-validation-tools/issues/435)) ([5e7925e](https://github.com/clevercanary/hca-validation-tools/commit/5e7925ec38da4eff43744a42ac04106512e1e267))

## [0.5.1](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-tools-v0.5.0...hca-anndata-tools-v0.5.1) (2026-05-25)


### Features

* **hca-anndata-tools:** strip forbidden SRE obs columns in convert_cellxgene_to_hca ([#410](https://github.com/clevercanary/hca-validation-tools/issues/410)) ([#419](https://github.com/clevercanary/hca-validation-tools/issues/419)) ([e9df88e](https://github.com/clevercanary/hca-validation-tools/commit/e9df88ed9f1a56e832d8e5b4497e3815a9b3e26d))

## [0.5.0](https://github.com/clevercanary/hca-validation-tools/compare/hca-anndata-tools-v0.4.0...hca-anndata-tools-v0.5.0) (2026-05-17)


### Features

* copy_cap_annotations overlap stats — gene axis + CAP/HCA reshape; persist skill reports ([#391](https://github.com/clevercanary/hca-validation-tools/issues/391)) ([18aeeac](https://github.com/clevercanary/hca-validation-tools/commit/18aeeac1a2aa7b6a7997c721b75fe3e338075a00))

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
