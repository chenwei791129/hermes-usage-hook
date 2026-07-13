"""Tests for multi-provider usage detection, normalization, and formatting.

``tests/conftest.py`` puts the repo root on ``sys.path`` so the plugin's
``plugin.usage`` and ``plugin.providers`` modules (which ship under ``plugin/``)
are importable as a package:

    uv run --with pytest --with httpx --with pyyaml python -m pytest tests -v
"""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path

import httpx
import pytest
import yaml

from plugin import autoreset
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
        "rate_limit_reset_credits": {"available_count": 3},
    }

    usage = codex_usage._normalize(raw)

    assert usage["provider"] == "Codex"
    assert usage["plan_type"] == "pro"
    assert usage["windows"]["5h"]["used_percent"] == 42
    assert usage["windows"]["5h"]["remaining_percent"] == 58
    assert usage["reset_credits_available"] == 3


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


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("GPT-5-CODEX", True),
        ("o4-mini", True),
        ("claude-opus-4", False),
        (None, False),
    ],
)
def test_matches_codex_model_is_public_and_case_insensitive(model, expected):
    assert usage.matches_codex_model(model) is expected


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


def test_format_summary_falls_back_to_weekly_when_5h_is_absent():
    usage_dict = {
        "provider": "Codex",
        "plan_type": "plus",
        "reset_credits_available": 3,
        "windows": {
            "weekly": {
                "used_percent": 10,
                "remaining_percent": 90,
                "reset_in_min": 8880,
            }
        },
    }

    assert usage.format_summary(usage_dict) == (
        "Codex weekly | used 10%, left 90% (resets in 6d4h) | plan plus | reset credits 3"
    )


def test_format_summary_includes_zero_reset_credits():
    usage_dict = {
        "provider": "Codex",
        "plan_type": "plus",
        "reset_credits_available": 0,
        "windows": {
            "weekly": {"used_percent": 10, "remaining_percent": 90},
        },
    }

    assert usage.format_summary(usage_dict) == (
        "Codex weekly | used 10%, left 90% | plan plus | reset credits 0"
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


# --- Footer hook failure handling (Failure never breaks the reply) -------------


def test_footer_logs_prefixed_error_and_leaves_reply_unchanged(monkeypatch, capsys):
    def _raise(_model):
        raise RuntimeError("usage fetch exploded")

    monkeypatch.setattr(footer_hook, "get_usage_for_model", _raise)

    result = footer_hook.append_usage_footer("original reply", model="gpt-5-codex")

    # Returning None tells Hermes to keep the reply unchanged.
    assert result is None
    assert "[hermes-usage-hook]" in capsys.readouterr().err


# --- Hook registration and Codex auto-reset integration -----------------------


class _HookContext:
    def __init__(self):
        self.calls = []

    def register_hook(self, hook_name, callback):
        self.calls.append((hook_name, callback))


def _codex_usage(*, remaining=10, credits=3):
    return {
        "provider": "Codex",
        "plan_type": "plus",
        "reset_credits_available": credits,
        "windows": {
            "weekly": {
                "used_percent": 100 - remaining,
                "remaining_percent": remaining,
            }
        },
    }


def test_register_adds_transform_and_pre_llm_hooks_exactly_once():
    ctx = _HookContext()

    footer_hook.register(ctx)

    assert ctx.calls == [
        ("transform_llm_output", footer_hook.append_usage_footer),
        ("pre_llm_call", footer_hook.codex_autoreset_preflight),
    ]


def test_preflight_disabled_returns_none_without_network(monkeypatch):
    calls = []

    def fake_autoreset(**kwargs):
        calls.append(kwargs)
        return autoreset.AutoResetResult("disabled")

    monkeypatch.setattr(footer_hook, "maybe_autoreset", fake_autoreset)

    result = footer_hook.codex_autoreset_preflight(
        model="gpt-5-codex",
        session_id="sess-1",
        turn_id="turn-1",
    )

    assert result is None
    assert len(calls) == 1


def test_preflight_is_synchronous_and_never_injects_prompt_context(monkeypatch):
    monkeypatch.setattr(
        footer_hook,
        "maybe_autoreset",
        lambda **_kwargs: autoreset.AutoResetResult("disabled"),
    )

    assert not inspect.iscoroutinefunction(footer_hook.codex_autoreset_preflight)
    assert footer_hook.codex_autoreset_preflight(model="gpt-5-codex") is None


def test_preflight_passes_session_turn_and_model(monkeypatch):
    captured = {}

    def fake_autoreset(**kwargs):
        captured.update(kwargs)
        return autoreset.AutoResetResult("disabled")

    monkeypatch.setattr(footer_hook, "maybe_autoreset", fake_autoreset)

    footer_hook.codex_autoreset_preflight(
        model="gpt-5-codex",
        session_id="sess-2",
        turn_id="turn-2",
    )

    assert captured == {
        "model": "gpt-5-codex",
        "session_id": "sess-2",
        "turn_id": "turn-2",
    }


def test_footer_passes_existing_usage_to_coordinator(monkeypatch):
    existing_usage = _codex_usage(remaining=50, credits=3)
    captured = {}

    monkeypatch.setattr(footer_hook, "get_usage_for_model", lambda _model: existing_usage)

    def fake_autoreset(**kwargs):
        captured.update(kwargs)
        return autoreset.AutoResetResult("ineligible")

    monkeypatch.setattr(footer_hook, "maybe_autoreset", fake_autoreset)

    footer_hook.append_usage_footer(
        "reply", model="gpt-5-codex", session_id="sess-3"
    )

    assert captured["usage"] is existing_usage
    assert captured["model"] == "gpt-5-codex"
    assert captured["session_id"] == "sess-3"


def test_footer_uses_refreshed_usage_after_reset(monkeypatch):
    monkeypatch.setattr(
        footer_hook,
        "get_usage_for_model",
        lambda _model: _codex_usage(remaining=0, credits=3),
    )
    monkeypatch.setattr(
        footer_hook,
        "maybe_autoreset",
        lambda **_kwargs: autoreset.AutoResetResult(
            "reset",
            after_usage=_codex_usage(remaining=100, credits=2),
            message="Codex auto reset | weekly 0% → 100% | reset credits 3 → 2",
        ),
    )

    result = footer_hook.append_usage_footer(
        "reply", model="gpt-5-codex", session_id="sess-4"
    )

    assert result is not None
    assert "Codex weekly | used 0%, left 100% | plan plus | reset credits 2" in result
    assert "Codex weekly | used 100%, left 0% | plan plus | reset credits 3" not in result


def test_footer_pops_preflight_notice_once(monkeypatch):
    notices = ["Codex auto reset | weekly 0% → 100% | reset credits 3 → 2"]

    class FakeStore:
        def pop_notice(self, session_id):
            assert session_id == "sess-5"
            return notices.pop(0) if notices else None

    monkeypatch.setattr(footer_hook, "get_usage_for_model", lambda _model: _codex_usage())
    monkeypatch.setattr(
        footer_hook,
        "maybe_autoreset",
        lambda **_kwargs: autoreset.AutoResetResult("ineligible"),
    )
    monkeypatch.setattr(footer_hook, "AutoResetStateStore", FakeStore)

    first = footer_hook.append_usage_footer(
        "reply", model="gpt-5-codex", session_id="sess-5"
    )
    second = footer_hook.append_usage_footer(
        "reply", model="gpt-5-codex", session_id="sess-5"
    )

    assert first is not None
    assert first.count("Codex auto reset |") == 1
    assert second is not None
    assert "Codex auto reset |" not in second


def test_footer_triggered_reset_adds_exactly_one_notice(monkeypatch):
    notice = "Codex auto reset | weekly 0% → 100% | reset credits 3 → 2"
    monkeypatch.setattr(
        footer_hook,
        "get_usage_for_model",
        lambda _model: _codex_usage(remaining=0, credits=3),
    )
    monkeypatch.setattr(
        footer_hook,
        "maybe_autoreset",
        lambda **_kwargs: autoreset.AutoResetResult(
            "reset",
            after_usage=_codex_usage(remaining=100, credits=2),
            message=notice,
        ),
    )

    result = footer_hook.append_usage_footer(
        "reply", model="gpt-5-codex", session_id="sess-6"
    )

    assert result is not None
    assert result.count(notice) == 1


@pytest.mark.parametrize(
    "status",
    ["invalid_config", "transient", "pending", "auth_or_validation_error"],
)
def test_footer_never_renders_non_success_autoreset_messages(monkeypatch, status):
    monkeypatch.setattr(footer_hook, "get_usage_for_model", lambda _model: _codex_usage())
    monkeypatch.setattr(
        footer_hook,
        "maybe_autoreset",
        lambda **_kwargs: autoreset.AutoResetResult(
            status,
            message="must not appear in the footer",
        ),
    )

    result = footer_hook.append_usage_footer(
        "reply", model="gpt-5-codex", session_id=""
    )

    assert result is not None
    assert "must not appear" not in result
    assert "Codex auto reset |" not in result


def test_persisted_notice_pop_failure_never_uses_duplicate_message_fallback(monkeypatch):
    notice = "Codex auto reset | weekly 0% → 100% | reset credits 3 → 2"
    pops = [None, notice]
    monkeypatch.setattr(footer_hook, "get_usage_for_model", lambda _model: _codex_usage())
    monkeypatch.setattr(footer_hook, "_pop_notice", lambda _session_id: pops.pop(0))
    monkeypatch.setattr(
        footer_hook,
        "maybe_autoreset",
        lambda **_kwargs: autoreset.AutoResetResult(
            "reset",
            message=notice,
            notice_persisted=True,
        ),
    )

    first = footer_hook.append_usage_footer(
        "reply", model="gpt-5-codex", session_id="sess-lock"
    )
    second = footer_hook.append_usage_footer(
        "reply", model="gpt-5-codex", session_id="sess-lock"
    )

    assert first is not None
    assert notice not in first
    assert second is not None
    assert second.count(notice) == 1


def test_autoreset_failure_keeps_original_reply_and_normal_footer(monkeypatch):
    monkeypatch.setattr(footer_hook, "get_usage_for_model", lambda _model: _codex_usage())

    def exploding_autoreset(**_kwargs):
        raise RuntimeError("coordinator failed")

    monkeypatch.setattr(footer_hook, "maybe_autoreset", exploding_autoreset)

    result = footer_hook.append_usage_footer("reply", model="gpt-5-codex")

    assert result == (
        "reply\n\n───\n"
        "Codex weekly | used 90%, left 10% | plan plus | reset credits 3"
    )


def test_manifest_declares_exactly_two_supported_hooks():
    manifest = yaml.safe_load(Path("plugin/plugin.yaml").read_text())

    assert manifest["provides_hooks"] == ["transform_llm_output", "pre_llm_call"]
    assert "requires_env" not in manifest


def test_readme_documents_codex_autoreset_configuration():
    readme = Path("README.md").read_text()
    required = [
        "plugins.entries.hermes-usage-hook.auto_reset.enabled",
        "plugins.entries.hermes-usage-hook.auto_reset.threshold",
        "CODEX_ENABLE_AUTORESET",
        "CODEX_AUTORESET_THRESHOLD",
        "disabled by default",
        "threshold: 0",
        "0..99",
        "weekly remaining",
        "irreversible",
        "earliest-expiring",
        "idempotent",
        "internal, unstable ChatGPT backend API",
        "OAuth credentials do not belong in plugin config",
        "autoreset-notices.json",
        "autoreset-notices.lock/",
        "env → plugin config → defaults",
        "plugins.entries.<plugin_id>",
        "load_config()",
        "Codex auto reset | weekly 0% → 100% | reset credits 3 → 2",
    ]
    for needle in required:
        assert needle in readme


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


# --- auth.json layout (Hermes provider nesting, credential pool, Codex CLI flat) -------


def _hermes_nested_auth(access_token="access-tok", refresh_token="refresh-tok"):
    """A minimal Hermes-shaped auth.json: credentials nested per-provider."""
    return {
        "version": 1,
        "providers": {
            "openai-codex": {
                "tokens": {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                },
                "last_refresh": "2099-01-01T00:00:00Z",
                "auth_mode": "chatgpt",
            }
        },
        "active_provider": "openai-codex",
    }


def _hermes_credential_pool_auth():
    """A minimal Hermes auth.json with pooled OpenAI Codex credentials."""
    return {
        "version": 2,
        "providers": {},
        "credential_pool": {
            "openai-codex": [
                {
                    "id": "secondary",
                    "priority": 20,
                    "access_token": "secondary-access-tok",
                    "refresh_token": "secondary-refresh-tok",
                },
                {
                    "id": "primary",
                    "priority": 10,
                    "access_token": "pool-access-tok",
                    "refresh_token": "pool-refresh-tok",
                    "account_id": "account-123",
                },
                {
                    "id": "missing-token",
                    "priority": 1,
                    "refresh_token": "ignored-refresh-tok",
                },
            ]
        },
        "active_provider": "openai-codex",
    }


def test_load_auth_reads_hermes_nested_layout(monkeypatch, tmp_path):
    (tmp_path / "auth.json").write_text(json.dumps(_hermes_nested_auth()))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    record = codex_usage._load_auth()

    assert record["tokens"]["access_token"] == "access-tok"
    assert record["tokens"]["refresh_token"] == "refresh-tok"


def test_load_auth_reads_hermes_credential_pool_layout(monkeypatch, tmp_path):
    (tmp_path / "auth.json").write_text(json.dumps(_hermes_credential_pool_auth()))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    record = codex_usage._load_auth()

    assert record["tokens"] == {
        "access_token": "pool-access-tok",
        "refresh_token": "pool-refresh-tok",
        "account_id": "account-123",
    }


def test_load_auth_prefers_hermes_nested_layout_over_credential_pool(
    monkeypatch, tmp_path
):
    auth = _hermes_credential_pool_auth()
    auth["providers"] = _hermes_nested_auth(
        access_token="nested-access-tok",
        refresh_token="nested-refresh-tok",
    )["providers"]
    (tmp_path / "auth.json").write_text(json.dumps(auth))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    record = codex_usage._load_auth()

    assert record["tokens"]["access_token"] == "nested-access-tok"
    assert record["tokens"]["refresh_token"] == "nested-refresh-tok"


def _pool_auth(records):
    """Wrap pooled OpenAI Codex credential records in a Hermes-shaped auth.json."""
    return {
        "version": 2,
        "providers": {},
        "credential_pool": {"openai-codex": records},
        "active_provider": "openai-codex",
    }


# Epoch seconds far enough from now to read as a definite future/past cooldown
# without monkeypatching the clock (year ~2286 vs the Unix epoch + 1s).
_FUTURE_EPOCH = 9_999_999_999
_PAST_EPOCH = 1


def test_load_auth_skips_dead_pool_record(monkeypatch, tmp_path):
    # The highest-priority credential is terminally dead (token invalidated):
    # Hermes drops it from rotation, so the hook must fall through to the next.
    auth = _pool_auth(
        [
            {
                "id": "primary",
                "priority": 10,
                "access_token": "dead-access-tok",
                "last_status": "dead",
            },
            {
                "id": "secondary",
                "priority": 20,
                "access_token": "live-access-tok",
                "last_status": "ok",
            },
        ]
    )
    (tmp_path / "auth.json").write_text(json.dumps(auth))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    record = codex_usage._load_auth()

    assert record["tokens"]["access_token"] == "live-access-tok"


def test_load_auth_skips_exhausted_pool_record_in_cooldown(monkeypatch, tmp_path):
    # Top-priority credential is rate-limited with a reset window still in the
    # future: Hermes runs on the next one, so the hook must too.
    auth = _pool_auth(
        [
            {
                "id": "primary",
                "priority": 10,
                "access_token": "exhausted-access-tok",
                "last_status": "exhausted",
                "last_error_reset_at": _FUTURE_EPOCH,
            },
            {
                "id": "secondary",
                "priority": 20,
                "access_token": "live-access-tok",
                "last_status": "ok",
            },
        ]
    )
    (tmp_path / "auth.json").write_text(json.dumps(auth))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    record = codex_usage._load_auth()

    assert record["tokens"]["access_token"] == "live-access-tok"


def test_load_auth_uses_exhausted_pool_record_after_cooldown(monkeypatch, tmp_path):
    # Once the cooldown has elapsed, Hermes reactivates the credential; the hook
    # keeps honoring priority order and lets the live usage call be the judge.
    auth = _pool_auth(
        [
            {
                "id": "primary",
                "priority": 10,
                "access_token": "recovered-access-tok",
                "last_status": "exhausted",
                "last_error_reset_at": _PAST_EPOCH,
            },
            {
                "id": "secondary",
                "priority": 20,
                "access_token": "live-access-tok",
                "last_status": "ok",
            },
        ]
    )
    (tmp_path / "auth.json").write_text(json.dumps(auth))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    record = codex_usage._load_auth()

    assert record["tokens"]["access_token"] == "recovered-access-tok"


def test_load_auth_reads_flat_codex_cli_layout(monkeypatch, tmp_path):
    flat = {"tokens": {"access_token": "flat-tok"}, "last_refresh": "x"}
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    (tmp_path / "auth.json").write_text(json.dumps(flat))

    assert codex_usage._load_auth() == flat


def test_get_codex_usage_reads_nested_hermes_layout(monkeypatch, tmp_path):
    (tmp_path / "auth.json").write_text(json.dumps(_hermes_nested_auth()))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    captured = {}

    def _fake_call(access_token, account_id):
        captured["access_token"] = access_token
        return {
            "rate_limit": {
                "primary_window": {
                    "used_percent": 12,
                    "reset_at": None,
                    "limit_window_seconds": codex_usage.WINDOW_5H,
                }
            },
            "plan_type": "pro",
        }

    monkeypatch.setattr(codex_usage, "_call_usage", _fake_call)

    usage = codex_usage.get_codex_usage()

    # The access token is read straight from the nested record (the module never
    # refreshes the token).
    assert captured["access_token"] == "access-tok"
    assert usage["provider"] == "Codex"
    assert usage["windows"]["5h"]["used_percent"] == 12


def test_get_codex_usage_reads_credential_pool_layout(monkeypatch, tmp_path):
    (tmp_path / "auth.json").write_text(json.dumps(_hermes_credential_pool_auth()))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    captured = {}

    def _fake_call(access_token, account_id):
        captured["access_token"] = access_token
        captured["account_id"] = account_id
        return {
            "rate_limit": {
                "primary_window": {
                    "used_percent": 34,
                    "reset_at": None,
                    "limit_window_seconds": codex_usage.WINDOW_5H,
                }
            },
            "plan_type": "plus",
        }

    monkeypatch.setattr(codex_usage, "_call_usage", _fake_call)

    usage = codex_usage.get_codex_usage()

    assert captured == {
        "access_token": "pool-access-tok",
        "account_id": "account-123",
    }
    assert usage["provider"] == "Codex"
    assert usage["windows"]["5h"]["used_percent"] == 34


# --- Codex rate-limit reset credit transport (offline only) -------------------


def _mock_codex_transport(monkeypatch, handler, *, account_id="account-123"):
    real_client = httpx.Client
    monkeypatch.setattr(
        codex_usage,
        "_load_auth",
        lambda: {
            "tokens": {
                "access_token": "secret-access-token",
                "account_id": account_id,
            }
        },
    )
    monkeypatch.setattr(
        codex_usage.httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )


def test_list_reset_credits_uses_get_endpoint_and_active_auth(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"available_count": 2})

    _mock_codex_transport(monkeypatch, handler)

    assert codex_usage.list_rate_limit_reset_credits() == {"available_count": 2}
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert str(requests[0].url) == codex_usage.RESET_CREDITS_URL
    assert requests[0].headers["Authorization"] == "Bearer secret-access-token"


def test_consume_reset_credit_posts_stable_identifiers(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"status": "reset"})

    _mock_codex_transport(monkeypatch, handler)

    result = codex_usage.consume_rate_limit_reset_credit("request-uuid", "credit-1")

    assert result == {"status": "reset"}
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert str(requests[0].url) == codex_usage.CONSUME_RESET_CREDIT_URL
    assert json.loads(requests[0].content) == {
        "redeem_request_id": "request-uuid",
        "credit_id": "credit-1",
    }


def test_consume_omits_credit_id_only_when_none(monkeypatch):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"status": "reset"})

    _mock_codex_transport(monkeypatch, handler)

    codex_usage.consume_rate_limit_reset_credit("request-without-credit", None)
    codex_usage.consume_rate_limit_reset_credit("request-with-empty-credit", "")

    assert bodies == [
        {"redeem_request_id": "request-without-credit"},
        {"redeem_request_id": "request-with-empty-credit", "credit_id": ""},
    ]


@pytest.mark.parametrize("operation", ["list", "consume"])
def test_reset_transport_sends_chatgpt_account_header_when_present(
    monkeypatch, operation
):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={})

    _mock_codex_transport(monkeypatch, handler, account_id="active-account")

    if operation == "list":
        codex_usage.list_rate_limit_reset_credits()
    else:
        codex_usage.consume_rate_limit_reset_credit("request-uuid", "credit-1")

    assert requests[0].headers["ChatGPT-Account-Id"] == "active-account"


@pytest.mark.parametrize("status_code", [401, 429, 500, 503])
@pytest.mark.parametrize("operation", ["list", "consume"])
def test_reset_transport_raises_on_401_429_and_5xx(
    monkeypatch, status_code, operation
):
    def handler(request):
        return httpx.Response(status_code, json={"error": "rejected"})

    _mock_codex_transport(monkeypatch, handler)

    with pytest.raises(httpx.HTTPStatusError):
        if operation == "list":
            codex_usage.list_rate_limit_reset_credits()
        else:
            codex_usage.consume_rate_limit_reset_credit("request-uuid", "credit-1")


def test_reset_transport_does_not_retry_post(monkeypatch):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"error": "try later"})

    _mock_codex_transport(monkeypatch, handler)

    with pytest.raises(httpx.HTTPStatusError):
        codex_usage.consume_rate_limit_reset_credit("stable-uuid", "credit-1")

    assert calls == 1


def test_provider_errors_do_not_include_bearer_token(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"error": "unauthorized"})

    _mock_codex_transport(monkeypatch, handler)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        codex_usage.list_rate_limit_reset_credits()

    assert "secret-access-token" not in str(exc_info.value)
    assert "Bearer" not in str(exc_info.value)
