# Changelog

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
