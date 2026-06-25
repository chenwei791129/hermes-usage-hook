## ADDED Requirements

### Requirement: Automated release workflow driven by Conventional Commits

The repository SHALL provide a GitHub Actions workflow at `.github/workflows/release-please.yml` that runs `googleapis/release-please-action@v4` on every push to the `main` branch. The workflow SHALL declare workflow-level `permissions` granting `contents: write` and `pull-requests: write`, and SHALL NOT contain any package-publishing steps (no `uv build`, `uv publish`, or PyPI upload).

#### Scenario: Workflow triggers on push to main

- **WHEN** a commit is pushed to the `main` branch
- **THEN** the `release-please.yml` workflow runs `googleapis/release-please-action@v4`
- **AND** the workflow declares `contents: write` and `pull-requests: write` permissions
- **AND** the workflow contains no PyPI publishing steps

#### Scenario: Conventional commits accumulate into a release pull request

- **WHEN** one or more Conventional Commits (for example `feat:` or `fix:`) are pushed to `main`
- **THEN** release-please creates or updates a release pull request that records the derived next semantic version and updates the CHANGELOG

### Requirement: Manifest-driven configuration with simple release type

The repository SHALL contain `release-please-config.json` and `.release-please-manifest.json` at the project root. The config SHALL define a single package keyed `"."` using `"release-type": "simple"`. The manifest SHALL be the authoritative version source and SHALL start at `0.1.0` for the `"."` package, matching the current `plugin/plugin.yaml` version.

#### Scenario: Configuration files define a simple-type package

- **WHEN** `release-please-config.json` is inspected
- **THEN** it defines a package keyed `"."` with `"release-type": "simple"`
- **AND** `.release-please-manifest.json` maps `"."` to `0.1.0`

### Requirement: Synchronized version across plugin manifest and pyproject

release-please SHALL update both `plugin/plugin.yaml` and `pyproject.toml` version strings on each release. The config's `extra-files` SHALL list both files, and each file's version line SHALL carry an `x-release-please-version` anchor comment so the generic updater can locate and rewrite it. The `pyproject.toml` version SHALL be `0.1.0` (no longer a placeholder `0`), and its version-related comment SHALL state that the version is synchronized by release-please while the project remains non-distributable (`package = false`).

#### Scenario: Both version files carry the release-please anchor

- **WHEN** `plugin/plugin.yaml` and `pyproject.toml` are inspected
- **THEN** each version line carries an `x-release-please-version` anchor comment
- **AND** both versions read `0.1.0`
- **AND** `release-please-config.json` lists both files under `extra-files`

#### Scenario: pyproject version comment reflects release-please ownership

- **WHEN** the version-related comment in `pyproject.toml` is read
- **THEN** it states the version is synchronized by release-please
- **AND** it does not claim the version is a meaningless placeholder
- **AND** `pyproject.toml` still sets `package = false` under `[tool.uv]`
