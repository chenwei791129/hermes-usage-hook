## Why

`hermes-usage-hook` v0.4.0 only keeps the current auto-reset coordination state and a one-shot footer notice. After the notice is drained, operators cannot reliably answer when a Codex weekly reset occurred. Standard `agent.log` output is mixed with runtime activity and rotated, so it is not a durable reset history.

## What Changes

- Add a profile-scoped append-only JSONL audit at `$HERMES_HOME/logs/hermes-usage-hook-autoreset.jsonl`.
- Record exactly one event for each successful logical reset, whether the terminal backend response is `reset` or an idempotent retry later confirms `already_redeemed`.
- Add a durable outbox to the existing auto-reset state so a process crash or audit-write failure cannot silently lose a successful reset event.
- Deduplicate events with `sha256(redeem_request_id)` while permanently omitting raw request, credit, session, turn, user, and account identifiers.
- Add a native read-only CLI: `hermes usage-hook history`, with `--last`, `--since`, and `--json` filters.
- Keep history permanently with no automatic rotation or deletion.
- Continue using standard Python logging for diagnostic warnings, while keeping the dedicated JSONL as the authoritative success history.

## Non-Goals

- Do not log failed or skipped evaluations (`no_credit`, `nothing_to_reset`, timeout, error, cooldown, disabled, non-Codex, missing weekly, or above threshold).
- Do not add a chat slash command, dashboard, remote exporter, metrics backend, or background polling.
- Do not persist credentials, raw backend payloads, prompts, model responses, or correlatable account/session identifiers.
- Do not import historical resets from old state, footer text, or rotated Gateway/session logs; v0.4.0 has no authoritative source for a complete backfill.
- Do not automatically rotate, truncate, prune, rewrite, or delete audit events.
- Do not call live Codex usage or consume endpoints from the history command or automated tests.

## Capabilities

### Modified Capabilities

- `codex-auto-reset`: successful logical resets gain crash-recoverable, exactly-once local audit persistence and a native history query command.

## Impact

- New code: `plugin/autoreset_audit.py`, `plugin/autoreset_cli.py`.
- Modified code: `plugin/autoreset.py`, `plugin/hooks/footer_hook.py`, `plugin/__init__.py`, `README.md`.
- Tests: `tests/test_autoreset_audit.py`, plus focused updates to `tests/test_autoreset.py` and `tests/test_usage.py`.
- Runtime audit: `$HERMES_HOME/logs/hermes-usage-hook-autoreset.jsonl`, mode `0600` where supported.
- Runtime outbox: optional `audit_outbox` in `$HERMES_HOME/state/hermes-usage-hook/autoreset.json`, protected by the existing coordinator lock.
- No configuration keys, network endpoints, credentials, or auto-reset eligibility rules change.
