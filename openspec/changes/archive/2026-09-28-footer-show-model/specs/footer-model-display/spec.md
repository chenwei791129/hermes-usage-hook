## Purpose

Define an optional footer line that shows the model serving the current Hermes session. The line is disabled by default and is enabled through the plugin's own entry in the Hermes config, so operators can confirm which model answered a reply without changing the existing usage footer for anyone who does not opt in.

## ADDED Requirements

### Requirement: Model display is configured through the plugin entry and disabled by default

The plugin SHALL read the model display setting from `plugins.entries.hermes-usage-hook.footer.show_model` in the Hermes config, loaded through the host `hermes_cli.config.load_config()` on every `transform_llm_output` call. The effective setting SHALL be enabled only when that value is the YAML boolean `true`. The effective setting SHALL be disabled when any of the following holds: the host config module cannot be imported, `load_config()` raises, or any of `plugins`, `plugins.entries`, the `hermes-usage-hook` entry, `footer`, or `show_model` is absent or `null`. A `null` value SHALL be treated exactly as absent, so `hermes config set plugins.entries.hermes-usage-hook.footer.show_model null` clears the setting without a warning. The plugin SHALL NOT read this setting from any environment variable and SHALL NOT declare it in `plugin/plugin.yaml`.

When `plugins`, `plugins.entries`, the `hermes-usage-hook` entry, or `footer` is present, not `null`, and not a mapping, or `show_model` is present, not `null`, and not a boolean, the effective setting SHALL be disabled and the plugin SHALL write exactly one line prefixed `[hermes-usage-hook]` to stderr for that call naming the offending key. The same warning SHALL be written when `load_config()` raises. An invalid or unreadable setting SHALL NOT change the usage lines, the auto-reset notice, or the reply text.

#### Scenario: Setting absent

- **WHEN** the Hermes config has no `plugins.entries.hermes-usage-hook.footer.show_model` key
- **THEN** the effective model display setting is disabled and no warning is written

#### Scenario: Enabled via hermes config set

- **WHEN** the operator has run `hermes config set plugins.entries.hermes-usage-hook.footer.show_model true`, so the stored value is the YAML boolean `true`
- **THEN** the effective model display setting is enabled on the next `transform_llm_output` call without reinstalling the plugin or restarting Hermes

#### Scenario: Non-boolean value fails closed with a warning

- **WHEN** `show_model` is present with a non-null, non-boolean value
- **THEN** the effective setting is disabled and exactly one `[hermes-usage-hook]` stderr line naming `footer.show_model` is written for that call

##### Example: value resolution

| Stored `show_model` value | Effective setting | Warning |
| ------------------------- | ----------------- | ------- |
| absent | disabled | no |
| `true` (boolean) | enabled | no |
| `false` (boolean) | disabled | no |
| `"true"` (quoted string) | disabled | yes |
| `1` (integer) | disabled | yes |
| `null` | disabled | no |

#### Scenario: Malformed parent structure fails closed with a warning

- **WHEN** `plugins.entries.hermes-usage-hook.footer` is present but is a string rather than a mapping
- **THEN** the effective setting is disabled, exactly one `[hermes-usage-hook]` stderr line naming the `footer` key is written, and the usage footer renders exactly as it does when the setting is absent

#### Scenario: Config load failure fails closed

- **WHEN** the host `load_config()` raises an exception during a `transform_llm_output` call
- **THEN** the effective setting is disabled, one `[hermes-usage-hook]` stderr line is written, and the reply is still delivered with its usage footer when usage is available

### Requirement: Enabled model display renders a model line above the usage lines

When the effective setting is enabled and the `model` keyword passed to `transform_llm_output` is a string that is non-empty after stripping surrounding whitespace, the footer body below the `───` separator SHALL begin with the line `Model <model>`, where `<model>` is that stripped string rendered verbatim. The usage summary lines SHALL follow the model line, and the one-shot auto-reset notice, when present, SHALL follow the usage lines. When the `model` keyword is absent, not a string, or blank after stripping, no model line SHALL be rendered.

When the effective setting is disabled, the footer SHALL be byte-for-byte identical to the footer produced without this capability.

Intentional-silence marker replies SHALL be returned unchanged regardless of the setting, and an empty `response_text` SHALL yield no change regardless of the setting.

#### Scenario: Enabled with Codex usage

- **WHEN** the setting is enabled, the model is `gpt-5.5-codex`, and Codex usage is available
- **THEN** the footer body is `Model gpt-5.5-codex` followed by the Codex usage lines

##### Example: enabled Codex footer

- **GIVEN** reply text `Done.`, model `gpt-5.5-codex`, and Codex usage whose summary is `Codex 5h | used 42%, left 58% (resets in 2h17m) | plan pro` and `Codex weekly | used 10%, left 90% (resets in 6d4h)`
- **WHEN** `transform_llm_output` runs with the setting enabled
- **THEN** the returned text is `Done.`, a blank line, `───`, `Model gpt-5.5-codex`, `Codex 5h | used 42%, left 58% (resets in 2h17m) | plan pro`, `Codex weekly | used 10%, left 90% (resets in 6d4h)`, joined by newlines

#### Scenario: Enabled with an auto-reset notice

- **WHEN** the setting is enabled and the footer carries a one-shot auto-reset notice
- **THEN** the footer body order is the model line, then the usage lines, then the notice line

#### Scenario: Disabled leaves the footer unchanged

- **WHEN** the setting is disabled and Codex usage is available
- **THEN** the footer body contains only the usage lines (and any notice) and no line starting with `Model `

#### Scenario: Blank or missing model renders no model line

- **WHEN** the setting is enabled and the `model` keyword is absent, `None`, or `"   "`
- **THEN** no model line is rendered and the footer is otherwise unchanged

#### Scenario: Silence marker is untouched

- **WHEN** the setting is enabled and the reply text is `[SILENT]`
- **THEN** the hook returns `[SILENT]` unchanged and fetches no usage

### Requirement: Enabled model display still reports the model without usage

When the effective setting is enabled and a model line would be rendered, the footer SHALL still be appended containing only the model line when no usage is available. No usage is available when the model matches no registered provider, or when the matched provider's usage fetch raises. A usage fetch failure SHALL still write the existing `[hermes-usage-hook] skipped:` stderr diagnostic. No auto-reset notice SHALL be rendered in a model-only footer.

When the effective setting is disabled, or no model line would be rendered, and no usage is available, the hook SHALL return `None` and leave the reply unchanged, as it does without this capability.

#### Scenario: Unrecognized model with the setting enabled

- **WHEN** the setting is enabled and the model is `some-other-model`, which matches no registered provider
- **THEN** the returned text is the reply followed by a blank line, `───`, and `Model some-other-model`

#### Scenario: Usage fetch failure with the setting enabled

- **WHEN** the setting is enabled, the model is `gpt-5.5-codex`, and the Codex usage fetch raises
- **THEN** a `[hermes-usage-hook] skipped:` line is written to stderr and the returned text is the reply followed by a blank line, `───`, and `Model gpt-5.5-codex`

#### Scenario: Unrecognized model with the setting disabled

- **WHEN** the setting is disabled and the model matches no registered provider
- **THEN** the hook returns `None`
