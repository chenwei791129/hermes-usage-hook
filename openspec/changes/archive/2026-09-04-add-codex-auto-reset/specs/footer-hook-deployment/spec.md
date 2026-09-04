## RENAMED Requirements

- FROM: `### Requirement: Distribute only the footer hook`
- TO: `### Requirement: Distribute only the supported usage hooks`

- FROM: `### Requirement: Documentation describes only the footer hook path`
- TO: `### Requirement: Documentation describes footer and opt-in auto-reset behavior`

## MODIFIED Requirements

### Requirement: Distribute only the footer hook

The repository SHALL ship exactly two Hermes hooks: the footer hook implemented as a plugin hook on `transform_llm_output`, and the Codex auto-reset preflight hook on `pre_llm_call`. The repository SHALL NOT include the fixed-destination notification plugin hook (`on_session_end`), the gateway hook (`agent:end`), background polling, or any unrelated hook. Both hooks SHALL resolve their modules from the installed `plugin/` directory. The shared usage module SHALL remain available for the footer hook to import, and the provider implementations it dispatches to SHALL live in the `plugin/providers/` Python package within the plugin root rather than as top-level modules in the repository root.

#### Scenario: Supported hooks and shared module are present

- **WHEN** the repository is inspected after this change
- **THEN** `plugin/hooks/footer_hook.py`, `plugin/usage.py`, `plugin/autoreset.py`, and `plugin/providers/codex_usage.py` exist, and the plugin registers handlers for `transform_llm_output` and `pre_llm_call`

#### Scenario: Provider implementations are consolidated under the providers package

- **WHEN** the repository is inspected after this change
- **THEN** `plugin/providers/__init__.py`, `plugin/providers/codex_usage.py`, and `plugin/providers/minimax_usage.py` exist, and the root-level `usage.py`, `providers/`, and `hooks/` do not exist

#### Scenario: Fixed-destination and gateway hooks are removed

- **WHEN** the repository is inspected after this change
- **THEN** `hooks/plugin_hook.py`, `hooks/gateway/handler.py`, and `hooks/gateway/HOOK.yaml` do not exist, and the `hooks/gateway/` directory is absent

#### Scenario: Auto reset is disabled

- **WHEN** effective `auto_reset.enabled` resolves to false from env, plugin config, and defaults
- **THEN** the `pre_llm_call` hook returns without network activity or prompt context, and the footer hook continues to operate normally

---

### Requirement: Documentation describes only the footer hook path

The `README.md` SHALL document the footer hook as the sole deployment path, deployed as a Hermes plugin directory. The install instructions SHALL direct the reader to install the `plugin/` subdirectory (not the whole repository) to `~/.hermes/plugins/hermes-usage-hook/` and to enable it by adding `hermes-usage-hook` to `plugins.enabled` in `~/.hermes/config.yaml` (or the equivalent `hermes plugins enable` command). The `README.md` SHALL NOT instruct copying the hook as a single standalone `.py` file, SHALL NOT instruct copying the whole repository, SHALL NOT claim that no configuration is needed, and SHALL NOT contain the fixed-destination notification deployment section, the gateway hook deployment section, the `CODEX_USAGE_NOTIFIER` configuration table, or the webhook configuration example.

Describing a whole-repository install as a failure mode to avoid SHALL NOT count as instructing it. Text stating that omitting the plugin subdirectory from a dashboard install identifier copies the whole repository (`tests/`, `openspec/`, `pyproject.toml`, and git metadata) into the user's plugins directory SHALL satisfy this requirement as long as that outcome is presented as a warning and never as an install step.

Auto-reset documentation SHALL be split by audience across three files, and no single file SHALL be required to carry all of it:

- `README.md` SHALL point the reader to `plugin/after-install.md` for setup notes and SHALL state that Codex auto reset is optional. It SHALL NOT be required to carry the auto-reset configuration reference.
- `plugin/after-install.md` SHALL carry the operator-facing decision content. Its required contents are specified by the post-install notice requirement and SHALL NOT be restated here.
- `AGENTS.md` SHALL carry the development and operational detail: the `CODEX_ENABLE_AUTORESET` and `CODEX_AUTORESET_THRESHOLD` override names, the env then plugin config then defaults precedence, the `0..99` threshold range with weekly-remaining semantics, that the plugin reads its own `auto_reset` schema from the same plugin entry through the host `load_config()` on every hook call, that OAuth credentials do not belong in plugin config, earliest-expiry idempotent credit selection, the notices queue file and the lock protecting it, the single coordinator-locked atomic write that persists a terminal transition, the five-minute post-success suppression window, and the rendered audit footer line.

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
- **THEN** it names both environment override variables, states the env then plugin config then defaults precedence, states the `0..99` range with weekly-remaining semantics, states that the plugin reads its own config through the host `load_config()`, states that OAuth credentials do not belong in plugin config, describes earliest-expiry idempotent credit selection, names the notices queue file and its lock, describes the single coordinator-locked atomic write and the five-minute suppression window, and shows the audit footer line

---

### Requirement: Ship a Hermes plugin manifest

The repository SHALL include a `plugin.yaml` manifest at the plugin root (`plugin/plugin.yaml`) that declares the plugin name `hermes-usage-hook`, `kind: standalone`, and a `provides_hooks` list containing exactly `transform_llm_output` and `pre_llm_call`, so that Hermes discovery recognizes the directory as a loadable plugin. The manifest SHALL also declare `version`, `description`, and `author`. The manifest SHALL NOT declare `requires_env` and SHALL NOT carry any auto-reset runtime value; auto-reset settings are read from the host plugin config at call time.

#### Scenario: Manifest declares the plugin and both hooks

- **WHEN** `plugin/plugin.yaml` is parsed after this change
- **THEN** it parses as valid YAML, its `name` is `hermes-usage-hook`, its `kind` is `standalone`, and its `provides_hooks` list contains `transform_llm_output` and `pre_llm_call` exactly once each

#### Scenario: Manifest carries no runtime configuration

- **WHEN** `plugin/plugin.yaml` is parsed after this change
- **THEN** it declares no `requires_env` key and no `auto_reset` key

---

### Requirement: Expose a register entry point from the plugin root

The repository SHALL expose a callable `register(ctx)` from the plugin root package (`plugin/__init__.py`) that registers at least the footer handler on `transform_llm_output` and the Codex auto-reset preflight handler on `pre_llm_call`. Registering further host integrations from the same entry point SHALL be permitted. Registration SHALL NOT perform network access or filesystem mutation; the runtime handlers enforce configuration and safety policy. The footer hook SHALL resolve its `usage` and `providers` modules from the plugin root (`plugin/`) rather than from a separate `~/.hermes/lib` location, so the plugin loads from a single installed directory.

#### Scenario: Plugin root exposes register

- **WHEN** the plugin root package (`plugin/`) is imported after this change
- **THEN** importing it yields a callable `register`, and the import succeeds without `usage` or `providers` being on an external `~/.hermes/lib` path

#### Scenario: Register wires both hook handlers

- **WHEN** a fake plugin context records registration calls
- **THEN** one handler is registered for `transform_llm_output`, one handler is registered for `pre_llm_call`, and registration itself performs no usage or consume request

#### Scenario: Shared modules resolve from the plugin directory

- **WHEN** the plugin root (`plugin/`) is inspected after this change
- **THEN** `plugin.yaml`, `__init__.py`, `usage.py`, `autoreset.py`, `providers/__init__.py`, and `hooks/footer_hook.py` all reside in the plugin root, and `hooks/footer_hook.py` no longer inserts `~/.hermes/lib` into `sys.path`
