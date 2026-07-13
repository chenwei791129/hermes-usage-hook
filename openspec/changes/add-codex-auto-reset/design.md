## Context

The plugin already calls `GET https://chatgpt.com/backend-api/wham/usage` and normalizes Codex weekly usage plus `rate_limit_reset_credits.available_count`. OpenAI's Codex client also uses `GET /wham/rate-limit-reset-credits` to list credits and `POST /wham/rate-limit-reset-credits/consume` with `redeem_request_id` and optional `credit_id` to consume one.

A live test on 2026-07-13 returned HTTP 200 with `code: reset`, reset one weekly window from 11% used to 0% used, and reduced credits from 3 to 2. Consumption is irreversible and must be idempotent.

The existing `transform_llm_output` hook runs only after a successful response, so a footer-only design can miss `threshold=0` when the provider rejects the request first. Hermes also exposes `pre_llm_call`, which runs once before the request and includes the model.

## Goals

- Automatically reset only the Codex weekly window after explicit effective plugin configuration.
- Interpret the threshold as weekly remaining percentage.
- Prevent duplicate consumption across dual hooks, concurrent cron/gateway work, retries, timeouts, and restarts.
- Preserve the guarantee that provider/API failures never break a model response.
- Make every successful autonomous consumption visible in the footer and local state.

## Configuration

### Canonical Hermes plugin config

```yaml
plugins:
  entries:
    hermes-usage-hook:
      auto_reset:
        enabled: false
        threshold: 0
```

- `plugins.entries.hermes-usage-hook.auto_reset.enabled`: boolean, default `false`. Setting true is explicit standing authorization for autonomous reset-credit consumption.
- `plugins.entries.hermes-usage-hook.auto_reset.threshold`: integer weekly remaining-percentage threshold, default `0`, valid range `0..99`; eligibility is `remaining_percent <= threshold`.
- Plugin config is loaded with Hermes `load_config()` at hook invocation time, so edits to `config.yaml` can take effect without plugin reinstallation. No values are stored in `plugin.yaml`.
- Hermes has no generic plugin-config schema/UI for standalone hooks; README documents YAML and `hermes config set` commands.

### Environment overrides

- `CODEX_ENABLE_AUTORESET` and `CODEX_AUTORESET_THRESHOLD` are optional operator overrides for containers, CI, and process-managed deployments.
- Resolution precedence is explicit env value → plugin config → defaults (`false`, `0`).
- Boolean env accepts trimmed case-insensitive `1`, `true`, `yes`, `on`, `0`, `false`, `no`, or `off`; any other explicit value is invalid and fails closed.
- Empty, non-integer, negative, or greater-than-99 threshold values are invalid and fail closed.
- `100` is intentionally invalid because a freshly reset window has 100% remaining and would immediately qualify again.
- Process-level env changes require Gateway reload/restart; `config.yaml` is read per invocation.

## Architecture

### `plugin/autoreset.py`

Owns mutation policy and state. It provides testable config parsing, weekly extraction, eligibility, and a `maybe_autoreset(*, model, usage=None, session_id="", turn_id="") -> AutoResetResult` coordinator.

`AutoResetResult` distinguishes `disabled`, `not_codex`, `no_weekly_window`, `above_threshold`, `no_credit`, `nothing_to_reset`, `reset`, `already_redeemed`, `cooldown`, and `error`. It carries non-sensitive before/after percentages and counts when known.

### `plugin/providers/codex_usage.py`

Keeps auth and HTTP provider-local. Add:

- `list_rate_limit_reset_credits() -> dict`
- `consume_rate_limit_reset_credit(redeem_request_id: str, credit_id: str | None) -> dict`

Consume reuses the active Codex credential and existing bounded timeout. Generic automatic POST retries are forbidden because retries must reuse persisted identifiers.

### Hook integration

- Register `pre_llm_call` in addition to `transform_llm_output`.
- Pre-LLM calls the coordinator only when enabled and model maps to Codex; it returns no prompt context.
- Footer passes already-fetched normalized usage into the coordinator, avoiding a redundant initial GET. The coordinator still re-fetches after lock acquisition.
- Successful events become one-shot notices for the matching footer; they are not injected into model prompts.

## Control Flow

1. Return with no network work when disabled.
2. Parse threshold; invalid values log and return without mutation.
3. Return for non-Codex models.
4. Use supplied usage or fetch Codex usage.
5. Require a real `windows.weekly.remaining_percent` and `reset_credits_available > 0`.
6. Require `remaining_percent <= threshold` and no active cooldown.
7. Acquire the cross-process lock atomically.
8. Reload state and live usage inside the lock; re-evaluate all eligibility conditions.
9. Reuse an unresolved pending attempt, or list details, choose the earliest-expiring `available` credit (null expiry last), generate a UUID, and atomically persist pending state before POST.
10. POST consume once for this invocation.
11. Update state, refresh usage/count after success, and release the lock in `finally`.
12. Catch/log every hook exception without suppressing the model response.

## Concurrency and Idempotency

- Atomic lock directory: `$HERMES_HOME/state/hermes-usage-hook/autoreset.lock/`, acquired via `os.mkdir` without a dependency.
- Lock metadata contains PID and acquisition time only. A lock older than 120 seconds may be reclaimed once; reclaim failure stays fail closed.
- State path: `$HERMES_HOME/state/hermes-usage-hook/autoreset.json`, written by temp file plus `os.replace`, with owner-only permissions where supported.
- Pending state contains request UUID, credit ID, timestamps, and status—never credentials.
- Timeout/connection loss after POST keeps pending state. The next invocation reuses the same UUID and credit ID.
- `reset` and `already_redeemed` are successful terminal outcomes. `no_credit` and `nothing_to_reset` are non-success terminal outcomes.

## Cooldown and Loop Prevention

- Threshold maximum 99 prevents immediate reset loops at 100% remaining.
- `nothing_to_reset`, `no_credit`, deterministic validation/auth failures, and unknown deterministic responses set a five-minute cooldown.
- Transient GET failures set a one-minute cooldown.
- Ambiguous POST timeout permits pending-state retry after one minute with the same identifiers.
- Lock-holder rechecks live usage before consume.

## Error Handling

- Disabled, non-Codex, above-threshold, missing-weekly, no-credit, and cooldown are normal no-ops.
- Missing/malformed fields never trigger consume.
- If summary count is positive but details have no usable available row, skip consume and enter cooldown rather than letting the backend select an unspecified credit.
- API/filesystem errors are logged and swallowed by hooks.
- Corrupt state is quarantined with a timestamp; auto reset is disabled for that invocation.

## Security and Privacy

- OAuth credentials stay in Hermes `auth.json` and are never copied into state/logs.
- Effective `auto_reset.enabled=true`—resolved from env override or plugin config—is the explicit opt-in boundary for irreversible consumption.
- Logs may contain outcome, percentages, counts, expiry, request UUID, and HTTP status; never tokens, account/user IDs, or full response bodies.

## User-Visible Behavior

Disabled: footer unchanged. Enabled but above threshold: footer unchanged except existing reset-credit count. After success:

```text
Codex weekly | used 0%, left 100% (...) | plan plus | reset credits 2
Codex auto reset | weekly 0% → 100% | reset credits 3 → 2
```

Failures never claim success and never block the reply.

## Testing Strategy

- Config: default disabled, accepted truthy values, threshold default/bounds, invalid rejection.
- Eligibility: provider, weekly missing, above/equal/below threshold, count missing/zero/positive.
- Selection: earliest expiry, null last, unavailable ignored, detail mismatch fail closed.
- Provider: GET/POST paths, stable payload identifiers, no token leakage.
- Concurrency: two contenders cause one logical consume.
- Idempotency: timeout preserves pending; retry reuses UUID; already-redeemed succeeds.
- Outcomes and cooldowns: reset, nothing-to-reset, no-credit, malformed/error cases.
- Hooks: no disabled-network work, footer reuse, exception safety, exactly one audit line.
- Full existing Codex/MiniMax/installer/script/lint regressions.

## Rollout and Verification

1. Ship disabled by default.
2. Verify hook registration with env unset.
3. Enable a controlled account with plugin config `auto_reset.enabled=true` and `threshold=0`; separately test env override precedence.
4. CI uses mocks and never consumes a real credit.
5. Any live consume requires explicit operator confirmation.
6. Verify reset, decrement, notice, state cleanup, and concurrent deduplication.

## Open Questions

None. Names, remaining-percent semantics, default threshold, dual-hook architecture, earliest-expiry policy, and opt-in authorization are approved.
