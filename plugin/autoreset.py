"""Configuration and coordination primitives for Codex auto reset."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module

from .usage import matches_codex_model

PLUGIN_ID = "hermes-usage-hook"
ENV_ENABLED = "CODEX_ENABLE_AUTORESET"
ENV_THRESHOLD = "CODEX_AUTORESET_THRESHOLD"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True)
class AutoResetConfig:
    """Effective auto-reset settings, including fail-closed validation state."""

    enabled: bool
    threshold: int
    valid: bool = True
    error: str | None = None


def _load_hermes_config() -> dict:
    """Load Hermes config lazily so standalone tests need no Hermes runtime."""
    try:
        config_module = import_module("hermes_cli.config")
    except ImportError:
        return {}
    loaded = config_module.load_config() or {}
    return loaded if isinstance(loaded, dict) else {}


def _invalid(error: str) -> AutoResetConfig:
    return AutoResetConfig(enabled=False, threshold=0, valid=False, error=error)


def _plugin_autoreset(config: dict) -> dict:
    plugins = config.get("plugins")
    if plugins is None:
        return {}
    if not isinstance(plugins, dict):
        raise ValueError("plugins must be a mapping")

    entries = plugins.get("entries")
    if entries is None:
        return {}
    if not isinstance(entries, dict):
        raise ValueError("plugins.entries must be a mapping")

    entry = entries.get(PLUGIN_ID)
    if entry is None:
        return {}
    if not isinstance(entry, dict):
        raise ValueError(f"plugins.entries.{PLUGIN_ID} must be a mapping")

    auto_reset = entry.get("auto_reset")
    if auto_reset is None:
        return {}
    if not isinstance(auto_reset, dict):
        raise ValueError(
            f"plugins.entries.{PLUGIN_ID}.auto_reset must be a mapping"
        )
    return auto_reset


def _parse_env_boolean(value: object) -> bool:
    if not isinstance(value, str):
        raise ValueError(f"{ENV_ENABLED} must be a string boolean")
    normalized = value.strip().casefold()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(f"{ENV_ENABLED} has an invalid boolean value")


def _parse_env_threshold(value: object) -> int:
    if not isinstance(value, str):
        raise ValueError(f"{ENV_THRESHOLD} must be an integer string")
    normalized = value.strip()
    if not normalized.isdecimal():
        raise ValueError(f"{ENV_THRESHOLD} must be an integer from 0 to 99")
    threshold = int(normalized)
    if threshold > 99:
        raise ValueError(f"{ENV_THRESHOLD} must be an integer from 0 to 99")
    return threshold


def _parse_plugin_boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("plugin auto_reset.enabled must be a boolean")
    return value


def _parse_plugin_threshold(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("plugin auto_reset.threshold must be an integer from 0 to 99")
    if not 0 <= value <= 99:
        raise ValueError("plugin auto_reset.threshold must be an integer from 0 to 99")
    return value


def load_autoreset_config(
    *, env: Mapping[str, str] | None = None, config: dict | None = None
) -> AutoResetConfig:
    """Resolve env overrides, canonical plugin config, then safe defaults.

    Explicit invalid values fail closed instead of falling through to a
    lower-precedence source.
    """
    source_env: Mapping[str, str] = os.environ if env is None else env
    source_config = _load_hermes_config() if config is None else config

    try:
        plugin = _plugin_autoreset(source_config)

        if ENV_ENABLED in source_env:
            enabled = _parse_env_boolean(source_env[ENV_ENABLED])
        elif "enabled" in plugin:
            enabled = _parse_plugin_boolean(plugin["enabled"])
        else:
            enabled = False

        if ENV_THRESHOLD in source_env:
            threshold = _parse_env_threshold(source_env[ENV_THRESHOLD])
        elif "threshold" in plugin:
            threshold = _parse_plugin_threshold(plugin["threshold"])
        else:
            threshold = 0
    except (TypeError, ValueError) as exc:
        return _invalid(str(exc))

    return AutoResetConfig(enabled=enabled, threshold=threshold)


def weekly_remaining(usage: dict) -> int | float | None:
    """Return only the normalized weekly remaining percentage, never a proxy."""
    windows = usage.get("windows")
    if not isinstance(windows, dict):
        return None
    weekly = windows.get("weekly")
    if not isinstance(weekly, dict):
        return None
    remaining = weekly.get("remaining_percent")
    if isinstance(remaining, bool) or not isinstance(remaining, (int, float)):
        return None
    if not 0 <= remaining <= 100:
        return None
    return remaining


def is_eligible(*, model: str | None, usage: dict, config: AutoResetConfig) -> bool:
    """Evaluate pure Codex weekly reset eligibility without side effects."""
    if not config.valid or not config.enabled or not matches_codex_model(model):
        return False
    if (
        isinstance(config.threshold, bool)
        or not isinstance(config.threshold, int)
        or not 0 <= config.threshold <= 99
    ):
        return False
    remaining = weekly_remaining(usage)
    if remaining is None:
        return False
    credit_count = usage.get("reset_credits_available")
    if isinstance(credit_count, bool) or not isinstance(credit_count, int):
        return False
    return credit_count > 0 and remaining <= config.threshold


def _parse_expiry(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("credit expiry must be an ISO-8601 string or null")
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("credit expiry must include a timezone")
    return parsed.astimezone(timezone.utc)


def select_earliest_available_credit(payload: dict) -> dict | None:
    """Choose the usable available credit with the earliest real expiry."""
    available_count = payload.get("available_count")
    if (
        isinstance(available_count, bool)
        or not isinstance(available_count, int)
        or available_count <= 0
    ):
        return None
    credits = payload.get("credits")
    if not isinstance(credits, list):
        return None

    candidates: list[tuple[bool, datetime, dict]] = []
    for row in credits:
        if not isinstance(row, dict) or row.get("status") != "available":
            continue
        credit_id = row.get("id")
        if not isinstance(credit_id, str) or not credit_id:
            continue
        try:
            expiry = _parse_expiry(row.get("expires_at"))
        except (TypeError, ValueError, OverflowError):
            continue
        candidates.append(
            (
                expiry is None,
                expiry or datetime.max.replace(tzinfo=timezone.utc),
                row,
            )
        )

    if not candidates:
        return None
    return min(candidates, key=lambda candidate: candidate[:2])[2]
