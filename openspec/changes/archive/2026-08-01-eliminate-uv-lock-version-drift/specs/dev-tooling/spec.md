## MODIFIED Requirements

### Requirement: Provide a repo-root development pyproject.toml

The repository SHALL contain a `pyproject.toml` at the project root that serves as the single source of development configuration. It SHALL declare `requires-python` consistent with the plugin's declared floor (`>=3.10`), SHALL declare a fixed development-only `[project].version` of `0.0.0` without a release-please updater anchor, and SHALL configure uv in non-package mode (`[tool.uv]` with `package = false`) so that syncing the environment installs declared dependencies without attempting to build or install the repository itself as a distributable package.

#### Scenario: Development pyproject is present at the root

- **WHEN** the repository is inspected after this change
- **THEN** `pyproject.toml` exists at the project root
- **AND** `[project]` declares `version = "0.0.0"`
- **AND** the version line does not carry an `x-release-please-version` anchor
- **AND** `[tool.uv]` sets `package = false`

#### Scenario: Syncing the environment installs declared dependencies

- **WHEN** `uv sync` runs on a clean checkout
- **THEN** a virtual environment is created containing the declared runtime and development dependencies
- **AND** `uv run pytest` collects and runs the existing tests under `tests/` and they all pass

## ADDED Requirements

### Requirement: Keep generated lock metadata independent of release versions

The `uv.lock` virtual workspace package entry for `hermes-codex-usage-hook` SHALL contain the fixed development-only version `0.0.0`. The checked-in lockfile SHALL remain valid when only the release manifest and shipped plugin version change.

#### Scenario: Lockfile workspace entry uses a release-independent development version

- **WHEN** the `hermes-codex-usage-hook` virtual workspace package entry in `uv.lock` is inspected
- **THEN** the entry identifies its source as the project root
- **AND** the entry declares `version = "0.0.0"`

#### Scenario: Checked-in lockfile matches fixed development metadata

- **WHEN** `uv lock --check` runs against the checked-in `pyproject.toml` and `uv.lock`
- **THEN** the command exits successfully without rewriting `uv.lock`
