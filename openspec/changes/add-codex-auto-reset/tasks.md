# Codex Auto Reset Implementation Plan

> **Execution contract:** Implement with TDD in the task order below. Keep auto reset disabled by default. Automated tests and routine smoke checks MUST NOT call the live consume endpoint. A live credit consumption requires a fresh explicit confirmation after displaying current weekly usage, available credit count, and selected expiry.

**Goal:** Add opt-in, threshold-based automatic reset of the Codex weekly rate-limit window, configured canonically under `plugins.entries.hermes-usage-hook.auto_reset`, with environment overrides, dual Hermes hooks, cross-process deduplication, persistent idempotency, and a visible audit footer.

**Architecture:** A new synchronous `plugin/autoreset.py` owns configuration, policy, locking, state, credit selection, coordination, cooldowns, and one-shot notices. `plugin/providers/codex_usage.py` owns authenticated GET/POST transport. Both Hermes hooks call one coordinator; pre-LLM closes the exhausted-before-request gap, and the footer reuses its already-fetched usage and displays a one-shot notice. Every mutation is rechecked under a cross-process lock and uses a persisted UUID.

**Tech stack:** Python 3.10+, stdlib (`dataclasses`, `datetime`, `json`, `os`, `pathlib`, `time`, `uuid`, `contextlib`), `httpx==0.28.1`, Hermes `load_config()` via a lazy runtime import, pytest, Ruff, ty.

**Approved specs:**
- `openspec/changes/add-codex-auto-reset/proposal.md`
- `openspec/changes/add-codex-auto-reset/design.md`
- `openspec/changes/add-codex-auto-reset/specs/codex-auto-reset/spec.md`
- `openspec/changes/add-codex-auto-reset/specs/footer-hook-deployment/spec.md`

---

## 1. Prepare an isolated feature branch and lock the baseline

**Files:**
- Add: `openspec/changes/add-codex-auto-reset/tasks.md`
- Do not stage: existing unrelated `pr-body.md`

- [x] **1.1 Create the feature branch from verified `origin/main`.**

```bash
git fetch origin
git switch main
git pull --ff-only
git switch -c feat/codex-auto-reset
```

Expected: branch starts at `v0.3.0`/current `origin/main`; the approved OpenSpec change remains untracked and ready to add.

- [x] **1.2 Run the baseline suite before implementation.**

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ty check
```

Expected baseline: all existing tests and checks pass. If not, stop and record the pre-existing failure before changing product code.

- [x] **1.3 Commit only the approved specification and plan.**

```bash
git add openspec/changes/add-codex-auto-reset
git diff --cached --check
git commit -m "docs: specify Codex auto reset"
```

Do not include `pr-body.md` or credentials.

---

## 2. Add canonical plugin-config resolution with fail-closed env overrides

**Files:**
- Create: `plugin/autoreset.py`
- Create: `tests/test_autoreset.py`

- [ ] **2.1 Write failing configuration tests.**

Cover at minimum:

```python
def test_config_defaults_disabled_threshold_zero(): ...
def test_plugin_entry_enables_auto_reset(): ...
def test_env_false_overrides_plugin_true(): ...
def test_env_true_overrides_plugin_false(): ...
def test_env_threshold_overrides_plugin_threshold(): ...
def test_threshold_accepts_zero_and_ninety_nine(): ...
@pytest.mark.parametrize("value", ["", "x", "-1", "100", True, 1.5])
def test_invalid_threshold_fails_closed(value): ...
@pytest.mark.parametrize("value", ["maybe", "enabled", "2", ""])
def test_invalid_explicit_boolean_env_fails_closed(value): ...
def test_missing_hermes_runtime_falls_back_to_defaults(): ...
```

Use an injected full config dict shaped as:

```python
{
    "plugins": {
        "entries": {
            "hermes-usage-hook": {
                "auto_reset": {"enabled": True, "threshold": 10}
            }
        }
    }
}
```

- [ ] **2.2 Run the focused tests and verify RED.**

```bash
uv run pytest tests/test_autoreset.py -k config -v
```

Expected: failures because `plugin.autoreset` and config resolution do not exist.

- [ ] **2.3 Implement typed, lazy config resolution.**

Add these public/internal shapes to `plugin/autoreset.py`:

```python
PLUGIN_ID = "hermes-usage-hook"
ENV_ENABLED = "CODEX_ENABLE_AUTORESET"
ENV_THRESHOLD = "CODEX_AUTORESET_THRESHOLD"

@dataclass(frozen=True)
class AutoResetConfig:
    enabled: bool
    threshold: int
    valid: bool = True
    error: str | None = None


def _load_hermes_config() -> dict:
    try:
        from hermes_cli.config import load_config
    except ImportError:
        return {}
    loaded = load_config() or {}
    return loaded if isinstance(loaded, dict) else {}


def load_autoreset_config(
    *, env: Mapping[str, str] | None = None, config: dict | None = None
) -> AutoResetConfig:
    ...
```

Rules:
- canonical source: `plugins.entries.hermes-usage-hook.auto_reset.enabled/threshold`;
- precedence: explicitly present env → plugin config → defaults;
- plugin `enabled` must be a real boolean;
- plugin `threshold` must be an integer but not a boolean;
- explicit env booleans accept only `1/true/yes/on` and `0/false/no/off`, trimmed and case-folded;
- threshold range is `0..99`;
- invalid explicit values return `valid=False, enabled=False` and never silently fall through to a lower-precedence value;
- import `hermes_cli.config` only inside `_load_hermes_config`, because this standalone repo does not depend on Hermes during unit tests.

- [ ] **2.4 Run focused tests and verify GREEN.**

```bash
uv run pytest tests/test_autoreset.py -k config -v
uv run ruff check plugin/autoreset.py tests/test_autoreset.py
uv run ty check
```

- [ ] **2.5 Commit the configuration slice.**

```bash
git add plugin/autoreset.py tests/test_autoreset.py
git commit -m "feat: resolve Codex auto reset config"
```

---

## 3. Add authenticated reset-credit list and consume transport

**Files:**
- Modify: `plugin/providers/codex_usage.py`
- Modify: `tests/test_usage.py`

- [ ] **3.1 Write failing provider tests without live HTTP.**

Add tests for:

```python
def test_list_reset_credits_uses_get_endpoint_and_active_auth(): ...
def test_consume_reset_credit_posts_stable_identifiers(): ...
def test_consume_omits_credit_id_only_when_none(): ...
def test_reset_transport_sends_chatgpt_account_header_when_present(): ...
def test_reset_transport_raises_on_401_429_and_5xx(): ...
def test_reset_transport_does_not_retry_post(): ...
def test_provider_errors_do_not_include_bearer_token(): ...
```

Use a fake `httpx.Client`/`MockTransport`; never read the real `auth.json` and never call the live Codex backend in tests.

- [ ] **3.2 Run the focused tests and verify RED.**

```bash
uv run pytest tests/test_usage.py -k "reset_credit or consume" -v
```

- [ ] **3.3 Refactor shared authenticated JSON transport and add APIs.**

Add constants:

```python
# Use the real Codex reset-credit base URL here (kept out of this artifact;
# see plugin/providers/codex_usage.py for the concrete value).
RESET_CREDITS_URL = "<codex-backend>/reset-credits"
CONSUME_RESET_CREDIT_URL = f"{RESET_CREDITS_URL}/consume"
```

Add provider-owned functions:

```python
def list_rate_limit_reset_credits() -> dict:
    """GET the detailed reset-credit collection using active Codex OAuth."""


def consume_rate_limit_reset_credit(
    redeem_request_id: str, credit_id: str | None
) -> dict:
    """POST one idempotent consume attempt; never generate or retry IDs here."""
```

The POST body is exactly:

```python
{"redeem_request_id": redeem_request_id, "credit_id": credit_id}
```

Omit `credit_id` when `None`. Reuse `_load_auth()` and active account selection. Centralize headers without logging them. Keep generic POST retries forbidden—the coordinator owns retry timing and identifier reuse.

- [ ] **3.4 Verify provider tests and existing normalization.**

```bash
uv run pytest tests/test_usage.py -k "codex or reset_credit or consume" -v
uv run ruff check plugin/providers/codex_usage.py tests/test_usage.py
```

- [ ] **3.5 Commit the transport slice.**

```bash
git add plugin/providers/codex_usage.py tests/test_usage.py
git commit -m "feat: add Codex reset credit API client"
```

---

## 4. Implement pure eligibility and earliest-expiry selection

**Files:**
- Modify: `plugin/autoreset.py`
- Modify: `plugin/usage.py`
- Modify: `tests/test_autoreset.py`
- Modify: `tests/test_usage.py`

- [ ] **4.1 Write failing policy and selection tests.**

Cover:

```python
def test_non_codex_model_is_ineligible(): ...
def test_missing_weekly_window_is_ineligible(): ...
def test_zero_or_missing_credit_count_is_ineligible(): ...
def test_remaining_equal_to_threshold_is_eligible(): ...
def test_remaining_above_threshold_is_ineligible(): ...
def test_remaining_below_threshold_is_eligible(): ...
def test_selects_earliest_available_non_null_expiry(): ...
def test_null_expiry_sorts_after_real_expiry(): ...
def test_ignores_redeemed_and_unusable_rows(): ...
def test_positive_count_but_no_valid_id_fails_closed(): ...
def test_malformed_credit_schema_fails_closed(): ...
```

Use the observed safe response shape:

```python
{
    "available_count": 2,
    "total_earned_count": 3,
    "credits": [
        {
            "id": "credit-1",
            "status": "available",
            "expires_at": "2026-07-18T00:40:00Z",
            "reset_type": "full",
        }
    ],
}
```

- [ ] **4.2 Verify RED.**

```bash
uv run pytest tests/test_autoreset.py -k "eligible or credit or expiry" -v
```

- [ ] **4.3 Expose Codex model matching and implement pure helpers.**

In `plugin/usage.py`, rename/export the current matcher as a stable helper while preserving registry behavior:

```python
def matches_codex_model(model: str | None) -> bool: ...
```

In `plugin/autoreset.py`, add pure helpers similar to:

```python
def weekly_remaining(usage: dict) -> int | float | None: ...
def is_eligible(*, model: str | None, usage: dict, config: AutoResetConfig) -> bool: ...
def select_earliest_available_credit(payload: dict) -> dict | None: ...
```

Do not infer weekly from position or reset timestamps. Require `credits` to be a list, `status == "available"`, and a non-empty string `id`. Parse ISO-8601 `Z` safely. Sort valid non-null expiries earliest-first and null expiry last. Reject any row whose non-null `expires_at` is malformed; if no valid available row remains, fail the invocation closed.

- [ ] **4.4 Verify GREEN and provider-registry regressions.**

```bash
uv run pytest tests/test_autoreset.py -k "eligible or credit or expiry" -v
uv run pytest tests/test_usage.py -k "match or provider" -v
uv run ruff check plugin/autoreset.py plugin/usage.py tests
uv run ty check
```

- [ ] **4.5 Commit the pure-policy slice.**

```bash
git add plugin/autoreset.py plugin/usage.py tests/test_autoreset.py tests/test_usage.py
git commit -m "feat: add Codex auto reset policy"
```

---

## 5. Add profile-local atomic state, lock, cooldown, and notices

**Files:**
- Modify: `plugin/autoreset.py`
- Modify: `tests/test_autoreset.py`

- [ ] **5.1 Write failing state/lock tests using `tmp_path`.**

Cover:

```python
def test_state_uses_hermes_home_and_contains_no_credentials(tmp_path): ...
def test_state_write_is_atomic_and_owner_only_where_supported(tmp_path): ...
def test_pending_attempt_round_trips_identifiers(tmp_path): ...
def test_corrupt_state_is_quarantined_and_invocation_fails_closed(tmp_path): ...
def test_only_one_process_style_lock_holder_wins(tmp_path): ...
def test_fresh_lock_is_not_reclaimed(tmp_path): ...
def test_stale_lock_can_be_reclaimed_once(tmp_path): ...
def test_cooldown_blocks_until_deadline(tmp_path): ...
def test_notice_is_popped_once_for_matching_session(tmp_path): ...
def test_empty_session_id_never_leaks_notice_across_sessions(tmp_path): ...
```

- [ ] **5.2 Verify RED.**

```bash
uv run pytest tests/test_autoreset.py -k "state or lock or cooldown or notice" -v
```

- [ ] **5.3 Implement state and locking without new dependencies.**

State paths:

```text
$HERMES_HOME/state/hermes-usage-hook/autoreset.json
$HERMES_HOME/state/hermes-usage-hook/autoreset.lock/
```

Implement:
- `_hermes_home()` honoring `HERMES_HOME`, defaulting to `~/.hermes`;
- JSON state versioning (start at version `1`);
- temp-file + `os.replace` atomic writes;
- owner-only file mode where supported;
- `os.mkdir` lock acquisition with PID/time metadata;
- 120-second stale-lock detection and one reclaim attempt;
- `finally` release owned lock only;
- corrupt state quarantine to a timestamped sibling and fail closed for that invocation;
- pending attempt fields: request UUID, credit ID, status, timestamps, cooldown, safe before values;
- one-shot audit notices keyed only by non-empty `session_id`, with a bounded TTL (24 hours) and pop-on-read behavior;
- no access token, refresh token, account/user ID, auth headers, or full response bodies.

Use explicit injected `now`/clock values in tests—no sleeps.

- [ ] **5.4 Verify GREEN.**

```bash
uv run pytest tests/test_autoreset.py -k "state or lock or cooldown or notice" -v
uv run ruff check plugin/autoreset.py tests/test_autoreset.py
uv run ty check
```

- [ ] **5.5 Commit the state slice.**

```bash
git add plugin/autoreset.py tests/test_autoreset.py
git commit -m "feat: persist Codex auto reset attempts"
```

---

## 6. Build the synchronous coordinator with stable retry identity

**Files:**
- Modify: `plugin/autoreset.py`
- Modify: `tests/test_autoreset.py`

- [ ] **6.1 Write failing coordinator tests with injected fakes.**

Cover all approved outcomes and call ordering:

```python
def test_disabled_returns_before_any_network_or_state_mutation(): ...
def test_above_threshold_does_not_lock_or_list_credits(): ...
def test_eligible_path_rechecks_usage_inside_lock(): ...
def test_recheck_above_threshold_avoids_consume(): ...
def test_reset_persists_before_post_then_refreshes(): ...
def test_post_timeout_preserves_pending_attempt(): ...
def test_retry_reuses_same_uuid_and_credit_id(): ...
def test_already_redeemed_is_successful_terminal(): ...
def test_nothing_to_reset_sets_five_minute_cooldown(): ...
def test_no_credit_sets_five_minute_cooldown(): ...
def test_transient_get_failure_sets_one_minute_cooldown(): ...
def test_unknown_or_malformed_response_fails_closed(): ...
def test_two_contenders_cause_one_logical_consume(): ...
def test_success_queues_one_notice_for_session(): ...
def test_hook_facing_api_never_raises(): ...
```

Inject `usage_fetcher`, `credit_lister`, `consumer`, `uuid_factory`, state store, lock, and clock. Assert the persisted pending record exists before the fake consumer is called.

- [ ] **6.2 Verify RED.**

```bash
uv run pytest tests/test_autoreset.py -k "coordinator or reset or timeout or redeemed or contender" -v
```

- [ ] **6.3 Implement the coordinator.**

Add:

```python
@dataclass(frozen=True)
class AutoResetResult:
    status: str
    before_remaining: int | float | None = None
    after_remaining: int | float | None = None
    before_credits: int | None = None
    after_credits: int | None = None
    after_usage: dict | None = None
    message: str | None = None


def maybe_autoreset(
    *,
    model: str | None,
    usage: dict | None = None,
    session_id: str = "",
    turn_id: str = "",
    ...injected dependencies...
) -> AutoResetResult:
    ...
```

Required ordering:
1. resolve config and return on invalid/disabled;
2. reject non-Codex;
3. use supplied usage or fetch;
4. validate weekly/count/threshold/cooldown;
5. acquire lock;
6. reload state and live usage, then re-evaluate;
7. reuse unresolved pending identifiers, otherwise list/select/generate/persist;
8. POST once;
9. classify `reset`, `already_redeemed`, `nothing_to_reset`, `no_credit`, unknown;
10. refresh usage/count after success;
11. persist terminal/cooldown state and queue one notice;
12. release lock in `finally`.

Ambiguous POST exceptions keep pending identifiers and set retry-after one minute. A subsequent invocation uses exactly the same UUID and credit ID. Never make a generic POST retry inside one invocation.

A consume response of `reset` with a failed refresh must remain transparent: queue a truthful partial notice such as `Codex auto reset | reset accepted; usage refresh unavailable`, rather than claiming percentages or hiding the accepted mutation.

- [ ] **6.4 Verify GREEN and all auto-reset tests.**

```bash
uv run pytest tests/test_autoreset.py -v
uv run ruff check plugin/autoreset.py tests/test_autoreset.py
uv run ty check
```

- [ ] **6.5 Commit the coordinator slice.**

```bash
git add plugin/autoreset.py tests/test_autoreset.py
git commit -m "feat: coordinate idempotent Codex auto reset"
```

---

## 7. Register dual synchronous hooks and render one audit line

**Files:**
- Modify: `plugin/hooks/footer_hook.py`
- Modify: `plugin/plugin.yaml`
- Modify: `tests/test_usage.py`
- Modify: `tests/test_plugin_manifest.py` if manifest tests already live there; otherwise keep them in `tests/test_usage.py`

- [ ] **7.1 Write failing hook-contract tests.**

Cover:

```python
def test_register_adds_transform_and_pre_llm_hooks_exactly_once(): ...
def test_preflight_disabled_returns_none_without_network(): ...
def test_preflight_is_synchronous_and_never_injects_prompt_context(): ...
def test_preflight_passes_session_turn_and_model(): ...
def test_footer_passes_existing_usage_to_coordinator(): ...
def test_footer_uses_refreshed_usage_after_reset(): ...
def test_footer_pops_preflight_notice_once(): ...
def test_footer_triggered_reset_adds_exactly_one_notice(): ...
def test_autoreset_failure_keeps_original_reply_and_normal_footer(): ...
def test_manifest_declares_exactly_two_supported_hooks(): ...
```

Also retain all existing MiniMax, unknown-model, and footer-format regressions.

- [ ] **7.2 Verify RED.**

```bash
uv run pytest tests/test_usage.py -k "register or preflight or footer or manifest" -v
```

- [ ] **7.3 Integrate synchronous handlers.**

`hermes_cli.plugins.invoke_hook()` calls callbacks synchronously and does not await coroutine results. Therefore both handlers MUST be plain `def`, not `async def`.

Add a preflight handler:

```python
def codex_autoreset_preflight(**kwargs) -> None:
    try:
        maybe_autoreset(
            model=kwargs.get("model"),
            session_id=kwargs.get("session_id") or "",
            turn_id=kwargs.get("turn_id") or "",
        )
    except Exception as exc:
        print(f"[hermes-usage-hook] auto reset skipped: {exc}", file=sys.stderr)
    return None
```

`None` is mandatory so `pre_llm_call` injects no model context.

Update registration:

```python
ctx.register_hook("transform_llm_output", append_usage_footer)
ctx.register_hook("pre_llm_call", codex_autoreset_preflight)
```

Update `append_usage_footer`:
- retain one normal usage GET;
- call `maybe_autoreset(..., usage=usage, session_id=...)`;
- if `after_usage` exists, render it instead of stale usage;
- pop at most one notice for the non-empty matching `session_id`;
- append the audit line below the usage summary;
- if auto reset fails, preserve original reply and existing footer behavior.

Update `plugin/plugin.yaml`:

```yaml
provides_hooks:
  - transform_llm_output
  - pre_llm_call
```

Do not add `requires_env`; auto reset is optional and disabled by default.

- [ ] **7.4 Verify GREEN.**

```bash
uv run pytest tests/test_usage.py -k "register or preflight or footer or manifest" -v
uv run pytest tests/test_autoreset.py -v
uv run ruff check plugin/hooks/footer_hook.py plugin/plugin.yaml tests
uv run ty check
```

- [ ] **7.5 Commit the hook slice.**

```bash
git add plugin/hooks/footer_hook.py plugin/plugin.yaml tests
git commit -m "feat: trigger Codex auto reset from dual hooks"
```

---

## 8. Document plugin config, env overrides, internal API risk, and operations

**Files:**
- Modify: `README.md`
- Modify: `plugin/providers/codex_usage.py` module docstring
- Modify: `plugin/hooks/footer_hook.py` module docstring
- Modify: `tests/test_install.py` only if installer/archive assertions require the new file or hook

- [ ] **8.1 Add README documentation tests/assertions if the project uses them.**

At minimum assert README and shipped manifest mention:
- `plugins.entries.hermes-usage-hook.auto_reset.enabled`;
- `plugins.entries.hermes-usage-hook.auto_reset.threshold`;
- `CODEX_ENABLE_AUTORESET` and `CODEX_AUTORESET_THRESHOLD` as optional overrides;
- default disabled and threshold `0`;
- valid range `0..99` and weekly remaining semantics;
- irreversible autonomous consumption;
- earliest-expiry selection and idempotency;
- internal/unstable ChatGPT backend API warning;
- no OAuth values in plugin config.

- [ ] **8.2 Update README with canonical YAML and CLI examples.**

Include:

```yaml
plugins:
  entries:
    hermes-usage-hook:
      auto_reset:
        enabled: true
        threshold: 0
```

```bash
hermes config set plugins.entries.hermes-usage-hook.auto_reset.enabled true
hermes config set plugins.entries.hermes-usage-hook.auto_reset.threshold 0
```

Document precedence as env → plugin config → defaults and link the official namespace example:

```text
https://hermes-agent.nousresearch.com/docs/developer-guide/plugin-llm-access#trust-gate
```

State clearly that Hermes documents `plugins.entries.<plugin_id>` for plugin LLM trust configuration, while `auto_reset.*` is this plugin's own schema read through Hermes `load_config()`; do not imply Hermes has a generic plugin-config UI/schema.

- [ ] **8.3 Update architecture/file tables and operational notes.**

Add `plugin/autoreset.py`, dual hooks, state paths, cooldown behavior, disabled-mode network behavior, and audit example:

```text
Codex auto reset | weekly 0% → 100% | reset credits 3 → 2
```

Mention plugin config is read per hook invocation; process env changes need Gateway restart/reload. Do not add `requires_env` to the manifest.

- [ ] **8.4 Verify docs/install regressions.**

```bash
uv run pytest tests/test_install.py -v
uv run pytest tests/test_usage.py -k "readme or manifest" -v
uv run ruff check .
```

- [ ] **8.5 Commit documentation.**

```bash
git add README.md plugin tests
git commit -m "docs: explain Codex auto reset configuration"
```

---

## 9. Run complete verification and disabled-mode Hermes smoke test

**Files:**
- No planned source changes; fix failures in the owning task's files and rerun.

- [ ] **9.1 Run the complete quality gate.**

```bash
uv run pytest
uv run ruff check .
uv run ty check
python -m compileall -q plugin
```

Expected: all commands exit 0; no warnings about un-awaited coroutine hooks.

- [ ] **9.2 Test installation in an isolated Hermes home.**

```bash
SMOKE_HOME="$(mktemp -d /tmp/hermes-usage-hook-smoke.XXXXXX)"
uv run install.py --local --hermes-home "$SMOKE_HOME"
HERMES_HOME="$SMOKE_HOME" hermes plugins list --plain --no-bundled
```

Verify:
- plugin is discovered/enabled;
- manifest declares both hooks;
- no auto-reset network call occurs because config is absent;
- installation preserves `plugins.entries` if rerun;
- no real credit is consumed.

Do not delete the smoke directory as part of an unattended run; report its path so cleanup remains explicit.

- [ ] **9.3 Test config parsing against an isolated real `config.yaml`.**

```bash
HERMES_HOME="$SMOKE_HOME" hermes config set plugins.entries.hermes-usage-hook.auto_reset.enabled false
HERMES_HOME="$SMOKE_HOME" hermes config set plugins.entries.hermes-usage-hook.auto_reset.threshold 0
```

Load the plugin and assert effective config is disabled/0 without calling usage or consume APIs.

- [ ] **9.4 Audit the diff for secrets and scope.**

```bash
git diff main...HEAD --check
git diff main...HEAD --stat
git grep -nE 'Bearer |access_token|refresh_token|ChatGPT-Account-Id' -- . ':!plugin/providers/codex_usage.py' ':!tests'
git status --short
```

Inspect every match. No real token, account ID, credit ID, live response body, or auth fixture may be committed. Keep unrelated `pr-body.md` untracked.

- [ ] **9.5 Commit any verification-only corrections.**

Use a scoped commit only if verification required changes; otherwise do not create an empty commit.

---

## 10. Optional live verification and publication gate

**Files:**
- No automated source change expected.

- [ ] **10.1 Present current live state and request explicit consume confirmation.**

Before any live POST, show:
- current weekly used/remaining;
- reset-credit available count;
- earliest available credit expiry;
- expected irreversible decrement (for example 2 → 1);
- generated/reused idempotency key policy.

A prior test confirmation does not authorize a new consume. If confirmation is not given, stop after read-only checks.

- [ ] **10.2 If explicitly confirmed, install locally with auto reset still disabled first.**

Use the official local installer, verify plugin discovery, then update the real config only after restating that `enabled=true` is standing authorization for autonomous future consumption. Do not enable it merely to test parser behavior.

- [ ] **10.3 Perform at most one controlled live reset and verify.**

Only when weekly remaining meets the configured threshold:
- select earliest-expiring available credit;
- persist UUID before POST;
- consume once;
- re-fetch usage/count/details;
- verify weekly reset and count decrement;
- verify state completion and one audit footer;
- never retry with a new UUID after an ambiguous timeout.

- [ ] **10.4 Prepare English PR material and request publication confirmation.**

```bash
git log --oneline main..HEAD
git diff --stat main...HEAD
gh pr create --draft --title "feat: add automatic Codex weekly reset" --body-file <reviewed-pr-body>
```

Creating/pushing a public branch or PR is an external publication action: obtain explicit confirmation immediately before `git push`/`gh pr create`. The PR must state that the endpoint is internal/unstable, auto reset is disabled by default, plugin config is canonical, env values override it, tests use mocks, and live consume is not part of CI.

---

## Definition of Done

- [ ] Approved OpenSpec files and this `tasks.md` are committed.
- [ ] Plugin config is canonical; env overrides and defaults behave exactly as specified.
- [ ] Disabled mode adds no pre-request network call.
- [ ] Only real Codex weekly windows can qualify.
- [ ] Earliest-expiring available credit is selected from the observed API shape.
- [ ] Cross-process lock + lock-time recheck prevents concurrent double consumption.
- [ ] Pending UUID and credit ID survive timeout/restart and are reused.
- [ ] All outcomes/cooldowns are tested; hook errors never break replies.
- [ ] Both registered hooks are synchronous and inject no prompt context.
- [ ] Successful reset is visible once in the matching session footer.
- [ ] State/logs/tests/docs contain no credentials or account/user IDs.
- [ ] Full pytest, Ruff, ty, compileall, installer, and disabled smoke checks pass.
- [ ] No live credit is consumed without a fresh explicit confirmation.
- [ ] No public push/PR occurs without publication confirmation.
