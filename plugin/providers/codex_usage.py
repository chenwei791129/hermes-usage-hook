#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27"]
# ///
"""Fetch Codex (ChatGPT-backed) rate-limit usage.

Reads the Codex OAuth credentials from ``$HERMES_HOME/auth.json`` when running
as a Hermes plugin (where Hermes keeps them under ``providers/openai-codex`` or
newer ``credential_pool.openai-codex`` records), falling back to the Codex CLI's
flat ``$CODEX_HOME/auth.json`` / ``~/.codex/auth.json`` for standalone use; all
layouts are supported. Queries the usage endpoint codexbar uses, returning a
normalized view of the 5-hour and weekly rate-limit windows.

This module never refreshes or writes back the token: the credential store may
be Hermes' own live store, and rotating the refresh token out from under Hermes
could break the deployment's login. It only reads the access token. If that
token is expired, the usage call fails and the hook simply omits the footer
(Hermes owns the token lifecycle and keeps it fresh).

Run standalone for a quick check:

    uv run plugin/providers/codex_usage.py
    # or, if httpx is already installed:
    python plugin/providers/codex_usage.py
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"

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
# module consumes the Codex record (the dict carrying ``tokens``), so normalize
# both layouts to that record on load.
_HERMES_CODEX_PROVIDER = "openai-codex"

# ``last_status`` values Hermes writes onto a pooled credential. ``dead`` is a
# terminal server-side failure (token invalidated/revoked); ``exhausted`` is a
# rate-limit/billing cooldown gated by ``last_error_reset_at``.
_POOL_STATUS_DEAD = "dead"
_POOL_STATUS_EXHAUSTED = "exhausted"


def _pool_record_usable(record: dict) -> bool:
    """Whether a ``credential_pool`` record is one Hermes would still select.

    Mirrors Hermes' own rotation (``agent.credential_pool``): it excludes
    ``dead`` credentials unconditionally and ``exhausted`` ones whose cooldown
    window (``last_error_reset_at``) has not yet elapsed. Picking a credential
    Hermes has retired would query the usage endpoint with a stale/invalid token
    and show the wrong account (or silently drop the footer) while Hermes runs
    on a healthy lower-priority credential.

    For ``exhausted`` records with no recorded reset time we fall through and
    let the live usage call be the source of truth, rather than replicating
    Hermes' error-code-based TTL fallback.
    """
    if not isinstance(record, dict) or not record.get("access_token"):
        return False
    status = record.get("last_status")
    if status == _POOL_STATUS_DEAD:
        return False
    if status == _POOL_STATUS_EXHAUSTED:
        reset_at = record.get("last_error_reset_at")
        if isinstance(reset_at, (int, float)) and reset_at > time.time():
            return False
    return True


def _codex_record(raw: dict) -> dict:
    """Return the Codex credential record from supported auth.json layouts.

    Hermes may nest credentials under ``providers/openai-codex`` or store a
    prioritized credential list under ``credential_pool/openai-codex``. The Codex
    CLI keeps ``tokens`` at the top level. Return a normalized dict carrying
    ``tokens`` in all cases.
    """
    providers = raw.get("providers")
    if isinstance(providers, dict) and isinstance(
        providers.get(_HERMES_CODEX_PROVIDER), dict
    ):
        return providers[_HERMES_CODEX_PROVIDER]

    pool = raw.get("credential_pool")
    pool_records = pool.get(_HERMES_CODEX_PROVIDER) if isinstance(pool, dict) else None
    if isinstance(pool_records, list):
        usable_records = [
            record for record in pool_records if _pool_record_usable(record)
        ]
        if usable_records:
            record = sorted(
                usable_records,
                key=lambda item: item.get("priority", 100),
            )[0]
            return {
                "tokens": {
                    "access_token": record.get("access_token"),
                    "refresh_token": record.get("refresh_token"),
                    "account_id": record.get("account_id"),
                }
            }

    return raw


def _load_auth() -> dict:
    return _codex_record(json.loads(_auth_path().read_text()))


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
    """Return normalized Codex usage from the stored access token.

    Synchronous on purpose: the ``transform_llm_output`` hook consumes the
    result as a plain string, so the fetch must run inline. Async hooks call
    this via ``asyncio.to_thread`` to avoid blocking the event loop.

    Reads the access token as-is and never refreshes it (see the module
    docstring). Raises on unrecoverable errors (missing auth.json, network
    failure, an HTTP error including an expired/rejected token). Callers running
    inside a hook should wrap this in a try/except so a failure never breaks the
    agent — an expired token then just omits the footer.
    """
    auth = _load_auth()
    tokens = auth.get("tokens", {})
    access_token = tokens.get("access_token") or auth.get("OPENAI_API_KEY")
    if not access_token:
        raise RuntimeError("auth.json has no usable access token")
    account_id = tokens.get("account_id")

    raw = _call_usage(access_token, account_id)
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
