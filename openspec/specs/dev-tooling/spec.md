# dev-tooling Specification

## Purpose

TBD - created by archiving change 'add-dev-pyproject'. Update Purpose after archive.

## Requirements

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

---
### Requirement: Pin runtime dependencies to the Hermes host versions

The development `pyproject.toml` SHALL declare the plugin's runtime dependencies with versions pinned to match the Hermes host environment, specifically `httpx==0.28.1` and `pyyaml==6.0.3`, so that local tests and standalone checks run against the same versions Hermes provides at plugin load time.

#### Scenario: Runtime dependency versions match Hermes

- **WHEN** the `dependencies` list in the root `pyproject.toml` is inspected
- **THEN** it pins `httpx==0.28.1` and `pyyaml==6.0.3`

---
### Requirement: Centralize development tooling configuration

The development `pyproject.toml` SHALL declare development tools (`pytest`, `ruff`, `ty`) under a PEP 735 `[dependency-groups]` `dev` group, and SHALL hold their configuration under `[tool.*]` sections. The ruff configuration SHALL preserve the repository's existing default-rules behavior, setting only `target-version` aligned with `requires-python` and introducing no new lint rule selection. The pytest configuration SHALL set `testpaths` to the `tests` directory and SHALL NOT take over import-path injection, leaving the existing `tests/conftest.py` mechanism unchanged.

#### Scenario: Development tools are declared and configured centrally

- **WHEN** the root `pyproject.toml` is inspected
- **THEN** `pytest`, `ruff`, and `ty` appear under `[dependency-groups]` `dev`
- **AND** `[tool.ruff]` sets only `target-version` without adding a new rule selection
- **AND** `[tool.pytest.ini_options]` sets `testpaths` and does not declare `pythonpath`

#### Scenario: Existing test import mechanism is preserved

- **WHEN** the repository is inspected after this change
- **THEN** `tests/conftest.py` retains its `sys.path` injection and is unmodified

---
### Requirement: Keep the shipped plugin free of the development pyproject

The development `pyproject.toml` SHALL NOT be included in the artifact installed by the installer. The installer SHALL continue to copy only the `plugin/` directory into the Hermes plugins directory, and SHALL NOT change the directory-plugin distribution model.

#### Scenario: Installed plugin excludes the development pyproject

- **WHEN** the installer runs and installs the plugin to the Hermes plugins directory
- **THEN** the installed plugin directory does not contain `pyproject.toml`

---
### Requirement: Keep generated lock metadata independent of release versions

The `uv.lock` virtual workspace package entry for `hermes-codex-usage-hook` SHALL contain the fixed development-only version `0.0.0`. The checked-in lockfile SHALL remain valid when only the release manifest and shipped plugin version change.

#### Scenario: Lockfile workspace entry uses a release-independent development version

- **WHEN** the `hermes-codex-usage-hook` virtual workspace package entry in `uv.lock` is inspected
- **THEN** the entry identifies its source as the project root
- **AND** the entry declares `version = "0.0.0"`

#### Scenario: Checked-in lockfile matches fixed development metadata

- **WHEN** `uv lock --check` runs against the checked-in `pyproject.toml` and `uv.lock`
- **THEN** the command exits successfully without rewriting `uv.lock`
