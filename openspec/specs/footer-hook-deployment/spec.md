# footer-hook-deployment Specification

## Purpose

Define what the repository ships and documents for deploying Hermes usage reporting: a single footer hook on `transform_llm_output` backed by the shared usage module, with documentation describing that footer hook as the sole deployment path.

## Requirements

### Requirement: Distribute only the footer hook

The repository SHALL ship exactly one Hermes hook: the footer hook implemented as a plugin hook on `transform_llm_output`. The repository SHALL NOT include the fixed-destination notification plugin hook (`on_session_end`) nor the gateway hook (`agent:end`). The shared usage module SHALL remain available for the footer hook to import.

#### Scenario: Footer hook and shared module are present

- **WHEN** the repository is inspected after this change
- **THEN** `hooks/footer_hook.py` and `codex_usage.py` exist

#### Scenario: Fixed-destination and gateway hooks are removed

- **WHEN** the repository is inspected after this change
- **THEN** `hooks/plugin_hook.py`, `hooks/gateway/handler.py`, and `hooks/gateway/HOOK.yaml` do not exist, and the `hooks/gateway/` directory is absent

---
### Requirement: Documentation describes only the footer hook path

The `README.md` SHALL document the footer hook as the sole deployment path. It SHALL NOT contain the fixed-destination notification deployment section, the gateway hook deployment section, the `CODEX_USAGE_NOTIFIER` configuration table, or the webhook configuration example.

#### Scenario: README contains only footer deployment guidance

- **WHEN** `README.md` is read after this change
- **THEN** it describes deploying the footer hook and contains no references to `CODEX_USAGE_NOTIFIER`, the `on_session_end` fixed-destination notifier, or the gateway `agent:end` hook deployment
