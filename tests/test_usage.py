"""Tests for multi-provider usage detection, normalization, and formatting.

Run from the repo root so the flat modules are importable:

    uv run --with pytest --with httpx python -m pytest tests/test_usage.py -v
"""

from __future__ import annotations

import pytest

import codex_usage
import minimax_usage
import usage


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


# --- Summary formatting (Render a provider-labeled usage summary) --------------


def test_format_summary_codex_includes_plan():
    codex = {
        "provider": "Codex",
        "plan_type": "pro",
        "windows": {
            "5h": {"used_percent": 42, "remaining_percent": 58, "reset_in_min": 137}
        },
    }

    assert (
        usage.format_summary(codex)
        == "Codex 5h | used 42%, left 58% (resets in 137 min) | plan pro"
    )


def test_format_summary_minimax_omits_plan():
    minimax = {
        "provider": "MiniMax",
        "plan_type": None,
        "windows": {
            "5h": {"used_percent": 4, "remaining_percent": 96, "reset_in_min": 281}
        },
    }

    assert (
        usage.format_summary(minimax)
        == "MiniMax 5h | used 4%, left 96% (resets in 281 min)"
    )


def test_format_summary_reports_missing_window():
    assert "unavailable" in usage.format_summary(
        {"provider": "Codex", "plan_type": None, "windows": {}}
    )


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
