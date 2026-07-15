## Context

Release v0.4.0 records only the current coordinator state and one-shot footer notices. A successful reset leaves `cooldown_reason=success`, but the timestamp can only be inferred while that state remains unchanged and older successes are lost. Hermes' official plugin documentation routes standard Python logging to profile-scoped `agent.log`, and the Hooks guide demonstrates dedicated JSONL audit files under `$HERMES_HOME/logs/`. Hermes also requires profile-safe storage via `get_hermes_home()` rather than a hardcoded `~/.hermes` path.

The consume call is irreversible. Audit persistence therefore cannot be treated as a best-effort `logger.info()` after clearing pending state: a crash in that gap would permanently lose the only durable record of a successful logical reset.

## Goals

- Preserve one valid audit event per successful logical reset across crashes, retries, dual hooks, and multiple Hermes processes.
- Keep reset delivery fail-safe: audit problems never suppress or replace the model response.
- Keep the history local, profile-scoped, privacy-minimized, script-readable, and queryable without network access.
- Reuse the v0.4.0 coordinator lock and idempotency model instead of introducing an independent reset workflow.

## Architecture

### `plugin/autoreset_audit.py`

Own audit schema, path resolution, append/dedup, parsing, and read filtering. The primary interfaces are:

```python
AUDIT_SCHEMA_VERSION = 1
AUDIT_EVENT_TYPE = "codex_autoreset_succeeded"


def audit_event_id(redeem_request_id: str) -> str:
    """Return `sha256:<lowercase hex>` without retaining the raw UUID."""


def build_success_event(
    *,
    redeem_request_id: str,
    observed_at: float,
    backend_status: str,
    trigger: str,
    before_remaining: int | float | None,
    after_remaining: int | float | None,
    before_credits: int | None,
    after_credits: int | None,
) -> dict:
    """Build and validate the schema-v1 event."""


class AutoResetAuditLog:
    def __init__(self, *, home: Path | None = None) -> None: ...
    def append_once(self, event: dict) -> bool: ...
    def read_events(self) -> tuple[list[dict], int]: ...
```

Default path:

```python
get_hermes_home() / "logs" / "hermes-usage-hook-autoreset.jsonl"
```

The module lazily imports `get_hermes_home()` so standalone unit tests remain independent of Hermes; tests inject `home=tmp_path`.

### `plugin/autoreset.py`

The existing coordinator remains the sole owner of consume ordering and the existing cross-process lock. Add optional `trigger="unknown"` and injectable `audit_log` parameters to `maybe_autoreset()` without breaking existing callers.

State remains additive and backward-compatible at `version: 1`. `_clean_state()` accepts at most one validated `audit_outbox` event; missing outbox in v0.4.0 state means no pending audit.

### `plugin/autoreset_cli.py`

Registers the `hermes usage-hook history` argparse tree and renders only local history. It never loads Codex auth and never calls usage, credit-list, or consume transports.

```python
def register_cli(parser: argparse.ArgumentParser) -> None: ...
def usage_hook_command(args: argparse.Namespace) -> int: ...
```

`plugin/hooks/footer_hook.py::register(ctx)` registers both lifecycle hooks and the CLI command through:

```python
ctx.register_cli_command(
    name="usage-hook",
    help="Inspect hermes-usage-hook state and audit history",
    setup_fn=register_cli,
    handler_fn=usage_hook_command,
)
```

The first release adds only the `history` subcommand.

The history handler imports and acquires `plugin.autoreset.acquire_autoreset_lock()` before reading. Lock contention returns exit 1 with a concise stderr message; it never performs an unlocked read or waits indefinitely.

## Event Schema

Each valid line is a compact UTF-8 JSON object:

```json
{
  "schema_version": 1,
  "event_type": "codex_autoreset_succeeded",
  "event_id": "sha256:<64 lowercase hex chars>",
  "observed_at": "2026-07-13T16:25:55.815223Z",
  "backend_status": "reset",
  "trigger": "pre_llm_call",
  "before": {
    "weekly_remaining_percent": 0,
    "reset_credits": 3
  },
  "after": {
    "weekly_remaining_percent": 100,
    "reset_credits": 2
  }
}
```

Rules:

- `backend_status` is exactly `reset` or `already_redeemed`.
- `trigger` is `pre_llm_call`, `transform_llm_output`, or `unknown` for backward-compatible direct callers.
- `observed_at` is RFC 3339 UTC with `Z`. It is observation/confirmation time, not an invented backend execution timestamp.
- Remaining percentages and credit counts are numbers/integers or `null`. Refresh failure keeps the event and writes unknown `after` values as `null`.
- Raw redeem request IDs are hashed immediately and never included in event/outbox logs. Raw credit, session, turn, user, account, model, prompt, and response data are absent.

## Durable Outbox Flow

All steps below run while holding the existing `$HERMES_HOME/state/hermes-usage-hook/autoreset.lock/` coordinator lock.

1. Load and sanitize state.
2. Before eligibility/network work, attempt to drain an existing `audit_outbox`.
3. `append_once()` scans valid events for the same `event_id`. If present, it reports success without appending.
4. If an old file lacks a trailing newline, append only a newline delimiter before the next valid event; do not rewrite or delete the malformed fragment.
5. Append one compact JSON line using `os.open(..., O_APPEND|O_CREAT|O_WRONLY, 0o600)`, complete short writes, `fsync`, and enforce `0600` where supported.
6. After append/dedup succeeds, clear `audit_outbox` with the existing atomic state writer.
7. If drain fails, preserve the outbox, log a warning through `logging`, perform no new consume attempt, and return a non-throwing coordinator result.
8. On a new `reset` or `already_redeemed` result, build the audit event and place it in `audit_outbox` in the same atomic state write that clears pending, sets the success cooldown, and stores the one-shot footer notice.
9. Immediately attempt the same drain sequence. Audit failure does not revoke the successful result or block the current model response; future hooks retry before any new consume.

Crash properties:

- Crash before terminal state write: prior pending consume IDs remain; retry reuses them.
- Crash after terminal state/outbox write but before append: next hook appends the outbox.
- Crash after append but before clearing outbox: next hook detects `event_id` and clears without duplication.
- Audit filesystem failure: outbox remains and prevents a later reset from overwriting the unresolved event.

Only one outbox event is needed because no new consume may proceed while it is unresolved.

## File Integrity and Concurrency

- Audit append and CLI reads both acquire the existing coordinator lock, so no additional lock order or deadlock surface is introduced.
- The audit file is append-only: implementation never truncates, rewrites, rotates, or deletes it.
- Each event is encoded to one bounded line before opening the file.
- A partial/malformed line is skipped by readers with a diagnostic warning; later valid events remain readable.
- `read_events()` returns `(valid_events, malformed_count)` and never exposes malformed raw content.
- Parent directory creation is profile-scoped. Audit file permissions are `0600` where POSIX permissions exist.
- No automatic retention or rotation is implemented. Expected event volume is very low.

## CLI Behavior

Commands:

```text
hermes usage-hook history
hermes usage-hook history --last 20
hermes usage-hook history --since 30d
hermes usage-hook history --json
```

Rules:

- Default is the latest 20 valid events, oldest-to-newest within the selected window.
- `--last N` requires a positive integer.
- `--since` accepts a positive integer plus `s`, `m`, `h`, or `d`; filtering compares `observed_at` in UTC.
- `--since` filters first; `--last` then limits the filtered result.
- Human output converts `observed_at` to the host's local timezone and renders unknown values as `?`.
- `--json` emits selected compact JSONL events unchanged in UTC, one object per line.
- Missing/empty file prints `No Codex auto-reset history found.` in human mode, emits no lines in JSON mode, and exits 0.
- Malformed lines are skipped. Human mode prints a concise stderr warning with only the count; JSON stdout remains machine-clean.
- Invalid CLI arguments exit 2 through argparse. Unreadable filesystem errors print a non-sensitive stderr message and exit 1.
- Coordinator lock contention prints a non-sensitive stderr message and exits 1 without reading a potentially in-progress append.

## Error Handling

- Logging or query failures never trigger network calls and never break a model response.
- Diagnostics use `logging.getLogger(__name__)`, which Hermes routes to profile-scoped `agent.log`/`errors.log`.
- Diagnostics may include status, file path, malformed count, and event-id prefix; never raw event fragments, request IDs, credentials, account/session IDs, or backend bodies.
- A successful consume remains user-visible through the existing one-shot footer even when audit drain is deferred.

## Backward Compatibility and Rollout

- Existing v0.4.0 state with no `audit_outbox` loads unchanged.
- Existing `autoreset-notices.json`, cooldown, pending consume, lock, and footer semantics remain unchanged.
- No historical backfill is attempted because prior events cannot be reconstructed authoritatively.
- No new config is required; history is always recorded for successful logical resets when auto-reset itself is enabled and succeeds.
- Automated tests use injected temporary homes and mocked transports. No test or smoke check consumes a live reset credit.
- Installation and Gateway restart follow the official external plugin lifecycle; implementation work must not modify Hermes core or bypass restart guards.

## Testing Strategy

- Schema/privacy: exact keys, hashed event ID, UTC time, nullable after fields, forbidden identifiers absent.
- Append: first append, duplicate no-op, mode `0600`, newline recovery, partial writes, fsync, no rewrite/truncate.
- Parsing: valid events, malformed lines, unknown schema/event ignored with count, stable order.
- Outbox: atomic terminal state includes event; drain before network; append failure preserves outbox; crash-after-append dedups and clears; unresolved outbox prevents consume.
- Hooks: exact trigger propagation and existing notice behavior.
- CLI: registration, defaults, `--last`, `--since`, combined filters, local-time human output, JSONL output, empty file, malformed warning, filesystem error.
- Regression: full pytest, Ruff, ty, compileall, diff-check, installer tests, plugin import/discovery with no live Codex calls.

## Open Questions

None. Event scope, durable outbox, identifier hashing, permanent retention, native CLI, schema, official log root, and profile-safe path resolution are approved.
