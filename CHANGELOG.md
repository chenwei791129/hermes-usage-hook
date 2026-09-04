# Changelog

## [0.5.0](https://github.com/chenwei791129/hermes-usage-hook/compare/v0.4.0...v0.5.0) (2026-09-04)


### Features

* add --ref to install from a branch, tag, or commit ([8bdc503](https://github.com/chenwei791129/hermes-usage-hook/commit/8bdc5039ae4592b953f591d8c2e5884458e5eb1e))
* Codex auto-reset success history + /usagehook command ([#16](https://github.com/chenwei791129/hermes-usage-hook/issues/16)) ([0961321](https://github.com/chenwei791129/hermes-usage-hook/commit/09613218d6e173465133ed0dbf30c46f3fcffeac))


### Bug Fixes

* harden Codex credential and threshold handling ([d14b0da](https://github.com/chenwei791129/hermes-usage-hook/commit/d14b0dadf74e7001a82de74f13fe05b784f2f162))
* preserve intentional silence responses ([502ea40](https://github.com/chenwei791129/hermes-usage-hook/commit/502ea4041c1dbcb9373837d7cefc9dee059e7d0a))
* **release:** eliminate uv lock version drift ([7b099f5](https://github.com/chenwei791129/hermes-usage-hook/commit/7b099f5924db976824010f3787c5a7b0db147c56))
* unify plugin Hermes home on the profile-safe resolver ([806af15](https://github.com/chenwei791129/hermes-usage-hook/commit/806af15fca962174f8a653bf5724d2af19334c70))

## [0.4.1](https://github.com/chenwei791129/hermes-usage-hook/compare/v0.4.0...v0.4.1) (2026-07-31)


### Bug Fixes

* preserve intentional silence responses ([803c976](https://github.com/chenwei791129/hermes-usage-hook/commit/803c976822be30acea22ba7166938d8a9e7576ea))

## [0.4.0](https://github.com/chenwei791129/hermes-usage-hook/compare/v0.3.0...v0.4.0) (2026-07-13)


### Features

* add Codex auto reset credits ([#13](https://github.com/chenwei791129/hermes-usage-hook/issues/13)) ([4c7f5f5](https://github.com/chenwei791129/hermes-usage-hook/commit/4c7f5f5b14854d9c35c5dcdecb6250cd4523a015))

## [0.3.0](https://github.com/chenwei791129/hermes-usage-hook/compare/v0.2.2...v0.3.0) (2026-07-13)


### Features

* show available Codex reset credits ([206582f](https://github.com/chenwei791129/hermes-usage-hook/commit/206582fd510e6bce437adb49672378bdda30f64a))

## [0.2.2](https://github.com/chenwei791129/hermes-usage-hook/compare/v0.2.1...v0.2.2) (2026-07-13)


### Bug Fixes

* show weekly usage when 5h window is unavailable ([617a91f](https://github.com/chenwei791129/hermes-usage-hook/commit/617a91f6d3640654b2daa4201f2d6cf3b4d1a76b))

## [0.2.1](https://github.com/chenwei791129/hermes-usage-hook/compare/v0.2.0...v0.2.1) (2026-06-25)


### Bug Fixes

* support Codex credential pool auth ([#5](https://github.com/chenwei791129/hermes-usage-hook/issues/5)) ([7c796c1](https://github.com/chenwei791129/hermes-usage-hook/commit/7c796c1926ea87b7e69eea3d9bb4f5e3962f7669))

## [0.2.0](https://github.com/chenwei791129/hermes-usage-hook/compare/v0.1.0...v0.2.0) (2026-06-25)


### Features

* add development pyproject for centralized tooling and pinned deps ([dc7da17](https://github.com/chenwei791129/hermes-usage-hook/commit/dc7da17ee74f17c36a1af8d703f6f3a33fb621e7))
* add release-please for automated versioning and releases ([0a56e50](https://github.com/chenwei791129/hermes-usage-hook/commit/0a56e50545c933706f3bac0a82679daee0e397ac))
* add transform_llm_output footer hook routing usage to the user's platform ([0769171](https://github.com/chenwei791129/hermes-usage-hook/commit/0769171a6a3bc9d380648432a41edc6e95387fa7))
* add uv run install.py one-command installer ([250a280](https://github.com/chenwei791129/hermes-usage-hook/commit/250a2802b57ea0fde480d57a0c7bb3c3b13065a2))
* Codex 5h usage hook for Hermes Agent ([50b65df](https://github.com/chenwei791129/hermes-usage-hook/commit/50b65dfc539fe21ec98294a8e2575ffe126a4bd4))
* detect provider from model and report matching usage ([c9aa44a](https://github.com/chenwei791129/hermes-usage-hook/commit/c9aa44ab92d775496b4610d6901578a2c3d6fa95))
* package as a Hermes plugin under plugin/ with manifest and register entry point ([c8ffd76](https://github.com/chenwei791129/hermes-usage-hook/commit/c8ffd7601eba7adedac4146ecb339b2504da2eca))
* rename project to hermes-usage-hook ([564bf68](https://github.com/chenwei791129/hermes-usage-hook/commit/564bf685749b5c44638cd47d70409b3a0cd2c3d0))
* render weekly usage window in footer summary ([80ae949](https://github.com/chenwei791129/hermes-usage-hook/commit/80ae9492dcaa5cbcac8d1f02888902d3de482de8))


### Bug Fixes

* read Codex auth.json from $HERMES_HOME when running under Hermes ([#2](https://github.com/chenwei791129/hermes-usage-hook/issues/2)) ([350c7da](https://github.com/chenwei791129/hermes-usage-hook/commit/350c7da48a49de33509e5f7451ecd0098a7afd14))
* read Codex tokens from Hermes' nested per-provider auth.json layout ([#3](https://github.com/chenwei791129/hermes-usage-hook/issues/3)) ([09a1e83](https://github.com/chenwei791129/hermes-usage-hook/commit/09a1e83ad3747d5f1ecba5a1379a6f6fafe8aa74))
* use package-relative imports so the plugin loads under Hermes ([#1](https://github.com/chenwei791129/hermes-usage-hook/issues/1)) ([9efa385](https://github.com/chenwei791129/hermes-usage-hook/commit/9efa385728fe79454d4a3e3a33b7a58051f703b9))
