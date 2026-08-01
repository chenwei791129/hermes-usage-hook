## RENAMED Requirements

- FROM: `### Requirement: Synchronized version across plugin manifest and pyproject`
- TO: `### Requirement: Synchronize the shipped plugin version from the release manifest`

## MODIFIED Requirements

### Requirement: Synchronized version across plugin manifest and pyproject

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
