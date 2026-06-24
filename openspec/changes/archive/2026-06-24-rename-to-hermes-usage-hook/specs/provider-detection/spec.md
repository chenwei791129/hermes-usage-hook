## MODIFIED Requirements

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
