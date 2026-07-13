"""Tests for fail-closed Codex auto-reset configuration resolution."""

from __future__ import annotations

from contextlib import contextmanager

import httpx
import pytest

from plugin import autoreset


def _plugin_config(*, enabled=True, threshold=10):
    return {
        "plugins": {
            "entries": {
                "hermes-usage-hook": {
                    "auto_reset": {"enabled": enabled, "threshold": threshold}
                }
            }
        }
    }


def test_config_defaults_disabled_threshold_zero():
    assert autoreset.load_autoreset_config(env={}, config={}) == autoreset.AutoResetConfig(
        enabled=False,
        threshold=0,
    )


def test_plugin_entry_enables_auto_reset():
    assert autoreset.load_autoreset_config(
        env={}, config=_plugin_config(enabled=True, threshold=10)
    ) == autoreset.AutoResetConfig(enabled=True, threshold=10)


def test_env_false_overrides_plugin_true():
    result = autoreset.load_autoreset_config(
        env={autoreset.ENV_ENABLED: " off "},
        config=_plugin_config(enabled=True),
    )
    assert result.enabled is False
    assert result.valid is True


def test_env_true_overrides_plugin_false():
    result = autoreset.load_autoreset_config(
        env={autoreset.ENV_ENABLED: "YES"},
        config=_plugin_config(enabled=False),
    )
    assert result.enabled is True
    assert result.valid is True


def test_env_threshold_overrides_plugin_threshold():
    result = autoreset.load_autoreset_config(
        env={autoreset.ENV_THRESHOLD: " 42 "},
        config=_plugin_config(threshold=10),
    )
    assert result.threshold == 42
    assert result.valid is True


@pytest.mark.parametrize("value", [0, 99])
def test_threshold_accepts_zero_and_ninety_nine(value):
    result = autoreset.load_autoreset_config(
        env={}, config=_plugin_config(threshold=value)
    )
    assert result.threshold == value
    assert result.valid is True


@pytest.mark.parametrize("value", ["", "x", "-1", "100", True, 1.5])
def test_invalid_threshold_fails_closed(value):
    result = autoreset.load_autoreset_config(
        env={}, config=_plugin_config(enabled=True, threshold=value)
    )
    assert result.valid is False
    assert result.enabled is False
    assert result.error


@pytest.mark.parametrize("value", ["", "x", "-1", "100", True, 1.5])
def test_invalid_explicit_env_threshold_fails_closed(value):
    result = autoreset.load_autoreset_config(
        env={autoreset.ENV_THRESHOLD: value},
        config=_plugin_config(enabled=True, threshold=10),
    )
    assert result.valid is False
    assert result.enabled is False
    assert result.error


@pytest.mark.parametrize("value", ["maybe", "enabled", "2", ""])
def test_invalid_explicit_boolean_env_fails_closed(value):
    result = autoreset.load_autoreset_config(
        env={autoreset.ENV_ENABLED: value},
        config=_plugin_config(enabled=True),
    )
    assert result.valid is False
    assert result.enabled is False
    assert result.error


@pytest.mark.parametrize("value", ["true", 1, None])
def test_invalid_plugin_boolean_fails_closed(value):
    result = autoreset.load_autoreset_config(
        env={}, config=_plugin_config(enabled=value)
    )
    assert result.valid is False
    assert result.enabled is False
    assert result.error


def test_invalid_explicit_env_does_not_fall_through_to_plugin_value():
    result = autoreset.load_autoreset_config(
        env={autoreset.ENV_ENABLED: ""},
        config=_plugin_config(enabled=True, threshold=10),
    )
    assert result.valid is False
    assert result.enabled is False


def test_missing_hermes_runtime_falls_back_to_defaults(monkeypatch):
    def missing_hermes(name):
        assert name == "hermes_cli.config"
        raise ImportError("Hermes is not installed")

    monkeypatch.setattr(autoreset, "import_module", missing_hermes)

    assert autoreset.load_autoreset_config(env={}) == autoreset.AutoResetConfig(
        enabled=False,
        threshold=0,
    )


# --- Pure auto-reset eligibility and credit selection -------------------------


def _eligible_usage(*, remaining=10, credits=2):
    return {
        "provider": "Codex",
        "windows": {"weekly": {"remaining_percent": remaining}},
        "reset_credits_available": credits,
    }


def _enabled_config(threshold=10):
    return autoreset.AutoResetConfig(enabled=True, threshold=threshold)


def test_non_codex_model_is_ineligible():
    assert not autoreset.is_eligible(
        model="claude-opus-4",
        usage=_eligible_usage(),
        config=_enabled_config(),
    )


def test_missing_weekly_window_is_ineligible():
    usage = _eligible_usage()
    usage["windows"] = {"5h": {"remaining_percent": 0}}

    assert autoreset.weekly_remaining(usage) is None
    assert not autoreset.is_eligible(
        model="gpt-5-codex", usage=usage, config=_enabled_config()
    )


@pytest.mark.parametrize("credits", [None, 0])
def test_zero_or_missing_credit_count_is_ineligible(credits):
    assert not autoreset.is_eligible(
        model="gpt-5-codex",
        usage=_eligible_usage(credits=credits),
        config=_enabled_config(),
    )


def test_remaining_equal_to_threshold_is_eligible():
    assert autoreset.is_eligible(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=10),
        config=_enabled_config(threshold=10),
    )


def test_remaining_above_threshold_is_ineligible():
    assert not autoreset.is_eligible(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=11),
        config=_enabled_config(threshold=10),
    )


def test_remaining_below_threshold_is_eligible():
    assert autoreset.is_eligible(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=9),
        config=_enabled_config(threshold=10),
    )


def _credit(credit_id, expires_at, *, status="available", reset_type="full"):
    return {
        "id": credit_id,
        "status": status,
        "expires_at": expires_at,
        "reset_type": reset_type,
    }


def _credit_payload(*credits, available_count=None):
    return {
        "available_count": len(credits) if available_count is None else available_count,
        "total_earned_count": len(credits),
        "credits": list(credits),
    }


def test_selects_earliest_available_non_null_expiry():
    selected = autoreset.select_earliest_available_credit(
        _credit_payload(
            _credit("credit-late", "2026-07-31T00:40:00Z"),
            _credit("credit-first", "2026-07-18T00:40:00Z"),
            _credit("credit-middle", "2026-07-27T00:40:00Z"),
        )
    )

    assert selected is not None
    assert selected["id"] == "credit-first"


def test_null_expiry_sorts_after_real_expiry():
    selected = autoreset.select_earliest_available_credit(
        _credit_payload(
            _credit("credit-no-expiry", None),
            _credit("credit-expiring", "2026-07-18T00:40:00Z"),
        )
    )

    assert selected is not None
    assert selected["id"] == "credit-expiring"


def test_ignores_redeemed_and_unusable_rows():
    selected = autoreset.select_earliest_available_credit(
        _credit_payload(
            _credit("redeemed", "2026-07-17T00:40:00Z", status="redeemed"),
            _credit("", "2026-07-16T00:40:00Z"),
            _credit("usable", None),
        )
    )

    assert selected is not None
    assert selected["id"] == "usable"


def test_positive_count_but_no_valid_id_fails_closed():
    assert (
        autoreset.select_earliest_available_credit(
            _credit_payload(
                _credit("", "2026-07-18T00:40:00Z"), available_count=1
            )
        )
        is None
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"available_count": 1, "credits": "not-a-list"},
        {"available_count": 1, "credits": ["not-a-row"]},
        _credit_payload(
            _credit("malformed-expiry", "not-an-iso-date"), available_count=1
        ),
    ],
)
def test_malformed_credit_schema_fails_closed(payload):
    assert autoreset.select_earliest_available_credit(payload) is None


def test_malformed_available_row_does_not_hide_another_valid_credit():
    selected = autoreset.select_earliest_available_credit(
        _credit_payload(
            _credit("malformed", "not-an-iso-date"),
            _credit("valid", "2026-07-18T00:40:00Z"),
        )
    )

    assert selected is not None
    assert selected["id"] == "valid"


# --- Profile-local state, locking, cooldowns, and one-shot notices ------------


def _pending_attempt():
    return {
        "redeem_request_id": "request-uuid",
        "credit_id": "credit-1",
        "status": "pending",
        "created_at": 1_000.0,
        "updated_at": 1_000.0,
        "retry_after": 1_060.0,
        "before_remaining": 0,
        "before_credits": 3,
    }


def test_state_uses_hermes_home_and_contains_no_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = autoreset.AutoResetStateStore(clock=lambda: 1_000.0)

    store.write(
        {
            "pending": {
                **_pending_attempt(),
                "access_token": "must-not-persist",
                "refresh_token": "also-secret",
                "account_id": "private-account",
                "headers": {"Authorization": "Bearer secret"},
                "response": {"full": "body"},
            }
        }
    )

    assert store.path == (
        tmp_path / "state" / "hermes-usage-hook" / "autoreset.json"
    )
    serialized = store.path.read_text()
    for forbidden in (
        "must-not-persist",
        "also-secret",
        "private-account",
        "Authorization",
        "response",
    ):
        assert forbidden not in serialized


def test_state_write_is_atomic_and_owner_only_where_supported(monkeypatch, tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    real_replace = autoreset.os.replace
    replacements = []

    def recording_replace(source, destination):
        replacements.append((source, destination))
        return real_replace(source, destination)

    monkeypatch.setattr(autoreset.os, "replace", recording_replace)

    store.write({"pending": _pending_attempt()})

    assert replacements and replacements[-1][1] == store.path
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert list(store.path.parent.glob(".autoreset.*.tmp")) == []


def test_pending_attempt_round_trips_identifiers(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    store.write({"pending": _pending_attempt()})

    pending = store.load()["pending"]

    assert pending["redeem_request_id"] == "request-uuid"
    assert pending["credit_id"] == "credit-1"
    assert pending["status"] == "pending"


def test_corrupt_state_is_quarantined_and_invocation_fails_closed(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_234.5)
    store.path.parent.mkdir(parents=True)
    store.path.write_text("{not-json")

    with pytest.raises(autoreset.CorruptStateError):
        store.load()

    assert not store.path.exists()
    quarantined = list(store.path.parent.glob("autoreset.corrupt.1234*.json"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text() == "{not-json"


def test_only_one_process_style_lock_holder_wins(tmp_path):
    with autoreset.acquire_autoreset_lock(home=tmp_path, now=1_000.0) as first:
        assert first is True
        with autoreset.acquire_autoreset_lock(home=tmp_path, now=1_000.0) as second:
            assert second is False


def test_fresh_lock_is_not_reclaimed(tmp_path):
    with autoreset.acquire_autoreset_lock(home=tmp_path, now=1_000.0) as first:
        assert first is True
        with autoreset.acquire_autoreset_lock(home=tmp_path, now=1_119.9) as second:
            assert second is False


def test_stale_lock_can_be_reclaimed_once(tmp_path):
    with autoreset.acquire_autoreset_lock(home=tmp_path, now=1_000.0) as first:
        assert first is True
        with autoreset.acquire_autoreset_lock(home=tmp_path, now=1_120.1) as second:
            assert second is True
            with autoreset.acquire_autoreset_lock(home=tmp_path, now=1_120.2) as third:
                assert third is False


def test_stale_reclaimer_never_steals_fresh_replacement(tmp_path):
    lock_path = tmp_path / "state" / autoreset.PLUGIN_ID / "autoreset.lock"
    lock_path.mkdir(parents=True)
    (lock_path / "owner.json").write_text(
        '{"owner":"stale-owner","created_at":1000.0}'
    )
    observed_identity = autoreset._lock_identity(lock_path)
    assert observed_identity is not None

    autoreset._remove_lock_dir(lock_path)
    assert autoreset._try_create_lock(lock_path, "fresh-owner", 1_120.0)

    reclaimed = autoreset._reclaim_stale_lock(
        lock_path,
        "reclaimer",
        expected_identity=observed_identity,
        now=1_120.1,
    )

    assert reclaimed is False
    assert autoreset._lock_metadata(lock_path)["owner"] == "fresh-owner"


def test_cooldown_blocks_until_deadline(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    state = {"cooldown_until": 1_060.0, "cooldown_reason": "no_credit"}

    assert store.cooldown_active(state, now=1_059.9)
    assert not store.cooldown_active(state, now=1_060.0)


def test_notice_is_popped_once_for_matching_session(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    assert store.queue_notice("session-a", "reset complete", now=1_000.0)
    assert store.queue_notice("session-b", "other session", now=1_000.0)

    assert store.pop_notice("session-a", now=1_001.0) == "reset complete"
    assert store.pop_notice("session-a", now=1_002.0) is None
    assert store.pop_notice("session-b", now=1_003.0) == "other session"


def test_expired_notice_is_pruned_after_twenty_four_hours(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    assert store.queue_notice("session-a", "expired", now=1_000.0)

    assert (
        store.pop_notice(
            "session-a", now=1_000.0 + autoreset.NOTICE_TTL_SECONDS + 0.1
        )
        is None
    )


def test_empty_session_id_never_leaks_notice_across_sessions(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)

    assert not store.queue_notice("", "must not persist", now=1_000.0)
    assert store.pop_notice("", now=1_001.0) is None
    assert store.pop_notice("another-session", now=1_001.0) is None


def test_notice_stale_snapshot_write_cannot_clobber_pending_state(
    monkeypatch, tmp_path
):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    store.write({"pending": _pending_attempt()})
    stale_state = autoreset.AutoResetStateStore.empty()

    monkeypatch.setattr(store, "load", lambda: stale_state)

    assert store.queue_notice("session-a", "reset complete", now=1_000.0)

    pending = autoreset.AutoResetStateStore(home=tmp_path).load()["pending"]
    assert pending is not None
    assert pending["redeem_request_id"] == "request-uuid"


# --- Synchronous coordinator with stable retry identity -----------------------


def _never(*args, **kwargs):
    raise AssertionError("dependency must not be called on this path")


@contextmanager
def _held(acquired):
    yield acquired


class _LockFactory:
    """Yield a sequence of acquisition results for successive contenders."""

    def __init__(self, *acquired):
        self._acquired = list(acquired) or [True]
        self.calls = 0

    def __call__(self):
        self.calls += 1
        value = self._acquired.pop(0) if self._acquired else False
        return _held(value)


class _Fetcher:
    """Return queued usage snapshots (or raise queued errors) in order."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if not self._responses:
            raise AssertionError("unexpected usage_fetcher call")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _Lister:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.payload


class _Consumer:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def __call__(self, redeem_request_id, credit_id):
        self.calls.append((redeem_request_id, credit_id))
        if self.error is not None:
            raise self.error
        return self.response


class _Uuids:
    def __init__(self, *values):
        self._values = list(values)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self._values.pop(0)


def _valid_credit_list(credit_id="credit-1", expires_at="2026-07-18T00:40:00Z"):
    return _credit_payload(_credit(credit_id, expires_at))


def _seed_pending(store, **overrides):
    pending = {
        "redeem_request_id": "req-1",
        "credit_id": "credit-1",
        "status": "pending",
        "created_at": 900.0,
        "updated_at": 900.0,
        "retry_after": 900.0,
        "before_remaining": 5,
        "before_credits": 2,
    }
    pending.update(overrides)
    store.write({"pending": pending, "notices": {}})


class _ExplodingStore:
    home = None

    def load(self):
        raise autoreset.CorruptStateError("state is unreadable")


def test_disabled_returns_before_any_network_or_state_mutation(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        config=autoreset.AutoResetConfig(enabled=False, threshold=10),
        store=store,
        usage_fetcher=_never,
        credit_lister=_never,
        consumer=_never,
        uuid_factory=_never,
        lock_factory=_never,
        clock=lambda: 1_000.0,
    )

    assert result.status == "disabled"
    assert not store.path.exists()


def test_above_threshold_does_not_lock_or_list_credits(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=50),
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_never,
        credit_lister=_never,
        consumer=_never,
        uuid_factory=_never,
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == "ineligible"
    assert not store.path.exists()


def test_eligible_path_rechecks_usage_inside_lock(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    fetcher = _Fetcher(
        _eligible_usage(remaining=5),
        _eligible_usage(remaining=100, credits=1),
    )
    lister = _Lister(_valid_credit_list())
    consumer = _Consumer(response={"status": "already_redeemed"})

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=fetcher,
        credit_lister=lister,
        consumer=consumer,
        uuid_factory=_Uuids("req-1"),
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == "already_redeemed"
    assert fetcher.calls == 2  # lock-time recheck plus success refresh
    assert lister.calls == 1
    assert consumer.calls == [("req-1", "credit-1")]


def test_recheck_above_threshold_avoids_consume(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    consumer = _Consumer(response={"status": "reset"})

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(_eligible_usage(remaining=80)),
        credit_lister=_never,
        consumer=consumer,
        uuid_factory=_never,
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == "ineligible"
    assert consumer.calls == []


def test_reset_persists_before_post_then_refreshes(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    captured = {}

    def consumer(redeem_request_id, credit_id):
        captured["args"] = (redeem_request_id, credit_id)
        captured["pending"] = store.load()["pending"]
        return {"status": "reset"}

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        session_id="sess-1",
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(
            _eligible_usage(remaining=5),
            _eligible_usage(remaining=100, credits=1),
        ),
        credit_lister=_Lister(_valid_credit_list()),
        consumer=consumer,
        uuid_factory=_Uuids("req-1"),
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert captured["args"] == ("req-1", "credit-1")
    assert captured["pending"]["redeem_request_id"] == "req-1"
    assert captured["pending"]["credit_id"] == "credit-1"
    assert captured["pending"]["status"] == "pending"
    assert result.status == "reset"
    assert result.before_remaining == 5
    assert result.after_remaining == 100
    assert result.after_credits == 1
    assert store.load()["pending"] is None


def test_success_cooldown_blocks_sequential_consume_on_stale_usage(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    consumer = _Consumer(response={"status": "reset"})

    first = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(
            _eligible_usage(remaining=5),
            _eligible_usage(remaining=5),
        ),
        credit_lister=_Lister(_valid_credit_list()),
        consumer=consumer,
        uuid_factory=_Uuids("req-1"),
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )
    second = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_never,
        credit_lister=_never,
        consumer=consumer,
        uuid_factory=_never,
        lock_factory=_never,
        clock=lambda: 1_001.0,
    )

    assert first.status == "reset"
    assert second.status == "cooldown"
    assert consumer.calls == [("req-1", "credit-1")]
    state = store.load()
    assert state["cooldown_reason"] == "success"
    assert state["cooldown_until"] == 1_000.0 + autoreset.COOLDOWN_SUCCESS_SECONDS


def test_post_timeout_preserves_pending_attempt(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    consumer = _Consumer(error=TimeoutError("request timed out"))

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(_eligible_usage(remaining=5)),
        credit_lister=_Lister(_valid_credit_list()),
        consumer=consumer,
        uuid_factory=_Uuids("req-1"),
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == "pending"
    assert len(consumer.calls) == 1  # no generic retry inside one invocation
    pending = store.load()["pending"]
    assert pending["redeem_request_id"] == "req-1"
    assert pending["credit_id"] == "credit-1"
    assert pending["status"] == "pending"
    assert pending["retry_after"] == 1_000.0 + autoreset.COOLDOWN_RETRY_SECONDS


def test_future_retry_after_blocks_without_new_uuid_or_post(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    _seed_pending(store, retry_after=1_060.0)
    uuids = _Uuids("new-request-must-not-be-used")
    lock_factory = _LockFactory(True)

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_never,
        credit_lister=_never,
        consumer=_never,
        uuid_factory=uuids,
        lock_factory=lock_factory,
        clock=lambda: 1_000.0,
    )

    assert result.status == "cooldown"
    assert lock_factory.calls == 0
    assert uuids.calls == 0
    pending = store.load()["pending"]
    assert pending["redeem_request_id"] == "req-1"
    assert pending["credit_id"] == "credit-1"


def test_due_pending_retries_exact_ids_even_when_live_usage_above_threshold(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    _seed_pending(store, retry_after=900.0)
    consumer = _Consumer(response={"status": "already_redeemed"})

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=100, credits=1),
        session_id="sess-retry",
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(
            _eligible_usage(remaining=100, credits=1),
            _eligible_usage(remaining=100, credits=1),
        ),
        credit_lister=_never,
        consumer=consumer,
        uuid_factory=_never,
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == "already_redeemed"
    assert consumer.calls == [("req-1", "credit-1")]
    assert store.load()["pending"] is None


def test_fresh_attempt_waits_until_terminal_response_clears_pending(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    _seed_pending(store, retry_after=900.0)
    first_consumer = _Consumer(response={"status": "already_redeemed"})

    first = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=100, credits=1),
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(
            _eligible_usage(remaining=100, credits=1),
            _eligible_usage(remaining=100, credits=1),
        ),
        credit_lister=_never,
        consumer=first_consumer,
        uuid_factory=_never,
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )
    assert first.status == "already_redeemed"

    consumer = _Consumer(response={"status": "reset"})
    later = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5, credits=1),
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(
            _eligible_usage(remaining=5, credits=1),
            _eligible_usage(remaining=100, credits=0),
        ),
        credit_lister=_Lister(_valid_credit_list("credit-2")),
        consumer=consumer,
        uuid_factory=_Uuids("req-2"),
        lock_factory=_LockFactory(True),
        clock=lambda: 1_301.0,
    )

    assert later.status == "reset"
    assert consumer.calls == [("req-2", "credit-2")]


def test_retry_reuses_same_uuid_and_credit_id(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    _seed_pending(store)
    consumer = _Consumer(response={"status": "already_redeemed"})
    fetcher = _Fetcher(
        _eligible_usage(remaining=5),
        _eligible_usage(remaining=100, credits=1),
    )
    lister = _Lister(_valid_credit_list("credit-OTHER"))
    uuids = _Uuids()

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=fetcher,
        credit_lister=lister,
        consumer=consumer,
        uuid_factory=uuids,
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == "already_redeemed"
    assert consumer.calls == [("req-1", "credit-1")]
    assert uuids.calls == 0
    assert lister.calls == 0
    assert fetcher.calls == 2
    assert store.load()["pending"] is None


def test_already_redeemed_is_successful_terminal(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        session_id="sess-2",
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(
            _eligible_usage(remaining=5),
            _eligible_usage(remaining=100, credits=1),
        ),
        credit_lister=_Lister(_valid_credit_list()),
        consumer=_Consumer(response={"status": "already_redeemed"}),
        uuid_factory=_Uuids("req-1"),
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == "already_redeemed"
    assert result.after_remaining == 100
    assert result.after_credits == 1
    assert store.load()["pending"] is None
    assert store.pop_notice("sess-2", now=1_001.0) is not None


def test_nothing_to_reset_sets_five_minute_cooldown(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(_eligible_usage(remaining=5)),
        credit_lister=_Lister(_valid_credit_list()),
        consumer=_Consumer(response={"status": "nothing_to_reset"}),
        uuid_factory=_Uuids("req-1"),
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == "nothing_to_reset"
    state = store.load()
    assert state["pending"] is None
    assert state["cooldown_until"] == 1_000.0 + autoreset.COOLDOWN_EXHAUSTED_SECONDS
    assert state["cooldown_reason"] == "nothing_to_reset"


def test_no_credit_sets_five_minute_cooldown(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    consumer = _Consumer(response={"status": "reset"})

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(_eligible_usage(remaining=5)),
        credit_lister=_Lister(_credit_payload()),
        consumer=consumer,
        uuid_factory=_Uuids("req-1"),
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == "no_credit"
    assert consumer.calls == []
    state = store.load()
    assert state["cooldown_until"] == 1_000.0 + autoreset.COOLDOWN_EXHAUSTED_SECONDS
    assert state["cooldown_reason"] == "no_credit"


def test_transient_get_failure_sets_one_minute_cooldown(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    consumer = _Consumer(response={"status": "reset"})

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(ConnectionError("usage endpoint unreachable")),
        credit_lister=_never,
        consumer=consumer,
        uuid_factory=_never,
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == "transient"
    assert consumer.calls == []
    state = store.load()
    assert state["cooldown_until"] == 1_000.0 + autoreset.COOLDOWN_RETRY_SECONDS
    assert state["cooldown_reason"] == "transient"


def test_initial_usage_fetch_failure_sets_one_minute_cooldown_and_preserves_state(
    tmp_path,
):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    store.queue_notice("sess-earlier", "earlier notice", now=990.0)

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=None,
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(ConnectionError("usage endpoint unreachable")),
        credit_lister=_never,
        consumer=_never,
        uuid_factory=_never,
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == "transient"
    state = store.load()
    assert state["pending"] is None
    assert state["cooldown_until"] == 1_000.0 + autoreset.COOLDOWN_RETRY_SECONDS
    assert state["cooldown_reason"] == "transient"
    assert store.pop_notice("sess-earlier", now=1_001.0) == "earlier notice"


def _http_status_error(status_code):
    request = httpx.Request("POST", "https://chatgpt.com/backend-api/test")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("backend rejected request", request=request, response=response)


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422])
def test_consume_deterministic_4xx_clears_pending_and_sets_five_minute_cooldown(
    status_code, tmp_path
):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    _seed_pending(store, retry_after=900.0)

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(_eligible_usage(remaining=5)),
        credit_lister=_never,
        consumer=_Consumer(error=_http_status_error(status_code)),
        uuid_factory=_never,
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == "auth_or_validation_error"
    state = store.load()
    assert state["pending"] is None
    assert state["cooldown_until"] == 1_000.0 + autoreset.COOLDOWN_EXHAUSTED_SECONDS
    assert state["cooldown_reason"] == "auth_or_validation_error"


@pytest.mark.parametrize("status_code", [408, 409, 425, 429])
def test_consume_transient_4xx_preserves_pending_for_one_minute(status_code, tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    _seed_pending(store, retry_after=900.0)

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(_eligible_usage(remaining=5)),
        credit_lister=_never,
        consumer=_Consumer(error=_http_status_error(status_code)),
        uuid_factory=_never,
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == "pending"
    pending = store.load()["pending"]
    assert pending["redeem_request_id"] == "req-1"
    assert pending["credit_id"] == "credit-1"
    assert pending["retry_after"] == 1_000.0 + autoreset.COOLDOWN_RETRY_SECONDS


@pytest.mark.parametrize(
    "error",
    [
        httpx.TimeoutException("timed out"),
        httpx.TransportError("connection lost"),
    ],
)
def test_consume_ambiguous_transport_exceptions_preserve_pending_ids(error, tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    _seed_pending(store, retry_after=900.0)

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(_eligible_usage(remaining=5)),
        credit_lister=_never,
        consumer=_Consumer(error=error),
        uuid_factory=_never,
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == "pending"
    pending = store.load()["pending"]
    assert pending["redeem_request_id"] == "req-1"
    assert pending["credit_id"] == "credit-1"
    assert pending["retry_after"] == 1_000.0 + autoreset.COOLDOWN_RETRY_SECONDS


def test_unknown_or_malformed_response_fails_closed(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        session_id="sess-3",
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(_eligible_usage(remaining=5)),
        credit_lister=_Lister(_valid_credit_list()),
        consumer=_Consumer(response={"status": "who-knows"}),
        uuid_factory=_Uuids("req-1"),
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == "unknown"
    assert store.pop_notice("sess-3", now=1_001.0) is None
    pending = store.load()["pending"]
    assert pending is not None
    assert pending["redeem_request_id"] == "req-1"
    assert pending["status"] == "pending"


def test_two_contenders_cause_one_logical_consume(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    consumer = _Consumer(response={"status": "already_redeemed"})
    lock_factory = _LockFactory(True, False)

    def run():
        return autoreset.maybe_autoreset(
            model="gpt-5-codex",
            usage=_eligible_usage(remaining=5),
            config=_enabled_config(threshold=10),
            store=store,
            usage_fetcher=_Fetcher(_eligible_usage(remaining=5)),
            credit_lister=_Lister(_valid_credit_list()),
            consumer=consumer,
            uuid_factory=_Uuids("req-1"),
            lock_factory=lock_factory,
            clock=lambda: 1_000.0,
        )

    first = run()
    second = run()

    assert first.status == "already_redeemed"
    assert second.status == "cooldown"
    assert lock_factory.calls == 1
    assert len(consumer.calls) == 1


def test_success_queues_one_notice_for_session(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        session_id="sess-9",
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(
            _eligible_usage(remaining=5),
            _eligible_usage(remaining=100, credits=1),
        ),
        credit_lister=_Lister(_valid_credit_list()),
        consumer=_Consumer(response={"status": "reset"}),
        uuid_factory=_Uuids("req-1"),
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == "reset"
    assert result.notice_persisted is True
    message = store.pop_notice("sess-9", now=1_001.0)
    assert message is not None
    assert message.startswith("Codex auto reset")
    assert store.pop_notice("sess-9", now=1_002.0) is None


def test_success_uses_locked_fallback_notice_when_notice_lock_is_busy(
    monkeypatch, tmp_path
):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    monkeypatch.setattr(store, "queue_notice", lambda *_args, **_kwargs: False)

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        session_id="sess-fallback",
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(
            _eligible_usage(remaining=5),
            _eligible_usage(remaining=100, credits=1),
        ),
        credit_lister=_Lister(_valid_credit_list()),
        consumer=_Consumer(response={"status": "reset"}),
        uuid_factory=_Uuids("req-fallback"),
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == "reset"
    assert result.notice_persisted is True
    message = store.pop_fallback_notice("sess-fallback", now=1_001.0)
    assert message is not None
    assert message.startswith("Codex auto reset")
    assert store.pop_fallback_notice("sess-fallback", now=1_002.0) is None


def test_hook_facing_api_never_raises(tmp_path):
    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        config=_enabled_config(threshold=10),
        store=_ExplodingStore(),
        usage_fetcher=_Fetcher(_eligible_usage(remaining=5)),
        credit_lister=_Lister(_valid_credit_list()),
        consumer=_Consumer(response={"status": "reset"}),
        uuid_factory=_Uuids("req-1"),
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == "error"


def test_pending_and_cooldown_writes_preserve_existing_notice(tmp_path):
    # Regression for the Task 5 review finding: a load-modify-write update that
    # sets pending/cooldown must not clobber a notice queued for another session.
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    store.queue_notice("sess-earlier", "earlier notice", now=1_000.0)

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(_eligible_usage(remaining=5)),
        credit_lister=_Lister(_credit_payload()),
        consumer=_Consumer(),
        uuid_factory=_Uuids(),
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == "no_credit"
    assert store.cooldown_active(store.load(), now=1_000.0)
    assert store.pop_notice("sess-earlier", now=1_001.0) == "earlier notice"
