#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27"]
# ///
"""Fetch Codex (ChatGPT-backed) rate-limit usage.

Reads the Codex OAuth credentials from ``$HERMES_HOME/auth.json`` when running
as a Hermes plugin (where Hermes keeps them, nested per-provider under
``providers/openai-codex``), falling back to the Codex CLI's flat
``$CODEX_HOME/auth.json`` / ``~/.codex/auth.json`` for standalone use; both
layouts are supported. Queries the usage endpoint codexbar uses, returning a
normalized view of the
5-hour and weekly rate-limit windows. Refreshes the access token when stale or
rejected, persisting the new token back to ``auth.json``.

Run standalone for a quick check:

    uv run plugin/providers/codex_usage.py
    # or, if httpx is already installed:
    python plugin/providers/codex_usage.py
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

# Public Codex OAuth client id, identical to the one the Codex CLI ships with.
OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
TOKEN_URL = "https://auth.openai.com/oauth/token"
USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"

# Codex marks a stored token stale after roughly 8 days; refresh before that.
REFRESH_AFTER_DAYS = 8
HTTP_TIMEOUT = 30.0

# Window lengths used to label rate-limit buckets (seconds).
WINDOW_5H = 18_000
WINDOW_WEEKLY = 604_800


def _auth_path() -> Path:
    """Locate auth.json.

    Prefer Hermes' own credential store (``$HERMES_HOME/auth.json``) when it
    exists: running as a Hermes plugin, that is where the active Codex OAuth
    credential lives (Hermes does not populate the Codex CLI's ``~/.codex``).
    Fall back to the Codex CLI location (``$CODEX_HOME/auth.json``, else
    ``~/.codex/auth.json``) for standalone use.
    """
    hermes_home = os.environ.get("HERMES_HOME")
    if hermes_home:
        hermes_auth = Path(hermes_home) / "auth.json"
        if hermes_auth.is_file():
            return hermes_auth
    home = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    return Path(home) / "auth.json"


# Hermes stores per-provider credentials nested under ``providers/<name>``,
# while the standalone Codex CLI uses a flat top-level layout. The rest of this
# module consumes the Codex record (the dict carrying ``tokens``/``last_refresh``),
# so normalize both layouts to that record on load and write it back into the
# right slot on save.
_HERMES_CODEX_PROVIDER = "openai-codex"


def _codex_record(raw: dict) -> dict:
    """Return the Codex credential record from either auth.json layout.

    Hermes nests it under ``providers/openai-codex`` (alongside ``last_refresh``
    and ``auth_mode``); the Codex CLI keeps ``tokens``/``last_refresh`` at the
    top level. Returns the sub-dict carrying ``tokens`` in both cases.
    """
    providers = raw.get("providers")
    if isinstance(providers, dict) and isinstance(
        providers.get(_HERMES_CODEX_PROVIDER), dict
    ):
        return providers[_HERMES_CODEX_PROVIDER]
    return raw


def _load_auth() -> dict:
    return _codex_record(json.loads(_auth_path().read_text()))


def _save_auth(auth: dict) -> None:
    """Persist the Codex record, preserving the on-disk auth.json layout.

    Re-reads the file so a refreshed token is spliced back into Hermes' nested
    ``providers/openai-codex`` slot, leaving other providers and top-level fields
    intact; a flat Codex-CLI file is written back as-is.
    """
    path = _auth_path()
    raw = json.loads(path.read_text())
    providers = raw.get("providers")
    if isinstance(providers, dict) and isinstance(
        providers.get(_HERMES_CODEX_PROVIDER), dict
    ):
        providers[_HERMES_CODEX_PROVIDER] = auth
    else:
        raw = auth
    path.write_text(json.dumps(raw, indent=2))


def _needs_refresh(auth: dict) -> bool:
    """True when the stored token is missing a timestamp or older than the cap."""
    last = auth.get("last_refresh")
    if not last:
        return True
    try:
        ts = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).days >= REFRESH_AFTER_DAYS


def _refresh(auth: dict) -> dict:
    """Exchange the refresh token for a fresh access token and persist it."""
    tokens = auth.get("tokens", {})
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("auth.json has no refresh_token; run `codex login` again")

    body = {
        "client_id": OAUTH_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": "openid profile email",
    }
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.post(
            TOKEN_URL, json=body, headers={"Content-Type": "application/json"}
        )
        resp.raise_for_status()
        new = resp.json()

    # Keep prior values for any field the refresh response omits.
    tokens["access_token"] = new.get("access_token", tokens.get("access_token"))
    tokens["refresh_token"] = new.get("refresh_token", tokens.get("refresh_token"))
    if new.get("id_token"):
        tokens["id_token"] = new["id_token"]
    auth["tokens"] = tokens
    auth["last_refresh"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _save_auth(auth)
    return auth


def _call_usage(access_token: str, account_id: str | None) -> dict:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "hermes-usage-hook",
    }
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.get(USAGE_URL, headers=headers)
        resp.raise_for_status()
        return resp.json()


def _label_window(seconds: int) -> str:
    if seconds == WINDOW_5H:
        return "5h"
    if seconds == WINDOW_WEEKLY:
        return "weekly"
    return f"{seconds}s"


def _normalize(raw: dict) -> dict:
    """Reduce the raw usage payload to the fields a notifier needs."""
    rate_limit = raw.get("rate_limit") or {}
    windows: dict[str, dict] = {}
    for snap in (rate_limit.get("primary_window"), rate_limit.get("secondary_window")):
        if not snap:
            continue
        used = snap.get("used_percent", 0)
        reset_at = snap.get("reset_at")
        windows[_label_window(snap.get("limit_window_seconds", 0))] = {
            "used_percent": used,
            "remaining_percent": 100 - used,
            "reset_at": reset_at,
            "reset_in_min": (
                max(0, round((reset_at - time.time()) / 60)) if reset_at else None
            ),
        }
    credits = raw.get("credits") or {}
    return {
        "provider": "Codex",
        "plan_type": raw.get("plan_type"),
        "windows": windows,
        "credits_balance": credits.get("balance"),
    }


def get_codex_usage() -> dict:
    """Return normalized Codex usage, refreshing the token when needed.

    Synchronous on purpose: the ``transform_llm_output`` hook consumes the
    result as a plain string, so the fetch must run inline. Async hooks call
    this via ``asyncio.to_thread`` to avoid blocking the event loop.

    Raises on unrecoverable errors (missing auth.json, network failure, a
    non-auth HTTP error). Callers running inside a hook should wrap this in a
    try/except so a failure never breaks the agent.
    """
    auth = _load_auth()
    # Only OAuth credentials can be refreshed; API-key-only auth.json has no
    # refresh_token, so skip the refresh path entirely for it.
    can_refresh = bool(auth.get("tokens", {}).get("refresh_token"))
    if can_refresh and _needs_refresh(auth):
        auth = _refresh(auth)

    tokens = auth.get("tokens", {})
    access_token = tokens.get("access_token") or auth.get("OPENAI_API_KEY")
    if not access_token:
        raise RuntimeError("auth.json has no usable access token")
    account_id = tokens.get("account_id")

    try:
        raw = _call_usage(access_token, account_id)
    except httpx.HTTPStatusError as exc:
        # A stale token can still slip past the age check; refresh once and retry.
        if exc.response.status_code in (401, 403) and can_refresh:
            auth = _refresh(auth)
            access_token = auth["tokens"]["access_token"]
            raw = _call_usage(access_token, account_id)
        else:
            raise
    return _normalize(raw)


def _handle_sigterm(signum, frame):
    raise SystemExit(128 + signum)


if __name__ == "__main__":
    import signal
    import sys

    # Add the repo root so ``plugin`` is importable as a package, letting the
    # deferred import resolve ``usage`` with package context (its ``.providers``
    # relative import needs a parent package). Deferred to avoid a cycle: usage
    # imports this module at top level.
    _repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    sys.path.insert(0, _repo_root)
    from plugin.usage import format_summary

    signal.signal(signal.SIGTERM, _handle_sigterm)
    try:
        result = get_codex_usage()
        print(json.dumps(result, indent=2))
        print(format_summary(result))
    except KeyboardInterrupt:
        raise SystemExit(130)  # 128 + SIGINT(2)
