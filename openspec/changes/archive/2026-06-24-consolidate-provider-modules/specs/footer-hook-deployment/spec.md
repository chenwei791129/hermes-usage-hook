## MODIFIED Requirements

### Requirement: Distribute only the footer hook

The repository SHALL ship exactly one Hermes hook: the footer hook implemented as a plugin hook on `transform_llm_output`. The repository SHALL NOT include the fixed-destination notification plugin hook (`on_session_end`) nor the gateway hook (`agent:end`). The shared usage module SHALL remain available for the footer hook to import, and the provider implementations it dispatches to SHALL live in the `providers/` Python package rather than as top-level modules in the repository root.

#### Scenario: Footer hook and shared module are present

- **WHEN** the repository is inspected after this change
- **THEN** `hooks/footer_hook.py`, `usage.py`, and `providers/codex_usage.py` exist

#### Scenario: Provider implementations are consolidated under the providers package

- **WHEN** the repository is inspected after this change
- **THEN** `providers/__init__.py`, `providers/codex_usage.py`, and `providers/minimax_usage.py` exist, and the root-level `codex_usage.py` and `minimax_usage.py` do not exist

#### Scenario: Fixed-destination and gateway hooks are removed

- **WHEN** the repository is inspected after this change
- **THEN** `hooks/plugin_hook.py`, `hooks/gateway/handler.py`, and `hooks/gateway/HOOK.yaml` do not exist, and the `hooks/gateway/` directory is absent
