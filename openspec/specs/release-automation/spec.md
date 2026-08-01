# release-automation Specification

## Purpose

TBD - created by archiving change 'add-release-please'. Update Purpose after archive.

## Requirements

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

---
### Requirement: Manifest-driven configuration with simple release type

The repository SHALL contain `release-please-config.json` and `.release-please-manifest.json` at the project root. The config SHALL define a single package keyed `"."` using `"release-type": "simple"`. The manifest SHALL be the authoritative version source and SHALL start at `0.1.0` for the `"."` package, matching the current `plugin/plugin.yaml` version.

#### Scenario: Configuration files define a simple-type package

- **WHEN** `release-please-config.json` is inspected
- **THEN** it defines a package keyed `"."` with `"release-type": "simple"`
- **AND** `.release-please-manifest.json` maps `"."` to `0.1.0`

---
### Requirement: Synchronize the shipped plugin version from the release manifest

release-please SHALL treat `.release-please-manifest.json` as the release version source and SHALL update the version in `plugin/plugin.yaml` on each release. The config's `extra-files` SHALL list `plugin/plugin.yaml`, whose version line SHALL carry an `x-release-please-version` anchor comment. The config SHALL NOT list the development-only `pyproject.toml` or generated `uv.lock` as release version targets.

#### Scenario: Release configuration targets only the shipped version file

- **WHEN** `release-please-config.json` is inspected
- **THEN** package `.` uses the `simple` release type
- **AND** its `extra-files` list contains `plugin/plugin.yaml`
- **AND** its `extra-files` list does not contain `pyproject.toml` or `uv.lock`
- **AND** the version line in `plugin/plugin.yaml` carries an `x-release-please-version` anchor comment
- **AND** that version matches package `.` in `.release-please-manifest.json`

#### Scenario: Development metadata cannot drift after a release bump

- **WHEN** release-please updates the manifest and shipped plugin version for a release
- **THEN** `pyproject.toml` and the virtual workspace package entry in `uv.lock` retain the fixed development-only version `0.0.0`
- **AND** neither file contains a release-please updater anchor requiring synchronization
