# Codex Auto-Reset Append-Only Audit Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use Hermes subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add crash-recoverable, exactly-once, profile-scoped JSONL history for successful Codex auto-resets plus a native offline history CLI.

**Architecture:** A focused `autoreset_audit.py` owns schema, append/dedup, parsing, and filtering. The existing `autoreset.py` coordinator atomically persists a single durable outbox event with terminal success and drains it under its existing cross-process lock. `autoreset_cli.py` registers a read-only `hermes usage-hook history` command.

**Tech Stack:** Python 3.10+, stdlib (`argparse`, `datetime`, `hashlib`, `json`, `logging`, `os`, `pathlib`), Hermes `get_hermes_home()` and plugin CLI registration, pytest, Ruff, ty.

## Global Constraints

- Baseline is release tag `v0.4.0` commit `d94f7832a468904ef1cb1a5eed0627ff18c7062e`.
- Automated tests and smoke checks MUST NOT call live Codex usage, credit-list, or consume endpoints.
- Audit path is exactly `$HERMES_HOME/logs/hermes-usage-hook-autoreset.jsonl`.
- Record only successful logical resets; never record skipped, failed, or non-success outcomes.
- Never persist raw redeem request, credit, session, turn, user, account, model, prompt, response, credential, or backend-body data.
- History is append-only and permanent: no truncate, rewrite, rotation, pruning, or deletion.
- Audit problems never suppress or replace a model response.
- Do not modify Hermes core, installed site-packages, Gateway launchd configuration, or bypass restart guards.

**Approved specs:**
- `openspec/changes/add-autoreset-audit-log/proposal.md`
- `openspec/changes/add-autoreset-audit-log/design.md`
- `openspec/changes/add-autoreset-audit-log/specs/codex-auto-reset/spec.md`

---

### Task 1: Add the profile-scoped audit schema and append-only store

**Files:**
- Create: `plugin/autoreset_audit.py`
- Create: `tests/test_autoreset_audit.py`

**Interfaces:**
- Produces: `audit_event_id(str) -> str`
- Produces: `build_success_event(*, redeem_request_id: str, observed_at: float, backend_status: str, trigger: str, before_remaining: int | float | None, after_remaining: int | float | None, before_credits: int | None, after_credits: int | None) -> dict`
- Produces: `AutoResetAuditLog(home: Path | None = None)`
- Produces: `AutoResetAuditLog.append_once(event: dict) -> bool`
- Produces: `AutoResetAuditLog.read_events() -> tuple[list[dict], int]`
- Consumes: active Hermes home only through a lazy `hermes_constants.get_hermes_home` import when `home` is not injected.

- [ ] **Step 1: Write failing schema/privacy tests.**

Add tests that call:

```python
event = build_success_event(
    redeem_request_id="request-uuid",
    observed_at=1_721_000_000.125,
    backend_status="reset",
    trigger="pre_llm_call",
    before_remaining=0,
    after_remaining=100,
    before_credits=3,
    after_credits=2,
)
```

Assert exact top-level keys and values, `event_id == "sha256:" + hashlib.sha256(b"request-uuid").hexdigest()`, RFC 3339 UTC `observed_at`, exact nested keys, and absence of every raw identifier. Add parametrized rejection tests for unsupported backend status, trigger, bool-as-number, negative credits, non-finite percentages, and malformed event IDs. Add a refresh-unavailable test asserting nullable `after` fields.

- [ ] **Step 2: Run schema tests and verify RED.**

Run:

```bash
uv run pytest tests/test_autoreset_audit.py -k "event or schema or privacy" -v
```

Expected: collection/import failure because `plugin.autoreset_audit` does not exist.

- [ ] **Step 3: Implement schema construction and validation.**

Create constants and signatures:

```python
AUDIT_SCHEMA_VERSION = 1
AUDIT_EVENT_TYPE = "codex_autoreset_succeeded"
AUDIT_FILENAME = "hermes-usage-hook-autoreset.jsonl"
_ALLOWED_STATUSES = frozenset({"reset", "already_redeemed"})
_ALLOWED_TRIGGERS = frozenset({"pre_llm_call", "transform_llm_output", "unknown"})


def audit_event_id(redeem_request_id: str) -> str:
    if not isinstance(redeem_request_id, str) or not redeem_request_id:
        raise ValueError("redeem request id must be a non-empty string")
    return "sha256:" + hashlib.sha256(redeem_request_id.encode("utf-8")).hexdigest()
```

Use `datetime.fromtimestamp(observed_at, timezone.utc).isoformat().replace("+00:00", "Z")`. Keep schema output to approved keys only; do not pass arbitrary dictionaries through.

- [ ] **Step 4: Write failing append/dedup/integrity tests.**

Create tests named `test_first_append_writes_one_compact_json_line_and_fsyncs`,
`test_duplicate_event_id_is_a_noop`, `test_audit_file_mode_is_owner_only`,
`test_append_completes_short_os_writes`,
`test_partial_trailing_line_gets_only_newline_then_valid_event`,
`test_append_never_calls_replace_truncate_unlink_or_rename`,
`test_read_events_returns_valid_events_and_malformed_count`,
`test_reader_skips_unknown_schema_and_event_type`,
`test_reader_never_returns_or_logs_malformed_raw_content`, and
`test_default_path_uses_injected_profile_home_logs_directory`.

Patch `os.open`, `os.write`, `os.fsync`, and destructive filesystem methods narrowly. Verify duplicate detection parses valid supported events only.

- [ ] **Step 5: Run storage tests and verify RED.**

```bash
uv run pytest tests/test_autoreset_audit.py -k "append or duplicate or partial or mode or read" -v
```

Expected: failures because `AutoResetAuditLog` is not implemented.

- [ ] **Step 6: Implement minimal append-only store.**

Implement:

```python
class AutoResetAuditLog:
    def __init__(self, *, home: Path | None = None) -> None:
        self.home = Path(home) if home is not None else _hermes_home()
        self.path = self.home / "logs" / AUDIT_FILENAME

    def append_once(self, event: dict) -> bool:
        normalized = validate_event(event)
        events, _ = self.read_events()
        if any(item["event_id"] == normalized["event_id"] for item in events):
            return False
        # mkdir, detect missing trailing newline, O_APPEND one bounded line,
        # complete short writes, fsync, chmod 0600; never rewrite prior bytes.
        return True

    def read_events(self) -> tuple[list[dict], int]:
        if not self.path.exists():
            return [], 0
        valid: list[dict] = []
        malformed = 0
        for raw_line in self.path.read_bytes().splitlines():
            try:
                candidate = validate_event(json.loads(raw_line))
            except (TypeError, ValueError, json.JSONDecodeError):
                malformed += 1
                continue
            valid.append(candidate)
        return valid, malformed
```

Use a helper that loops until the complete encoded buffer is written. File creation and subsequent chmod must be owner-only where supported. Do not use `RotatingFileHandler` or Python text append mode.

- [ ] **Step 7: Verify Task 1 and commit.**

```bash
uv run pytest tests/test_autoreset_audit.py -v
uv run ruff check plugin/autoreset_audit.py tests/test_autoreset_audit.py
uv run ty check
git add plugin/autoreset_audit.py tests/test_autoreset_audit.py
git commit -m "feat: add append-only auto-reset audit store"
```

Expected: focused tests and static checks pass.

---

### Task 2: Integrate the durable audit outbox into the reset coordinator

**Files:**
- Modify: `plugin/autoreset.py`
- Modify: `tests/test_autoreset.py`
- Test: `tests/test_autoreset_audit.py`

**Interfaces:**
- Consumes: `AutoResetAuditLog.append_once(event) -> bool`
- Consumes: `build_success_event` with the exact Task 1 keyword arguments and `dict` return
- Produces: optional validated `state["audit_outbox"]`
- Modifies: `maybe_autoreset` by adding `trigger: str = "unknown"` and `audit_log: Any = None`

- [ ] **Step 1: Write failing state sanitization tests.**

Add tests named `test_v040_state_without_audit_outbox_loads_unchanged`,
`test_valid_audit_outbox_round_trips_without_raw_ids`,
`test_invalid_audit_outbox_is_removed_fail_closed`, and
`test_state_write_filters_extra_outbox_keys`, with the assertions in the next
paragraph.

Use a valid event from `build_success_event`; assert `STATE_VERSION` remains `1` and old cooldown/pending/notice behavior is unchanged.

- [ ] **Step 2: Run state tests and verify RED.**

```bash
uv run pytest tests/test_autoreset.py -k audit_outbox -v
```

Expected: assertions fail because `_clean_state()` drops the outbox.

- [ ] **Step 3: Add additive state support and a drain helper.**

Add validated optional `audit_outbox` handling to `_clean_state()`. Add a helper with this contract:

```python
def _drain_audit_outbox(*, state: dict, store: AutoResetStateStore, audit_log: Any) -> bool:
    event = state.get("audit_outbox")
    if event is None:
        return True
    audit_log.append_once(event)
    state["audit_outbox"] = None
    store.write(state)
    return True
```

Catch failures at the coordinator boundary, preserve the outbox, and log only a non-sensitive warning. Do not log the event object.

- [ ] **Step 4: Write failing crash-window tests.**

Create tests named
`test_success_terminal_write_contains_outbox_notice_cooldown_and_no_pending`,
`test_outbox_is_appended_then_cleared_after_success`,
`test_append_failure_preserves_outbox_and_still_returns_reset`,
`test_crash_after_append_before_clear_dedups_then_clears`,
`test_existing_outbox_drains_before_any_usage_or_credit_network_call`,
`test_unresolved_outbox_prevents_new_consume`,
`test_already_redeemed_uses_same_hashed_event_id`, and
`test_non_success_outcomes_never_build_or_append_audit_event`.

Use fake store/audit objects that record operation order. Assert the successful atomic state write occurs before append and includes footer notice plus cooldown. Simulate the clear write failure and verify the next invocation deduplicates.

- [ ] **Step 5: Run coordinator tests and verify RED.**

```bash
uv run pytest tests/test_autoreset.py -k "audit or outbox" -v
```

Expected: failures because terminal transitions do not create or drain outbox events.

- [ ] **Step 6: Implement terminal outbox ordering.**

Update `maybe_autoreset` signature:

```python
def maybe_autoreset(
    *,
    model: str | None,
    usage: dict | None = None,
    session_id: str = "",
    turn_id: str = "",
    trigger: str = "unknown",
    audit_log: Any = None,
    config: AutoResetConfig | None = None,
    store: Any = None,
    usage_fetcher: Callable[[], dict] | None = None,
    credit_lister: Callable[[], dict] | None = None,
    consumer: Callable[[str, str | None], dict | None] | None = None,
    uuid_factory: Callable[[], object] | None = None,
    lock_factory: Callable[[], AbstractContextManager[bool]] | None = None,
    clock: Callable[[], float] = time.time,
) -> AutoResetResult:
```

After acquiring the existing coordinator lock and loading state, drain existing outbox before any live usage fetch. If drain fails, return a non-throwing `AutoResetResult("error", message="auto-reset audit is pending")` and make no network call.

For `reset`/`already_redeemed`, create the event from the persisted pending `redeem_request_id`, current injected clock, trigger, and known before/after values. Put `audit_outbox`, `pending=None`, success cooldown, and fallback notice in the same existing atomic state write. Then drain. If drain fails, retain success return and notice while preserving outbox for a future hook.

- [ ] **Step 7: Verify Task 2 and commit.**

```bash
uv run pytest tests/test_autoreset.py tests/test_autoreset_audit.py -v
uv run ruff check plugin/autoreset.py tests/test_autoreset.py
uv run ty check
git add plugin/autoreset.py tests/test_autoreset.py tests/test_autoreset_audit.py
git commit -m "feat: durably queue auto-reset audit events"
```

---

### Task 3: Propagate exact hook trigger and preserve hook safety

**Files:**
- Modify: `plugin/hooks/footer_hook.py`
- Modify: `tests/test_usage.py`

**Interfaces:**
- Consumes: `maybe_autoreset(trigger="pre_llm_call")` and `maybe_autoreset(trigger="transform_llm_output")`
- Produces: `trigger="pre_llm_call"` from preflight
- Produces: `trigger="transform_llm_output"` from footer evaluation

- [ ] **Step 1: Write failing trigger and safety tests.**

Add tests named `test_pre_llm_passes_pre_llm_trigger`,
`test_footer_passes_transform_trigger`,
`test_audit_failure_still_returns_original_prompt_and_response`, and
`test_no_raw_identifier_is_printed_to_stderr_on_audit_failure`.

Patch `maybe_autoreset` and capture kwargs. Existing hook order and one-shot notice tests must remain unchanged.

- [ ] **Step 2: Verify RED.**

```bash
uv run pytest tests/test_usage.py -k "trigger or audit_failure" -v
```

- [ ] **Step 3: Pass constant trigger names and use standard logging.**

At each existing coordinator call add only:

```python
trigger="pre_llm_call"
```

or:

```python
trigger="transform_llm_output"
```

Replace new audit diagnostics with `logging.getLogger(__name__)`; do not broaden unrelated stderr behavior in this task.

- [ ] **Step 4: Verify hooks and commit.**

```bash
uv run pytest tests/test_usage.py tests/test_autoreset.py -v
uv run ruff check plugin/hooks/footer_hook.py tests/test_usage.py
uv run ty check
git add plugin/hooks/footer_hook.py tests/test_usage.py
git commit -m "feat: identify auto-reset audit triggers"
```

---

### Task 4: Add the native offline history CLI

**Files:**
- Create: `plugin/autoreset_cli.py`
- Modify: `plugin/hooks/footer_hook.py`
- Modify: `plugin/__init__.py` only if export wiring requires it
- Create: `tests/test_autoreset_cli.py`
- Modify: `tests/test_usage.py`

**Interfaces:**
- Produces: `register_cli(parser: argparse.ArgumentParser) -> None`
- Produces: `usage_hook_command(args: argparse.Namespace) -> int`
- Consumes: `AutoResetAuditLog.read_events() -> tuple[list[dict], int]`
- Consumes: `acquire_autoreset_lock() -> AbstractContextManager[bool]`
- Registers: `hermes usage-hook history [--last N] [--since DURATION] [--json]`

- [ ] **Step 1: Write failing parser/filter/format tests.**

Create tests named `test_history_defaults_to_last_twenty_oldest_to_newest`,
`test_last_requires_positive_integer`,
`test_since_accepts_positive_s_m_h_d_durations`,
`test_since_filters_before_last_limit`,
`test_human_output_uses_local_timezone_and_question_marks`,
`test_json_output_is_compact_jsonl_in_stored_utc`,
`test_missing_file_human_message_and_exit_zero`,
`test_missing_file_json_is_silent_and_exit_zero`,
`test_malformed_lines_warn_only_on_stderr_without_raw_content`,
`test_unreadable_file_returns_one_without_traceback_or_secret_content`,
`test_busy_coordinator_lock_returns_one_without_reading_history`, and
`test_cli_never_imports_or_calls_codex_transport`.

Use an injected temporary home/environment and `argparse.ArgumentParser`; do not invoke the live installed `hermes` binary in unit tests.

- [ ] **Step 2: Run CLI tests and verify RED.**

```bash
uv run pytest tests/test_autoreset_cli.py -v
```

Expected: import failure because `plugin.autoreset_cli` does not exist.

- [ ] **Step 3: Implement parser and handler.**

Register:

```python
def register_cli(parser: argparse.ArgumentParser) -> None:
    subs = parser.add_subparsers(dest="usage_hook_action")
    history = subs.add_parser("history", help="Show successful Codex auto-reset history")
    history.add_argument("--last", type=_positive_int, default=20)
    history.add_argument("--since", type=_duration_seconds)
    history.add_argument("--json", action="store_true", dest="json_output")
    parser.set_defaults(func=usage_hook_command)
```

Handler dispatches only `history`, acquires `acquire_autoreset_lock()`, reads the active profile audit only while acquired, applies UTC `since` then `last`, and returns 0/1/2 exactly as approved. Lock contention exits 1 without reading. JSON stdout is one compact object per line with no headings. Human output includes timestamp, backend status, trigger, weekly before→after, and credits before→after.

- [ ] **Step 4: Write failing plugin registration test.**

Extend the fake plugin context to record `register_cli_command`. Assert exactly one call with:

```python
{
    "name": "usage-hook",
    "help": "Inspect hermes-usage-hook state and audit history",
    "setup_fn": autoreset_cli.register_cli,
    "handler_fn": autoreset_cli.usage_hook_command,
}
```

Keep the existing two hook registrations exactly once and in their current order.

- [ ] **Step 5: Register the CLI and verify Task 4.**

Add to `register(ctx)`:

```python
ctx.register_cli_command(
    name="usage-hook",
    help="Inspect hermes-usage-hook state and audit history",
    setup_fn=autoreset_cli.register_cli,
    handler_fn=autoreset_cli.usage_hook_command,
)
```

Run:

```bash
uv run pytest tests/test_autoreset_cli.py tests/test_usage.py -v
uv run ruff check plugin/autoreset_cli.py tests/test_autoreset_cli.py plugin/hooks/footer_hook.py
uv run ty check
git add plugin/autoreset_cli.py plugin/hooks/footer_hook.py plugin/__init__.py tests/test_autoreset_cli.py tests/test_usage.py
git commit -m "feat: add auto-reset history CLI"
```

Only stage `plugin/__init__.py` if it actually changed.

---

### Task 5: Document, validate, and package the complete change

**Files:**
- Modify: `README.md`
- Modify: `plugin/plugin.yaml` if release policy requires a development version only; otherwise leave unchanged
- Modify: `tests/test_usage.py` documentation/packaging assertions if needed
- Verify: `install.py`, `pyproject.toml`, all OpenSpec files

**Interfaces:**
- Documents: audit path, schema, retention, privacy, CLI examples, no-backfill limitation, recovery behavior.
- Preserves: installer inclusion of all `plugin/**/*.py` files.

- [ ] **Step 1: Add failing documentation and packaging assertions.**

Assert README contains:

```text
$HERMES_HOME/logs/hermes-usage-hook-autoreset.jsonl
hermes usage-hook history --last 20
hermes usage-hook history --since 30d
hermes usage-hook history --json
```

Assert installer packaging includes `autoreset_audit.py` and `autoreset_cli.py`, and no docs claim historical backfill or automatic rotation.

- [ ] **Step 2: Update README with exact operator behavior.**

Document:

- only successful logical resets are recorded;
- `observed_at` semantics for `already_redeemed`;
- event IDs are SHA-256 hashes and all correlatable IDs are omitted;
- no automatic deletion/rotation;
- CLI is offline and profile-scoped;
- malformed lines are skipped with a count;
- v0.4.0 and earlier history cannot be authoritatively reconstructed.

- [ ] **Step 3: Run focused docs/packaging checks.**

```bash
uv run pytest tests/test_usage.py -k "documentation or package or plugin" -v
uv run pytest tests/test_autoreset_cli.py -v
```

- [ ] **Step 4: Run the complete quality gate.**

```bash
uv run pytest
uv run ruff check .
uv run ty check
python3 -m compileall -q plugin tests
git diff --check
```

Expected: all commands exit 0. No live Codex API call occurs.

- [ ] **Step 5: Run isolated offline smoke tests.**

With a temporary Hermes home and synthetic JSONL event, verify:

```bash
HERMES_HOME=/tmp/hermes-usage-audit-smoke hermes usage-hook history --json
```

Expected: one synthetic JSONL event, no credentials/network access. Also run plugin import/discovery against the worktree source. Do not install to `~/.hermes/plugins` and do not restart Gateway during implementation verification.

- [ ] **Step 6: Review and commit documentation/spec artifacts.**

```bash
git status --short
git diff --check
git add README.md openspec/changes/add-autoreset-audit-log tests/test_usage.py
# Add plugin/plugin.yaml only if intentionally changed.
git commit -m "docs: document auto-reset audit history"
```

- [ ] **Step 7: Request a fresh whole-branch review.**

Review against `v0.4.0...HEAD` for correctness, crash consistency, append-only guarantees, privacy, CLI stdout/stderr contract, no-network tests, and regression risk. Resolve Critical/Important findings with new RED→GREEN tests, rerun the full gate, and present the final diff and verification evidence before requesting permission to push, install, restart, or open a PR.
