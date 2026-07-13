"""Tests for fail-closed Codex auto-reset configuration resolution."""

from __future__ import annotations

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
