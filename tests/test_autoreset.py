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
