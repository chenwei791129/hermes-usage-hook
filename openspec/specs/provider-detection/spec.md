# provider-detection Specification

## Purpose

Detect the usage provider for a reply from the response model name, dispatch to the matched provider's usage fetcher, and render a provider-labeled usage summary for the footer hook.

## Requirements

### Requirement: Detect provider from the response model name

The footer hook SHALL determine the provider for the current reply from the `model` value supplied in the `transform_llm_output` context, using case-insensitive matching. A model name containing `codex`, or starting with `gpt-`, `o1`, `o3`, or `o4`, SHALL map to the Codex provider. A model name containing `minimax` or `abab` SHALL map to the MiniMax provider. When the model name matches no provider, or is missing, the system SHALL NOT fetch any usage and SHALL leave the reply unchanged.

#### Scenario: Codex model is detected

- **WHEN** the footer hook receives a reply whose `model` is `gpt-5-codex`
- **THEN** the system selects the Codex usage fetcher

#### Scenario: MiniMax model is detected

- **WHEN** the footer hook receives a reply whose `model` is `MiniMax-M2.5`
- **THEN** the system selects the MiniMax usage fetcher

#### Scenario: Unknown or missing model leaves the reply unchanged

- **WHEN** the footer hook receives a reply whose `model` matches no known provider or is absent
- **THEN** the system returns no footer and the reply text is unchanged

##### Example: model-to-provider mapping

| model | provider |
| ----- | -------- |
| `gpt-5-codex` | Codex |
| `o3-mini` | Codex |
| `MiniMax-M2.5` | MiniMax |
| `abab6.5s-chat` | MiniMax |
| `claude-opus-4` | none (reply unchanged) |
| (missing) | none (reply unchanged) |

---
### Requirement: Dispatch to the matched provider and normalize usage

The system SHALL expose `get_usage_for_model(model)` that evaluates an ordered registry of providers, returns the normalized usage of the first provider whose matcher accepts the model, and returns `None` when no provider matches. The normalized usage SHALL have the shape `{provider, plan_type, windows}` where `windows` maps window labels (`5h`, optionally `weekly`) to `{used_percent, remaining_percent, reset_in_min}`.

#### Scenario: Matched provider returns normalized usage

- **WHEN** `get_usage_for_model` is called with a model that matches a registered provider
- **THEN** it returns that provider's normalized usage dict including the `provider` field

#### Scenario: No provider matches

- **WHEN** `get_usage_for_model` is called with a model that matches no registered provider
- **THEN** it returns `None`

---
### Requirement: Render a provider-labeled usage summary

The system SHALL provide `format_summary(usage)` that consumes only the normalized usage structure and produces a one-line summary for the `5h` window, prefixed with the provider name. When `plan_type` is present it SHALL append a `| plan <plan_type>` segment; when `plan_type` is absent it SHALL omit that segment. When the `5h` window is unavailable it SHALL return a summary stating the window is unavailable.

#### Scenario: Codex summary includes plan

- **WHEN** `format_summary` receives Codex usage with the `5h` window used 42% and `plan_type` `pro`
- **THEN** it returns `Codex 5h | used 42%, left 58% (resets in 137 min) | plan pro`

##### Example: Codex summary

- **GIVEN** usage `{provider: "Codex", plan_type: "pro", windows: {"5h": {used_percent: 42, remaining_percent: 58, reset_in_min: 137}}}`
- **WHEN** `format_summary` is called
- **THEN** the result is `Codex 5h | used 42%, left 58% (resets in 137 min) | plan pro`

#### Scenario: MiniMax summary omits plan

- **WHEN** `format_summary` receives MiniMax usage with the `5h` window used 4% and no `plan_type`
- **THEN** it returns `MiniMax 5h | used 4%, left 96% (resets in 281 min)`

#### Scenario: Failure never breaks the reply

- **WHEN** provider detection or usage fetching raises an exception during the footer hook
- **THEN** the hook swallows the error, logs it to stderr prefixed `[hermes-usage-hook]`, and returns the reply unchanged
