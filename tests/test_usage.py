"""Tests for multi-provider usage detection, normalization, and formatting.

``tests/conftest.py`` puts the repo root on ``sys.path`` so the plugin's
``plugin.usage`` and ``plugin.providers`` modules (which ship under ``plugin/``)
are importable as a package:

    uv run --with pytest --with httpx --with pyyaml python -m pytest tests -v
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from plugin import usage
from plugin.hooks import footer_hook
from plugin.providers import codex_usage, minimax_usage


def test_codex_normalize_tags_provider():
    raw = {
        "rate_limit": {
            "primary_window": {
                "used_percent": 42,
                "reset_at": None,
                "limit_window_seconds": codex_usage.WINDOW_5H,
            },
            "secondary_window": {
                "used_percent": 10,
                "reset_at": None,
                "limit_window_seconds": codex_usage.WINDOW_WEEKLY,
            },
        },
        "plan_type": "pro",
        "credits": {"balance": 5},
    }

    usage = codex_usage._normalize(raw)

    assert usage["provider"] == "Codex"
    assert usage["plan_type"] == "pro"
    assert usage["windows"]["5h"]["used_percent"] == 42
    assert usage["windows"]["5h"]["remaining_percent"] == 58


# --- MiniMax token resolution (Resolve the MiniMax API token) -----------------


def test_token_from_environment_skips_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "env-token")
    # Point HERMES_HOME at a dir with no .env to prove the file is not read.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    assert minimax_usage._resolve_token() == "env-token"


def test_token_from_hermes_home_env_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / ".env").write_text('OTHER=ignored\nMINIMAX_API_KEY="file-token"\n')

    assert minimax_usage._resolve_token() == "file-token"


def test_token_missing_everywhere_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))  # no .env file here

    with pytest.raises(Exception):
        minimax_usage._resolve_token()


# --- MiniMax normalization (Normalize the MiniMax token-plan response) ---------


def _minimax_general_payload():
    return {
        "base_resp": {"status_code": 0, "status_msg": "success"},
        "model_remains": [
            {
                "model_name": "general",
                "current_interval_remaining_percent": 96,
                "remains_time": 616664,
                "current_weekly_remaining_percent": 100,
                "weekly_remains_time": 483016664,
            }
        ],
    }


def test_minimax_normalize_general_entry():
    usage = minimax_usage._normalize(_minimax_general_payload())

    assert usage["provider"] == "MiniMax"
    assert usage["plan_type"] is None
    assert usage["windows"]["5h"] == {
        "used_percent": 4,
        "remaining_percent": 96,
        "reset_in_min": 10,
    }
    assert usage["windows"]["weekly"] == {
        "used_percent": 0,
        "remaining_percent": 100,
        "reset_in_min": 8050,
    }


def test_minimax_normalize_rejects_nonzero_status():
    payload = _minimax_general_payload()
    payload["base_resp"]["status_code"] = 1004

    with pytest.raises(Exception):
        minimax_usage._normalize(payload)


def test_minimax_normalize_rejects_missing_general():
    payload = _minimax_general_payload()
    payload["model_remains"][0]["model_name"] = "abab6.5s"

    with pytest.raises(Exception):
        minimax_usage._normalize(payload)


# --- Provider detection (Detect provider from the response model name) ---------


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-5-codex", "Codex"),
        ("o3-mini", "Codex"),
        ("MiniMax-M2.5", "MiniMax"),
        ("abab6.5s-chat", "MiniMax"),
        ("claude-opus-4", None),
        (None, None),
    ],
)
def test_match_provider_mapping(model, expected):
    assert usage._match_provider(model) == expected


def test_get_usage_for_model_dispatches_to_matched_provider(monkeypatch):
    sentinel = {"provider": "MiniMax", "plan_type": None, "windows": {}}
    monkeypatch.setattr(minimax_usage, "get_minimax_usage", lambda: sentinel)

    assert usage.get_usage_for_model("MiniMax-M2.5") is sentinel


def test_get_usage_for_model_returns_none_when_unmatched():
    assert usage.get_usage_for_model("claude-opus-4") is None
    assert usage.get_usage_for_model(None) is None


# --- Duration formatting (shared duration formatter) ---------------------------


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        (0, "0m"),
        (45, "45m"),
        (90, "1h30m"),
        (137, "2h17m"),
        (8640, "6d"),
        (8880, "6d4h"),
    ],
)
def test_format_duration_mapping(minutes, expected):
    assert usage._format_duration(minutes) == expected


# --- Summary formatting (Render a provider-labeled usage summary) --------------


def test_format_summary_codex_includes_plan():
    codex = {
        "provider": "Codex",
        "plan_type": "pro",
        "windows": {
            "5h": {"used_percent": 42, "remaining_percent": 58, "reset_in_min": 137},
            "weekly": {
                "used_percent": 10,
                "remaining_percent": 90,
                "reset_in_min": 8880,
            },
        },
    }

    assert usage.format_summary(codex) == (
        "Codex 5h | used 42%, left 58% (resets in 2h17m) | plan pro\n"
        "Codex weekly | used 10%, left 90% (resets in 6d4h)"
    )


def test_format_summary_minimax_omits_plan():
    minimax = {
        "provider": "MiniMax",
        "plan_type": None,
        "windows": {
            "5h": {"used_percent": 4, "remaining_percent": 96, "reset_in_min": 281},
            "weekly": {
                "used_percent": 30,
                "remaining_percent": 70,
                "reset_in_min": 8640,
            },
        },
    }

    assert usage.format_summary(minimax) == (
        "MiniMax 5h | used 4%, left 96% (resets in 4h41m)\n"
        "MiniMax weekly | used 30%, left 70% (resets in 6d)"
    )


def test_format_summary_weekly_absent_renders_only_5h():
    usage_dict = {
        "provider": "Codex",
        "plan_type": "pro",
        "windows": {
            "5h": {"used_percent": 42, "remaining_percent": 58, "reset_in_min": 137}
        },
    }

    assert (
        usage.format_summary(usage_dict)
        == "Codex 5h | used 42%, left 58% (resets in 2h17m) | plan pro"
    )


def test_format_summary_reports_missing_window():
    usage_dict = {
        "provider": "Codex",
        "plan_type": None,
        # A weekly window must not leak through when 5h is unavailable.
        "windows": {"weekly": {"used_percent": 10, "remaining_percent": 90}},
    }

    assert usage.format_summary(usage_dict) == "Codex usage: 5h window unavailable"


def test_format_summary_omits_reset_clause_when_unknown():
    # Codex _normalize sets reset_in_min to None when reset_at is absent; the
    # summary must not render the literal "(resets in None min)".
    usage_dict = {
        "provider": "Codex",
        "plan_type": "pro",
        "windows": {
            "5h": {"used_percent": 42, "remaining_percent": 58, "reset_in_min": None}
        },
    }

    assert (
        usage.format_summary(usage_dict) == "Codex 5h | used 42%, left 58% | plan pro"
    )


# --- Footer hook failure handling (Failure never breaks the reply) -------------


def test_footer_logs_prefixed_error_and_leaves_reply_unchanged(monkeypatch, capsys):
    def _raise(_model):
        raise RuntimeError("usage fetch exploded")

    monkeypatch.setattr(footer_hook, "get_usage_for_model", _raise)

    result = footer_hook.append_usage_footer("original reply", model="gpt-5-codex")

    # Returning None tells Hermes to keep the reply unchanged.
    assert result is None
    assert "[hermes-usage-hook]" in capsys.readouterr().err


# --- Codex auth.json location (prefer Hermes' store, fall back to Codex CLI) ----


def test_auth_path_prefers_hermes_home_when_file_exists(monkeypatch, tmp_path):
    # As a Hermes plugin, $HERMES_HOME/auth.json (where Hermes keeps the Codex
    # OAuth credential) wins over the Codex CLI location, even if CODEX_HOME is set.
    auth = tmp_path / "auth.json"
    auth.write_text("{}")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", "/nonexistent/codex/home")

    assert codex_usage._auth_path() == auth


def test_auth_path_falls_back_to_codex_home_when_hermes_file_absent(
    monkeypatch, tmp_path
):
    # HERMES_HOME is set but has no auth.json, so the Codex CLI location is used.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    codex_home = tmp_path / "codex"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    assert codex_usage._auth_path() == codex_home / "auth.json"


def test_auth_path_uses_codex_home_when_hermes_home_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("HERMES_HOME", raising=False)
    codex_home = tmp_path / "codex"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    assert codex_usage._auth_path() == codex_home / "auth.json"


def test_auth_path_defaults_to_user_codex_dir(monkeypatch):
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)

    assert (
        codex_usage._auth_path() == Path(os.path.expanduser("~/.codex")) / "auth.json"
    )
