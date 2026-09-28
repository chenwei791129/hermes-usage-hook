# provider-detection Specification

## Purpose

Detect the usage provider for a reply from the response model name, dispatch to the matched provider's usage fetcher, and render a provider-labeled usage summary for the footer hook.

## Requirements

### Requirement: Detect provider from the response model name

The footer hook SHALL determine the provider for the current reply from the `model` value supplied in the `transform_llm_output` context, using case-insensitive matching. A model name containing `codex`, or starting with `gpt-`, `o1`, `o3`, or `o4`, SHALL map to the Codex provider. A model name containing `minimax` or `abab` SHALL map to the MiniMax provider. When the model name matches no provider, or is missing, the system SHALL NOT fetch any usage and SHALL leave the reply unchanged, except that when the footer model display is enabled and a model line would be rendered, the reply SHALL carry a model-only footer as defined by the `footer-model-display` capability.

#### Scenario: Codex model is detected

- **WHEN** the footer hook receives a reply whose `model` is `gpt-5-codex`
- **THEN** the system selects the Codex usage fetcher

#### Scenario: MiniMax model is detected

- **WHEN** the footer hook receives a reply whose `model` is `MiniMax-M2.5`
- **THEN** the system selects the MiniMax usage fetcher

#### Scenario: Unknown or missing model leaves the reply unchanged

- **WHEN** the footer model display is disabled and the footer hook receives a reply whose `model` matches no known provider or is absent
- **THEN** the system returns no footer and the reply text is unchanged

#### Scenario: Unknown model with the footer model display enabled

- **WHEN** the footer model display is enabled and the footer hook receives a reply whose `model` is a non-blank string that matches no known provider
- **THEN** the system fetches no usage and appends a footer containing only the model line

##### Example: model-to-provider mapping

| model | provider |
| ----- | -------- |
| `gpt-5-codex` | Codex |
| `o3-mini` | Codex |
| `MiniMax-M2.5` | MiniMax |
| `abab6.5s-chat` | MiniMax |
| `claude-opus-4` | none (reply unchanged unless the model display is enabled) |
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

The system SHALL provide `format_summary(usage)` that consumes only the normalized usage structure and produces a multi-line summary, one line per available window, each line prefixed with the provider name and the window label.

The `5h` window SHALL render as the first line. When a `weekly` window is present in `windows`, it SHALL render as a second line. When the `weekly` window is absent, only the `5h` line SHALL render. When the `5h` window is unavailable, the system SHALL return `<provider> usage: 5h window unavailable` and SHALL NOT render a `weekly` line.

When `plan_type` is present it SHALL append a `| plan <plan_type>` segment to the `5h` line only; when `plan_type` is absent it SHALL omit that segment. The `weekly` line SHALL NOT carry a plan segment.

Each window line SHALL report `used <used_percent>%, left <remaining_percent>%`. When the window's `reset_in_min` is present, the line SHALL append ` (resets in <duration>)` where `<duration>` is produced by a single shared duration formatter applied identically to every window; when `reset_in_min` is absent the line SHALL omit the resets clause.

The shared duration formatter SHALL convert a whole-minute count to a compact human-readable string by these rules, applied to both the `5h` and `weekly` windows:

- Fewer than 60 minutes SHALL render as `<m>m` (e.g. `45m`); zero minutes SHALL render as `0m`.
- 60 minutes up to but excluding 1440 minutes SHALL render as `<h>h<m>m` (e.g. `2h17m`).
- 1440 minutes or more SHALL render as `<d>d<h>h` (e.g. `6d4h`); when the residual hours are zero the hours segment SHALL be omitted, rendering as `<d>d` (e.g. `6d`).

#### Scenario: Codex summary renders 5h and weekly with plan on the 5h line

- **WHEN** `format_summary` receives Codex usage with a `5h` window used 42% (resets in 137 min), a `weekly` window used 10% (resets in 8880 min), and `plan_type` `pro`
- **THEN** it returns two lines: `Codex 5h | used 42%, left 58% (resets in 2h17m) | plan pro` followed by `Codex weekly | used 10%, left 90% (resets in 6d4h)`

##### Example: Codex two-line summary

- **GIVEN** usage `{provider: "Codex", plan_type: "pro", windows: {"5h": {used_percent: 42, remaining_percent: 58, reset_in_min: 137}, "weekly": {used_percent: 10, remaining_percent: 90, reset_in_min: 8880}}}`
- **WHEN** `format_summary` is called
- **THEN** the result is the two lines `Codex 5h | used 42%, left 58% (resets in 2h17m) | plan pro` and `Codex weekly | used 10%, left 90% (resets in 6d4h)` joined by a newline

#### Scenario: MiniMax summary omits plan on both lines

- **WHEN** `format_summary` receives MiniMax usage with a `5h` window used 4% (resets in 281 min), a `weekly` window used 30% (resets in 8640 min), and no `plan_type`
- **THEN** it returns `MiniMax 5h | used 4%, left 96% (resets in 4h41m)` followed by `MiniMax weekly | used 30%, left 70% (resets in 6d)`

#### Scenario: Weekly window absent renders only the 5h line

- **WHEN** `format_summary` receives usage whose `windows` contains a `5h` window but no `weekly` window
- **THEN** it returns a single line for the `5h` window and no `weekly` line

#### Scenario: 5h window unavailable

- **WHEN** `format_summary` receives usage whose `windows` contains no `5h` window
- **THEN** it returns `<provider> usage: 5h window unavailable` and renders no `weekly` line

#### Scenario: Sub-hour reset renders minutes only

- **WHEN** the shared duration formatter receives a window whose `reset_in_min` is 90
- **THEN** the rendered duration is `1h30m`

##### Example: duration formatter mapping

| reset_in_min | duration |
| ------------ | -------- |
| 0 | `0m` |
| 45 | `45m` |
| 90 | `1h30m` |
| 137 | `2h17m` |
| 8640 | `6d` |
| 8880 | `6d4h` |
