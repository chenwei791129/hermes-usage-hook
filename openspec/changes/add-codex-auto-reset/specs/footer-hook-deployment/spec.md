## MODIFIED Requirements

### Requirement: Distribute only the supported usage hooks

The repository SHALL ship exactly two Hermes hooks: the existing footer hook on `transform_llm_output` and the Codex auto-reset preflight hook on `pre_llm_call`. It SHALL NOT include fixed-destination `on_session_end`, gateway `agent:end`, background polling, or unrelated hooks. Both hooks SHALL use modules from the installed `plugin/` directory.

#### Scenario: Supported hooks are present

- **WHEN** the repository is inspected after this change
- **THEN** the plugin registers `transform_llm_output` and `pre_llm_call`
- **AND** no fixed-destination, gateway, or polling hook is present

#### Scenario: Auto reset is disabled

- **WHEN** effective `auto_reset.enabled` resolves to false from env, plugin config, and defaults
- **THEN** `pre_llm_call` returns without network activity or prompt context
- **AND** the footer hook continues to operate normally

### Requirement: Documentation describes footer and opt-in auto-reset behavior

The `README.md` SHALL continue to document the plugin-directory installation path and footer behavior. It SHALL document canonical plugin config under `plugins.entries.hermes-usage-hook.auto_reset`, `hermes config set` examples, optional `CODEX_ENABLE_AUTORESET` and `CODEX_AUTORESET_THRESHOLD` overrides, env → plugin config → defaults precedence, disabled-by-default behavior, weekly remaining-percentage semantics, valid range `0..99`, reload differences, irreversible consumption, earliest-expiry selection, and the audit footer. It SHALL NOT place runtime values in `plugin.yaml` or instruct users to store OAuth tokens in these settings.

#### Scenario: README documents safe opt-in

- **WHEN** `README.md` is read after this change
- **THEN** it states that auto reset is disabled by default
- **AND** enabling it authorizes autonomous reset-credit consumption
- **AND** threshold examples use weekly remaining percentage

### Requirement: Ship a Hermes plugin manifest

The repository SHALL include `plugin/plugin.yaml` with name `hermes-usage-hook`, `kind: standalone`, version, description, author, and a `provides_hooks` list containing exactly `transform_llm_output` and `pre_llm_call` for this feature set.

#### Scenario: Manifest declares both hooks

- **WHEN** `plugin/plugin.yaml` is parsed after this change
- **THEN** `provides_hooks` contains `transform_llm_output` and `pre_llm_call` exactly once each

### Requirement: Expose a register entry point from the plugin root

The plugin root SHALL expose callable `register(ctx)` that registers the footer handler on `transform_llm_output` and the auto-reset preflight handler on `pre_llm_call`. Registration SHALL not perform network or filesystem mutation; runtime handlers enforce configuration and safety policy.

#### Scenario: Register wires both handlers

- **WHEN** a fake plugin context records registration calls
- **THEN** one handler is registered for `transform_llm_output`
- **AND** one handler is registered for `pre_llm_call`
- **AND** registration itself performs no usage or consume request
