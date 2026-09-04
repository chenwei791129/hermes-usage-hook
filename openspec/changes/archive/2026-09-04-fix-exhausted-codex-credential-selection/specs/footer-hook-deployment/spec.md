## MODIFIED Requirements

### Requirement: Documentation describes footer and opt-in auto-reset behavior

The `README.md` SHALL document the footer hook as the sole deployment path, deployed as a Hermes plugin directory. The install instructions SHALL direct the reader to install the `plugin/` subdirectory (not the whole repository) to `~/.hermes/plugins/hermes-usage-hook/` and to enable it by adding `hermes-usage-hook` to `plugins.enabled` in `~/.hermes/config.yaml` (or the equivalent `hermes plugins enable` command). The `README.md` SHALL NOT instruct copying the hook as a single standalone `.py` file, SHALL NOT instruct copying the whole repository, SHALL NOT claim that no configuration is needed, and SHALL NOT contain the fixed-destination notification deployment section, the gateway hook deployment section, the `CODEX_USAGE_NOTIFIER` configuration table, or the webhook configuration example.

Describing a whole-repository install as a failure mode to avoid SHALL NOT count as instructing it. Text stating that omitting the plugin subdirectory from a dashboard install identifier copies the whole repository (`tests/`, `openspec/`, `pyproject.toml`, and git metadata) into the user's plugins directory SHALL satisfy this requirement as long as that outcome is presented as a warning and never as an install step.

Auto-reset documentation SHALL be split by audience across three files, and no single file SHALL be required to carry all of it:

- `README.md` SHALL point the reader to `plugin/after-install.md` for setup notes and SHALL state that Codex auto reset is optional. It SHALL NOT be required to carry the auto-reset configuration reference.
- `plugin/after-install.md` SHALL carry the operator-facing decision content. Its required contents are specified by the post-install notice requirement and SHALL NOT be restated here.
- `AGENTS.md` SHALL carry the development and operational detail: the `CODEX_ENABLE_AUTORESET` and `CODEX_AUTORESET_THRESHOLD` override names, the env then plugin config then defaults precedence, the explicit `1..99` threshold range with weekly-remaining semantics, that explicitly configuring threshold 0 fails closed and emits a warning directing operators to `/usage reset` for an already-frozen credential, that the plugin reads its own `auto_reset` schema from the same plugin entry through the host `load_config()` on every hook call, that OAuth credentials do not belong in plugin config, earliest-expiry idempotent credit selection, the notices queue file and the lock protecting it, the single coordinator-locked atomic write that persists a terminal transition, the five-minute post-success suppression window, and the rendered audit footer line.

The documentation SHALL NOT place runtime values in `plugin.yaml` and SHALL NOT instruct users to store OAuth tokens in plugin settings.

#### Scenario: README documents directory install and plugin enablement

- **WHEN** `README.md` is read after this change
- **THEN** it instructs installing the `plugin/` subdirectory as a directory under `~/.hermes/plugins/` and enabling it via `plugins.enabled` in `~/.hermes/config.yaml`, and it contains no single-file copy step, no whole-repository copy step, and no claim that no configuration is needed

#### Scenario: README contains only footer deployment guidance

- **WHEN** `README.md` is read after this change
- **THEN** it describes deploying the footer hook and contains no references to `CODEX_USAGE_NOTIFIER`, the `on_session_end` fixed-destination notifier, or the gateway `agent:end` hook deployment

#### Scenario: Whole-repository install appears only as a warning

- **WHEN** the dashboard install section of `README.md` is read after this change
- **THEN** every mention of installing the whole repository is framed as an outcome to avoid, and no install step directs the reader to use an identifier without the plugin subdirectory

#### Scenario: README delegates auto-reset setup to the post-install notice

- **WHEN** `README.md` is read after this change
- **THEN** it links to `plugin/after-install.md` and states that Codex auto reset is optional, and it is not required to contain the auto-reset config keys, override names, or threshold range

#### Scenario: AGENTS.md documents the auto-reset configuration and operational contract

- **WHEN** `AGENTS.md` is read after this change
- **THEN** it names both environment override variables, states the env then plugin config then defaults precedence, states the explicit `1..99` range with weekly-remaining semantics, states that explicit zero fails closed and directs an operator to `/usage reset`, states that the plugin reads its own config through the host `load_config()`, states that OAuth credentials do not belong in plugin config, describes earliest-expiry idempotent credit selection, names the notices queue file and its lock, describes the single coordinator-locked atomic write and the five-minute suppression window, and shows the audit footer line


---
### Requirement: Ship a post-install notice with the plugin

The repository SHALL include `plugin/after-install.md`, a Markdown file that the `hermes plugins install` CLI command renders after a successful install. Neither `install.py` nor the dashboard install path renders it — `install.py` only copies it along, and the dashboard strips the notice path from its install response — so the README dashboard section carries the same steps independently.

The file SHALL state how to confirm the plugin is enabled, that Codex usage reads ChatGPT OAuth credentials from the Hermes credential store or the Codex CLI auth store and never refreshes or writes them, that the MiniMax fetcher needs `MINIMAX_API_KEY` from the environment or the Hermes `.env` file, that Codex auto reset is disabled by default and that enabling `plugins.entries.hermes-usage-hook.auto_reset.enabled` is standing authorization for irreversible autonomous reset-credit use, that `/usagehook history` reports past auto resets, and that a streaming deployment can send the reply before the footer is applied.

The file SHALL NOT ask the reader to supply credentials as plugin config values, and SHALL NOT describe `auto_reset` as enabled by default.

#### Scenario: Post-install notice exists at the plugin root

- **WHEN** the repository is inspected after this change
- **THEN** `plugin/after-install.md` exists and is non-empty Markdown

#### Scenario: Post-install notice covers the required setup steps

- **WHEN** `plugin/after-install.md` is read after this change
- **THEN** it covers confirming enablement, the Codex ChatGPT OAuth credential requirement, the `MINIMAX_API_KEY` sources, the disabled-by-default state of Codex auto reset with the authorization meaning of enabling it, the `/usagehook history` command, and the streaming caveat

#### Scenario: Post-install notice keeps credentials out of plugin config

- **WHEN** `plugin/after-install.md` is read after this change
- **THEN** it contains no instruction to place OAuth credentials or API tokens under `plugins.entries.hermes-usage-hook`, and no statement that Codex auto reset is enabled by default

#### Scenario: Installing the plugin carries the notice along

- **WHEN** the plugin is installed by copying the `plugin/` directory, whether by `install.py` or by a dashboard subdirectory install
- **THEN** `after-install.md` is present in the installed plugin directory without any installer change

