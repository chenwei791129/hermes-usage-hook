# plugin-home-resolution Specification

## Purpose

TBD - created by archiving change 'unify-profile-safe-home'. Update Purpose after archive.

## Requirements

### Requirement: Plugin-owned files resolve the Hermes home through one profile-safe resolver

The plugin SHALL resolve the Hermes home for every file it owns — coordinator state, coordinator locks, one-shot notices, and reset history — through a single resolver that prefers the official `hermes_constants.get_hermes_home()` when that module is importable, and falls back to the `HERMES_HOME` environment variable (default `~/.hermes`, user-expanded) only when the module is absent. An explicitly injected home path SHALL continue to take precedence over both. No plugin-owned file SHALL resolve its home through a separate env-only path that ignores the official resolver.

#### Scenario: Hermes runtime present resolves all files under the official home

- **WHEN** `hermes_constants` is importable and no home is injected
- **THEN** coordinator state, locks, notices, and reset history all resolve under the path returned by `get_hermes_home()`

#### Scenario: Standalone environment falls back to the environment variable

- **WHEN** `hermes_constants` is not importable and `HERMES_HOME` is set
- **THEN** coordinator state, locks, notices, and reset history all resolve under `$HERMES_HOME`

##### Example: Profile override applies to state and history alike

- **GIVEN** `hermes_constants.get_hermes_home()` returns `/profiles/work/.hermes` while `HERMES_HOME` is `/home/u/.hermes`
- **WHEN** the coordinator writes state and the reset-history append runs with no injected home
- **THEN** both the state file and the history file live under `/profiles/work/.hermes`, not `/home/u/.hermes`

---
### Requirement: History reads and writes resolve to the same home without a query-side workaround

The reset-history query SHALL resolve the history file through the same default home resolution as the write path, without injecting the coordinator store's home to force agreement. Because state and history now resolve through one resolver, a successful reset recorded by the coordinator SHALL be visible to the query in the same environment.

#### Scenario: A recorded reset is visible to the query in the same environment

- **WHEN** a successful reset appends a history event and the user later sends the history query in the same environment
- **THEN** the query returns that event, because read and write resolve to the same home

##### Example: Query reads back a reset written under the profile home

- **GIVEN** `hermes_constants.get_hermes_home()` returns `/profiles/work/.hermes` and a successful reset appended one event via the coordinator (no home injected by the query)
- **WHEN** the user sends `/usagehook history`
- **THEN** the reply lists that event, because the write landed under `/profiles/work/.hermes` and the query resolves to the same path
