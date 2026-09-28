## MODIFIED Requirements

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
