"""Tests for fail-closed Codex auto-reset configuration resolution."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os

import httpx
import pytest

from plugin import autoreset
from plugin import autoreset_audit
from plugin.autoreset_audit import AutoResetAuditLog, audit_event_id, build_success_event


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


def _audit_event(**overrides):
    values = {
        "redeem_request_id": "request-uuid",
        "observed_at": 1_000.0,
        "backend_status": "reset",
        "trigger": "pre_llm_call",
        "before_remaining": 0,
        "after_remaining": 100,
        "before_credits": 3,
        "after_credits": 2,
    }
    values.update(overrides)
    return build_success_event(**values)


def test_v040_state_without_audit_outbox_loads_unchanged(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    old_state = {
        "version": autoreset.STATE_VERSION,
        "pending": _pending_attempt(),
        "cooldown_until": 1_060.0,
        "cooldown_reason": "transient",
        "fallback_notices": {
            "sess-old": {"message": "old notice", "created_at": 999.0}
        },
    }
    store.path.parent.mkdir(parents=True)
    store.path.write_text(json.dumps(old_state), encoding="utf-8")

    assert store.load() == old_state
    assert autoreset.STATE_VERSION == 1


def test_valid_audit_outbox_round_trips_without_raw_ids(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    event = _audit_event()

    store.write({"pending": None, "audit_outbox": event})

    assert store.load()["audit_outbox"] == event
    serialized = store.path.read_text(encoding="utf-8")
    assert "request-uuid" not in serialized
    assert "redeem_request_id" not in serialized
    assert autoreset.STATE_VERSION == 1


def test_invalid_audit_outbox_is_removed_fail_closed(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    invalid = {**_audit_event(), "event_id": "raw-request-id"}

    store.write({"pending": _pending_attempt(), "audit_outbox": invalid})

    state = store.load()
    assert "audit_outbox" not in state
    assert state["pending"] == _pending_attempt()
    assert "raw-request-id" not in store.path.read_text(encoding="utf-8")


def test_state_write_filters_extra_outbox_keys(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    event = {**_audit_event(), "redeem_request_id": "must-not-persist"}

    store.write({"pending": None, "audit_outbox": event})

    state = store.load()
    assert state["audit_outbox"] == _audit_event()
    assert "redeem_request_id" not in state["audit_outbox"]
    assert "must-not-persist" not in store.path.read_text(encoding="utf-8")


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


class _AuditLog:
    def __init__(self, *, order=None, error=None):
        self.order = order
        self.error = error
        self.events = []
        self.attempted_event_ids = []
        self.event_ids = set()

    def append_once(self, event):
        if self.order is not None:
            self.order.append("append")
        event_id = event["event_id"]
        self.attempted_event_ids.append(event_id)
        if self.error is not None:
            raise self.error
        if event_id in self.event_ids:
            return False
        self.event_ids.add(event_id)
        self.events.append(json.loads(json.dumps(event)))
        return True


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


def _persist_raw_pending(store, **overrides):
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
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps({"version": 1, "pending": pending}), encoding="utf-8"
    )


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


@pytest.mark.parametrize(
    ("config", "model", "expected_status"),
    [
        (
            autoreset.AutoResetConfig(enabled=False, threshold=10),
            "gpt-5-codex",
            "disabled",
        ),
        (
            autoreset.AutoResetConfig(
                enabled=False, threshold=0, valid=False, error="bad config"
            ),
            "gpt-5-codex",
            "invalid_config",
        ),
        (_enabled_config(threshold=10), "claude-sonnet", "not_codex"),
    ],
)
def test_existing_outbox_drains_before_eligibility_exit(
    config, model, expected_status, tmp_path
):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    event = _audit_event(redeem_request_id=f"{expected_status}-event")
    store.write({"pending": None, "audit_outbox": event})
    audit_log = _AuditLog()

    result = autoreset.maybe_autoreset(
        model=model,
        usage=_eligible_usage(remaining=5),
        audit_log=audit_log,
        config=config,
        store=store,
        usage_fetcher=_never,
        credit_lister=_never,
        consumer=_never,
        uuid_factory=_never,
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == expected_status
    assert audit_log.events == [event]
    assert store.load()["audit_outbox"] is None


@pytest.mark.parametrize(
    ("config", "model"),
    [
        (autoreset.AutoResetConfig(enabled=False, threshold=10), "gpt-5-codex"),
        (
            autoreset.AutoResetConfig(
                enabled=False, threshold=0, valid=False, error="bad config"
            ),
            "gpt-5-codex",
        ),
        (_enabled_config(threshold=10), "claude-sonnet"),
    ],
)
def test_failed_outbox_drain_blocks_eligibility_exit_without_network(
    config, model, tmp_path
):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    event = _audit_event(redeem_request_id="blocked-exit")
    store.write({"pending": None, "audit_outbox": event})

    result = autoreset.maybe_autoreset(
        model=model,
        usage=_eligible_usage(remaining=5),
        audit_log=_AuditLog(error=OSError("audit unavailable")),
        config=config,
        store=store,
        usage_fetcher=_never,
        credit_lister=_never,
        consumer=_never,
        uuid_factory=_never,
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result == autoreset.AutoResetResult(
        "error", message="auto-reset audit is pending"
    )
    assert store.load()["audit_outbox"] == event


@pytest.mark.parametrize(
    "clock_value",
    [
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive-infinity"),
        pytest.param(10**100, id="unrepresentable"),
    ],
)
def test_invalid_clock_fails_before_network_or_state_transition(clock_value, tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    fetcher = _Fetcher(
        _eligible_usage(remaining=5),
        _eligible_usage(remaining=100, credits=1),
    )
    lister = _Lister(_valid_credit_list())
    consumer = _Consumer(response={"status": "reset"})
    lock_factory = _LockFactory(True)

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=fetcher,
        credit_lister=lister,
        consumer=consumer,
        uuid_factory=_Uuids("req-invalid-clock"),
        lock_factory=lock_factory,
        clock=lambda: clock_value,
    )

    assert result == autoreset.AutoResetResult(
        "error", message="auto-reset clock is invalid"
    )
    assert fetcher.calls == 0
    assert lister.calls == 0
    assert consumer.calls == []
    assert lock_factory.calls == 0
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


def test_existing_clean_state_and_supplied_ineligible_usage_avoid_transport(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    store.write(autoreset.AutoResetStateStore.empty())
    state_before = store.path.read_bytes()

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=50, credits=2),
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_never,
        credit_lister=_never,
        consumer=_never,
        uuid_factory=_never,
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result == autoreset.AutoResetResult(
        "ineligible", before_remaining=50, before_credits=2
    )
    assert store.path.read_bytes() == state_before


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


@pytest.mark.parametrize(
    "credit_count",
    [
        pytest.param(-1, id="negative"),
        pytest.param(True, id="bool"),
        pytest.param("1", id="string"),
        pytest.param(1.5, id="float"),
    ],
)
def test_invalid_refreshed_credit_count_cannot_strand_success(
    credit_count, tmp_path
):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    audit_log = _AuditLog()
    consumer = _Consumer(response={"status": "reset"})

    first = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        session_id="sess-invalid-after",
        trigger="pre_llm_call",
        audit_log=audit_log,
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(
            _eligible_usage(remaining=5),
            {
                **_eligible_usage(remaining=100),
                "reset_credits_available": credit_count,
            },
        ),
        credit_lister=_Lister(_valid_credit_list()),
        consumer=consumer,
        uuid_factory=_Uuids("req-invalid-after"),
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )
    second = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        audit_log=audit_log,
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_never,
        credit_lister=_never,
        consumer=consumer,
        uuid_factory=_never,
        lock_factory=_LockFactory(True),
        clock=lambda: 1_001.0,
    )

    assert first.status == "reset"
    assert first.after_credits is None
    assert second.status == "cooldown"
    assert consumer.calls == [("req-invalid-after", "credit-1")]
    assert store.load()["pending"] is None
    assert audit_log.events == [
        {
            "schema_version": 1,
            "event_type": "codex_autoreset_succeeded",
            "event_id": audit_event_id("req-invalid-after"),
            "observed_at": "1970-01-01T00:16:40Z",
            "backend_status": "reset",
            "trigger": "pre_llm_call",
            "before": {"weekly_remaining_percent": 5, "reset_credits": 2},
            "after": {
                "weekly_remaining_percent": 100,
                "reset_credits": None,
            },
        }
    ]


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
        lock_factory=_LockFactory(True),
        clock=lambda: 1_001.0,
    )

    assert first.status == "reset"
    assert second.status == "cooldown"
    assert consumer.calls == [("req-1", "credit-1")]
    state = store.load()
    assert state["cooldown_reason"] == "success"
    assert state["cooldown_until"] == 1_000.0 + autoreset.COOLDOWN_SUCCESS_SECONDS


def test_default_audit_drain_allows_success_then_cooldown_with_injected_store(
    tmp_path,
):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    consumer = _Consumer(response={"status": "reset"})

    first = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(
            _eligible_usage(remaining=5),
            _eligible_usage(remaining=100, credits=1),
        ),
        credit_lister=_Lister(_valid_credit_list()),
        consumer=consumer,
        uuid_factory=_Uuids("req-default-audit"),
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
        lock_factory=_LockFactory(True),
        clock=lambda: 1_001.0,
    )

    events, malformed = AutoResetAuditLog(home=tmp_path).read_events()
    assert first.status == "reset"
    assert second.status == "cooldown"
    assert malformed == 0
    assert [event["event_id"] for event in events] == [
        audit_event_id("req-default-audit")
    ]
    assert consumer.calls == [("req-default-audit", "credit-1")]


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
    assert lock_factory.calls == 1
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


@pytest.mark.parametrize(
    ("before_remaining", "before_credits"),
    [
        pytest.param("5", "2", id="strings"),
        pytest.param(True, False, id="bools"),
        pytest.param(float("nan"), -1, id="nonfinite-negative"),
        pytest.param(float("inf"), 2.5, id="nonfinite-non-int"),
    ],
)
def test_malformed_persisted_pending_snapshots_normalize_before_retry(
    before_remaining, before_credits, tmp_path
):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    _persist_raw_pending(
        store,
        before_remaining=before_remaining,
        before_credits=before_credits,
    )
    assert store.load()["pending"]["before_remaining"] is None
    assert store.load()["pending"]["before_credits"] is None
    audit_log = _AuditLog()
    consumed_snapshots = []

    def consumer(redeem_request_id, credit_id):
        consumed_snapshots.append(store.load()["pending"])
        assert (redeem_request_id, credit_id) == ("req-1", "credit-1")
        return {"status": "already_redeemed"}

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=100, credits=1),
        session_id="sess-malformed-before",
        trigger="transform_llm_output",
        audit_log=audit_log,
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

    assert len(consumed_snapshots) == 1
    assert consumed_snapshots[0]["before_remaining"] is None
    assert consumed_snapshots[0]["before_credits"] is None
    assert result.status == "already_redeemed"
    assert result.before_remaining is None
    assert result.before_credits is None
    assert result.message == (
        "Codex auto reset | reset already redeemed; usage refresh unavailable"
    )
    assert store.load()["pending"] is None
    assert store.pop_fallback_notice("sess-malformed-before", now=1_001.0) == (
        "Codex auto reset | reset already redeemed; usage refresh unavailable"
    )
    assert audit_log.events == [
        {
            "schema_version": 1,
            "event_type": "codex_autoreset_succeeded",
            "event_id": audit_event_id("req-1"),
            "observed_at": "1970-01-01T00:16:40Z",
            "backend_status": "already_redeemed",
            "trigger": "transform_llm_output",
            "before": {
                "weekly_remaining_percent": None,
                "reset_credits": None,
            },
            "after": {"weekly_remaining_percent": 100, "reset_credits": 1},
        }
    ]


def test_valid_persisted_pending_snapshots_are_preserved_in_exact_success_event(
    tmp_path,
):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    _persist_raw_pending(store, before_remaining=5.5, before_credits=2)
    audit_log = _AuditLog()
    consumer = _Consumer(response={"status": "already_redeemed"})

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=100, credits=1),
        session_id="sess-valid-before",
        trigger="transform_llm_output",
        audit_log=audit_log,
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(
            _eligible_usage(remaining=100, credits=1),
            _eligible_usage(remaining=87, credits=1),
        ),
        credit_lister=_never,
        consumer=consumer,
        uuid_factory=_never,
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == "already_redeemed"
    assert consumer.calls == [("req-1", "credit-1")]
    assert audit_log.events == [
        {
            "schema_version": 1,
            "event_type": "codex_autoreset_succeeded",
            "event_id": audit_event_id("req-1"),
            "observed_at": "1970-01-01T00:16:40Z",
            "backend_status": "already_redeemed",
            "trigger": "transform_llm_output",
            "before": {"weekly_remaining_percent": 5.5, "reset_credits": 2},
            "after": {"weekly_remaining_percent": 87, "reset_credits": 1},
        }
    ]


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
    assert store.pop_fallback_notice("sess-2", now=1_001.0) is not None


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


@pytest.mark.parametrize(
    "status_value",
    [
        pytest.param([], id="list"),
        pytest.param({}, id="dict"),
        pytest.param(None, id="null"),
        pytest.param(True, id="bool"),
        pytest.param(7, id="number"),
    ],
)
def test_non_string_post_consume_status_uses_unknown_cooldown_without_leakage(
    status_value, tmp_path, caplog
):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    raw_secret = "prompt-body-must-not-leak"

    with caplog.at_level("WARNING"):
        result = autoreset.maybe_autoreset(
            model="gpt-5-codex",
            usage=_eligible_usage(remaining=5),
            config=_enabled_config(threshold=10),
            store=store,
            usage_fetcher=_Fetcher(_eligible_usage(remaining=5)),
            credit_lister=_Lister(_valid_credit_list()),
            consumer=_Consumer(
                response={"status": status_value, "prompt": raw_secret}
            ),
            uuid_factory=_Uuids("req-non-string-status"),
            lock_factory=_LockFactory(True),
            clock=lambda: 1_000.0,
        )

    state = store.load()
    assert result.status == "unknown"
    assert result.message is None
    assert state["pending"] is None
    assert state["cooldown_reason"] == "unknown"
    assert state["cooldown_until"] == (
        1_000.0 + autoreset.COOLDOWN_EXHAUSTED_SECONDS
    )
    assert raw_secret not in caplog.text
    assert raw_secret not in repr(result)


class _SequenceClock:
    def __init__(self, *values):
        self.values = list(values)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.values.pop(0)


@pytest.mark.parametrize("status", ["reset", "already_redeemed"])
def test_success_observed_at_is_sampled_after_terminal_response(status, tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    audit_log = _AuditLog()
    clock = _SequenceClock(1_000.0, 1_234.5)

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        audit_log=audit_log,
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(
            _eligible_usage(remaining=5),
            _eligible_usage(remaining=100, credits=1),
        ),
        credit_lister=_Lister(_valid_credit_list()),
        consumer=_Consumer(response={"status": status}),
        uuid_factory=_Uuids("req-observation-clock"),
        lock_factory=_LockFactory(True),
        clock=clock,
    )

    assert result.status == status
    assert audit_log.events[0]["observed_at"] == "1970-01-01T00:20:34.500000Z"
    assert clock.calls == 2


@pytest.mark.parametrize(
    "invalid_terminal_time",
    [float("nan"), float("inf"), True, "bad", 10**100],
)
def test_invalid_terminal_clock_falls_back_without_stranding_success(
    invalid_terminal_time, tmp_path
):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    audit_log = _AuditLog()
    clock = _SequenceClock(1_000.0, invalid_terminal_time)

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        audit_log=audit_log,
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(
            _eligible_usage(remaining=5),
            _eligible_usage(remaining=100, credits=1),
        ),
        credit_lister=_Lister(_valid_credit_list()),
        consumer=_Consumer(response={"status": "reset"}),
        uuid_factory=_Uuids("req-clock-fallback"),
        lock_factory=_LockFactory(True),
        clock=clock,
    )

    assert result.status == "reset"
    assert audit_log.events[0]["observed_at"] == "1970-01-01T00:16:40Z"
    assert store.load()["pending"] is None
    assert clock.calls == 2


def test_two_contenders_cause_one_logical_consume(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    consumer = _Consumer(response={"status": "already_redeemed"})
    lock_factory = _LockFactory(True, True)

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
    assert lock_factory.calls == 2
    assert len(consumer.calls) == 1


def test_success_atomically_queues_one_notice_for_session(tmp_path):
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
    message = store.pop_fallback_notice("sess-9", now=1_001.0)
    assert message is not None
    assert message.startswith("Codex auto reset")
    assert store.pop_fallback_notice("sess-9", now=1_002.0) is None


def test_terminal_success_write_atomically_contains_audit_notice(monkeypatch, tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    writes = []
    queue_calls = []
    real_write = store.write

    def recording_write(state):
        writes.append(json.loads(json.dumps(state)))
        real_write(state)

    def forbidden_separate_queue(*args, **kwargs):
        queue_calls.append((args, kwargs))
        raise AssertionError("success notice must use the terminal state write")

    monkeypatch.setattr(store, "write", recording_write)
    monkeypatch.setattr(store, "queue_notice", forbidden_separate_queue)

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        session_id="sess-atomic",
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(
            _eligible_usage(remaining=5),
            _eligible_usage(remaining=100, credits=1),
        ),
        credit_lister=_Lister(_valid_credit_list()),
        consumer=_Consumer(response={"status": "reset"}),
        uuid_factory=_Uuids("req-atomic"),
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    terminal_writes = [
        state
        for state in writes
        if state.get("cooldown_reason") == "success"
        and state.get("audit_outbox") is not None
    ]
    assert result.status == "reset"
    assert result.notice_persisted is True
    assert queue_calls == []
    assert len(terminal_writes) == 1
    assert terminal_writes[0]["pending"] is None
    assert terminal_writes[0]["fallback_notices"]["sess-atomic"][
        "message"
    ].startswith("Codex auto reset")


def test_failed_atomic_terminal_write_preserves_pending_for_safe_retry(
    monkeypatch, tmp_path
):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    first_consumer = _Consumer(response={"status": "reset"})
    real_write = store.write

    def fail_terminal_write(state):
        if state.get("cooldown_reason") == "success":
            raise OSError("simulated crash before atomic replace")
        real_write(state)

    monkeypatch.setattr(store, "write", fail_terminal_write)
    first = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        session_id="sess-recover",
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(
            _eligible_usage(remaining=5),
            _eligible_usage(remaining=100, credits=1),
        ),
        credit_lister=_Lister(_valid_credit_list()),
        consumer=first_consumer,
        uuid_factory=_Uuids("req-recover"),
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert first.status == "error"
    pending = store.load()["pending"]
    assert pending["redeem_request_id"] == "req-recover"
    assert pending["credit_id"] == "credit-1"
    assert store.pop_fallback_notice("sess-recover", now=1_000.5) is None

    monkeypatch.setattr(store, "write", real_write)
    retry_consumer = _Consumer(response={"status": "already_redeemed"})
    retry = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        session_id="sess-recover",
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(
            _eligible_usage(remaining=100, credits=1),
            _eligible_usage(remaining=100, credits=1),
        ),
        credit_lister=_never,
        consumer=retry_consumer,
        uuid_factory=_never,
        lock_factory=_LockFactory(True),
        clock=lambda: 1_001.0,
    )

    assert retry.status == "already_redeemed"
    assert retry_consumer.calls == [("req-recover", "credit-1")]
    assert store.load()["pending"] is None
    assert store.pop_fallback_notice("sess-recover", now=1_002.0) is not None


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


# --- Durable audit outbox crash windows --------------------------------------


def _run_success(store, audit_log, *, status="reset", trigger="pre_llm_call"):
    return autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        session_id="sess-audit",
        trigger=trigger,
        audit_log=audit_log,
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(
            _eligible_usage(remaining=5),
            _eligible_usage(remaining=100, credits=1),
        ),
        credit_lister=_Lister(_valid_credit_list()),
        consumer=_Consumer(response={"status": status}),
        uuid_factory=_Uuids("req-audit"),
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )


def test_success_terminal_write_contains_outbox_notice_cooldown_and_no_pending(
    monkeypatch, tmp_path
):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    order = []
    writes = []
    real_write = store.write

    def recording_write(state):
        snapshot = json.loads(json.dumps(state))
        writes.append(snapshot)
        if snapshot.get("cooldown_reason") == "success":
            order.append("terminal_write")
        real_write(state)

    monkeypatch.setattr(store, "write", recording_write)
    audit_log = _AuditLog(order=order)

    result = _run_success(store, audit_log)

    terminal = next(
        state
        for state in writes
        if state.get("cooldown_reason") == "success"
        and state.get("audit_outbox") is not None
    )
    assert result.status == "reset"
    assert terminal["pending"] is None
    assert terminal["cooldown_until"] == 1_000.0 + autoreset.COOLDOWN_SUCCESS_SECONDS
    assert terminal["fallback_notices"]["sess-audit"]["message"].startswith(
        "Codex auto reset"
    )
    assert terminal["audit_outbox"]["event_id"] == audit_event_id("req-audit")
    assert order[:2] == ["terminal_write", "append"]


def test_outbox_is_appended_then_cleared_after_success(monkeypatch, tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    order = []
    real_write = store.write

    def recording_write(state):
        if (
            state.get("cooldown_reason") == "success"
            and state.get("audit_outbox") is None
        ):
            order.append("clear_write")
        real_write(state)

    monkeypatch.setattr(store, "write", recording_write)
    audit_log = _AuditLog(order=order)

    result = _run_success(store, audit_log)

    assert result.status == "reset"
    assert len(audit_log.events) == 1
    assert order == ["append", "clear_write"]
    assert store.load()["audit_outbox"] is None


def test_append_failure_preserves_outbox_and_still_returns_reset(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    audit_log = _AuditLog(error=OSError("audit unavailable"))

    result = _run_success(store, audit_log)

    assert result.status == "reset"
    assert store.load()["audit_outbox"]["event_id"] == audit_event_id("req-audit")
    assert store.pop_fallback_notice("sess-audit", now=1_001.0) is not None


def test_crash_after_append_before_clear_dedups_then_clears(monkeypatch, tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    audit_log = _AuditLog()
    real_write = store.write

    def crash_on_clear(state):
        if (
            state.get("cooldown_reason") == "success"
            and state.get("audit_outbox") is None
        ):
            raise OSError("simulated crash before outbox clear")
        real_write(state)

    monkeypatch.setattr(store, "write", crash_on_clear)
    first = _run_success(store, audit_log)
    assert first.status == "reset"
    assert store.load()["audit_outbox"] is not None

    monkeypatch.setattr(store, "write", real_write)
    second = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        audit_log=audit_log,
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_never,
        credit_lister=_never,
        consumer=_never,
        uuid_factory=_never,
        lock_factory=_LockFactory(True),
        clock=lambda: 1_001.0,
    )

    assert second.status == "cooldown"
    assert audit_log.attempted_event_ids == [
        audit_event_id("req-audit"),
        audit_event_id("req-audit"),
    ]
    assert [event["event_id"] for event in audit_log.events] == [
        audit_event_id("req-audit")
    ]
    assert store.load()["audit_outbox"] is None


def test_existing_outbox_drains_before_any_usage_or_credit_network_call(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    store.write({"pending": None, "audit_outbox": _audit_event()})
    order = []
    audit_log = _AuditLog(order=order)

    def fetch_usage():
        order.append("usage")
        return _eligible_usage(remaining=100)

    def list_credits():
        order.append("credits")
        return {}

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        audit_log=audit_log,
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=fetch_usage,
        credit_lister=list_credits,
        consumer=lambda *_args: order.append("consume"),
        uuid_factory=_never,
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == "ineligible"
    assert order == ["append", "usage"]
    assert store.load()["audit_outbox"] is None


def test_unresolved_outbox_prevents_new_consume(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    event = _audit_event()
    store.write({"pending": None, "audit_outbox": event})
    consumer = _Consumer(response={"status": "reset"})

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        audit_log=_AuditLog(error=OSError("audit unavailable")),
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_never,
        credit_lister=_never,
        consumer=consumer,
        uuid_factory=_never,
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result == autoreset.AutoResetResult(
        "error", message="auto-reset audit is pending"
    )
    assert consumer.calls == []
    assert store.load()["audit_outbox"] == event


def test_repeated_audit_fsync_failure_keeps_outbox_and_retries_sync(
    monkeypatch, tmp_path
):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    event = _audit_event(redeem_request_id="durability-retry")
    store.write({"pending": None, "audit_outbox": event})
    audit_log = AutoResetAuditLog(home=tmp_path)
    real_fsync = os.fsync
    audit_syncs = 0

    def fail_audit_fsync(descriptor):
        nonlocal audit_syncs
        if (
            audit_log.path.exists()
            and os.fstat(descriptor).st_ino == audit_log.path.stat().st_ino
        ):
            audit_syncs += 1
            raise OSError("audit fsync unavailable")
        return real_fsync(descriptor)

    monkeypatch.setattr(autoreset_audit.os, "fsync", fail_audit_fsync)

    for _ in range(2):
        result = autoreset.maybe_autoreset(
            model="gpt-5-codex",
            usage=_eligible_usage(remaining=5),
            audit_log=audit_log,
            config=autoreset.AutoResetConfig(enabled=False, threshold=10),
            store=store,
            usage_fetcher=_never,
            credit_lister=_never,
            consumer=_never,
            uuid_factory=_never,
            lock_factory=_LockFactory(True),
            clock=lambda: 1_000.0,
        )
        assert result == autoreset.AutoResetResult(
            "error", message="auto-reset audit is pending"
        )
        assert store.load()["audit_outbox"] == event

    assert audit_syncs == 2
    assert audit_log.path.read_bytes().count(b"\n") == 1
    assert audit_log.read_events() == ([event], 0)


def test_concurrent_outbox_is_drained_before_initial_usage_fetch(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    event = _audit_event()
    order = []
    lister = _Lister(_valid_credit_list())
    consumer = _Consumer(response={"status": "reset"})

    # Simulate a stale observation followed by an outside coordinator writing
    # the outbox immediately before this coordinator acquires its lock.
    assert store.load().get("audit_outbox") is None

    @contextmanager
    def acquire_after_outside_write():
        store.write({"pending": None, "audit_outbox": event})
        yield True

    def fetch_usage():
        order.append("usage")
        return _eligible_usage(remaining=5)

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=None,
        audit_log=_AuditLog(order=order, error=OSError("audit unavailable")),
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=fetch_usage,
        credit_lister=lister,
        consumer=consumer,
        uuid_factory=_never,
        lock_factory=lambda: acquire_after_outside_write(),
        clock=lambda: 1_000.0,
    )

    assert result == autoreset.AutoResetResult(
        "error", message="auto-reset audit is pending"
    )
    assert order == ["append"]
    assert lister.calls == 0
    assert consumer.calls == []
    assert store.load()["audit_outbox"] == event


def test_audit_drain_warning_omits_event_and_exception_details(caplog, tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    event = _audit_event()
    store.write({"pending": None, "audit_outbox": event})
    sensitive_detail = "raw-audit-backend-secret"

    with caplog.at_level("WARNING", logger="plugin.autoreset"):
        result = autoreset.maybe_autoreset(
            model="gpt-5-codex",
            usage=_eligible_usage(remaining=5),
            audit_log=_AuditLog(error=OSError(sensitive_detail)),
            config=_enabled_config(threshold=10),
            store=store,
            usage_fetcher=_never,
            credit_lister=_never,
            consumer=_never,
            uuid_factory=_never,
            lock_factory=_LockFactory(True),
            clock=lambda: 1_000.0,
        )

    assert result == autoreset.AutoResetResult(
        "error", message="auto-reset audit is pending"
    )
    assert [record.getMessage() for record in caplog.records] == [
        "auto-reset audit outbox drain failed"
    ]
    assert sensitive_detail not in caplog.text
    assert event["event_id"] not in caplog.text


def test_already_redeemed_uses_same_hashed_event_id(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    _seed_pending(store, redeem_request_id="persisted-request", retry_after=900.0)
    audit_log = _AuditLog()

    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        trigger="transform_llm_output",
        audit_log=audit_log,
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(
            _eligible_usage(remaining=100, credits=1),
            _eligible_usage(remaining=100, credits=1),
        ),
        credit_lister=_never,
        consumer=_Consumer(response={"status": "already_redeemed"}),
        uuid_factory=_never,
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == "already_redeemed"
    assert audit_log.events[0]["event_id"] == audit_event_id("persisted-request")
    assert audit_log.events[0]["backend_status"] == "already_redeemed"
    assert audit_log.events[0]["trigger"] == "transform_llm_output"


def test_invalid_trigger_cannot_strand_success_or_repeat_consume(tmp_path):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    audit_log = _AuditLog()
    consumer = _Consumer(response={"status": "reset"})

    first = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        trigger="unsupported-external-trigger",
        audit_log=audit_log,
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(
            _eligible_usage(remaining=5),
            _eligible_usage(remaining=100, credits=1),
        ),
        credit_lister=_Lister(_valid_credit_list()),
        consumer=consumer,
        uuid_factory=_Uuids("req-invalid-trigger"),
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )
    second = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        audit_log=audit_log,
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(
            _eligible_usage(remaining=5),
            _eligible_usage(remaining=100, credits=1),
        ),
        credit_lister=_never,
        consumer=consumer,
        uuid_factory=_never,
        lock_factory=_LockFactory(True),
        clock=lambda: 1_001.0,
    )

    assert first.status == "reset"
    assert second.status == "cooldown"
    assert consumer.calls == [("req-invalid-trigger", "credit-1")]
    assert audit_log.events[0]["trigger"] == "unknown"
    state = store.load()
    assert state["pending"] is None
    assert state["audit_outbox"] is None


@pytest.mark.parametrize("status", ["nothing_to_reset", "no_credit", "unexpected"])
def test_non_success_outcomes_never_build_or_append_audit_event(
    status, monkeypatch, tmp_path
):
    store = autoreset.AutoResetStateStore(home=tmp_path, clock=lambda: 1_000.0)
    audit_log = _AuditLog()

    def forbidden_build(**_kwargs):
        raise AssertionError("non-success outcome built an audit event")

    monkeypatch.setattr(autoreset, "build_success_event", forbidden_build)
    result = autoreset.maybe_autoreset(
        model="gpt-5-codex",
        usage=_eligible_usage(remaining=5),
        audit_log=audit_log,
        config=_enabled_config(threshold=10),
        store=store,
        usage_fetcher=_Fetcher(_eligible_usage(remaining=5)),
        credit_lister=_Lister(_valid_credit_list()),
        consumer=_Consumer(response={"status": status}),
        uuid_factory=_Uuids("req-non-success"),
        lock_factory=_LockFactory(True),
        clock=lambda: 1_000.0,
    )

    assert result.status == ("unknown" if status == "unexpected" else status)
    assert audit_log.events == []
