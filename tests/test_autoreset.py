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
