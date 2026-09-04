#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27"]
# ///
"""Fetch Codex (ChatGPT-backed) rate-limit usage and reset-credit APIs.

Reads the Codex OAuth credentials from ``$HERMES_HOME/auth.json`` when running
as a Hermes plugin (where Hermes keeps them under ``providers/openai-codex`` or
newer ``credential_pool.openai-codex`` records), falling back to the Codex CLI's
flat ``$CODEX_HOME/auth.json`` / ``~/.codex/auth.json`` for standalone use; all
layouts are supported. Queries the usage endpoint codexbar uses, returning a
normalized view of the 5-hour and weekly rate-limit windows.

The reset-credit list and consume helpers also call internal, unstable ChatGPT
backend API endpoints. They are transport-only wrappers: the auto-reset
coordinator owns opt-in config, earliest-expiry selection, cooldowns,
idempotency, and persisted redeem request IDs. ``consume_rate_limit_reset_credit``
therefore never generates IDs and never retries POSTs.

This module never refreshes or writes back the token: the credential store may
be Hermes' own live store, and rotating the refresh token out from under Hermes
could break the deployment's login. It only reads the access token. If that
token is expired, the usage call fails and the hook simply omits the footer
(Hermes owns the token lifecycle and keeps it fresh). OAuth credentials do not
belong in plugin config or auto-reset state.

Run standalone for a quick check:

    uv run plugin/providers/codex_usage.py
    # or, if httpx is already installed:
    python plugin/providers/codex_usage.py
"""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

import httpx

USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
RESET_CREDITS_URL = "https://chatgpt.com/backend-api/wham/rate-limit-reset-credits"
CONSUME_RESET_CREDIT_URL = f"{RESET_CREDITS_URL}/consume"

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


# Priority applied to a pooled record whose ``priority`` is missing or not a
# usable number. Ranking must never compare a raw value against this default:
# a ``null`` priority would raise TypeError and abort resolution.
_DEFAULT_POOL_PRIORITY = 100


def _pool_record_selectable(record: object) -> bool:
    """Whether a ``credential_pool`` record may be selected at all.

    Excludes records that carry no usable token and ``dead`` ones: Hermes
    writes ``dead`` when the credential was invalidated server-side, so every
    call with it would be rejected and demoting it could not help.
    """
    if not isinstance(record, dict):
        return False
    access_token = record.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        return False
    return record.get("last_status") != _POOL_STATUS_DEAD


def _numeric(value: object) -> float | None:
    """Return ``value`` as a number, or None when it is not one.

    Booleans are not numbers here: JSON ``true`` in a numeric field is bad data,
    and Python would otherwise silently rank it as 1.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _pool_record_in_cooldown(record: dict, *, now: float) -> bool:
    """Whether a selectable record is inside an ``exhausted`` cooldown at ``now``.

    Hermes writes ``exhausted`` when the completions endpoint returned a quota
    error, recording the reset time in ``last_error_reset_at``. That quota does
    not gate the usage and reset-credit endpoints this module reads, so the
    cooldown only demotes a record: it keeps the footer on the credential
    Hermes actually rotated to while a healthy one exists, without making
    resolution fail once every credential is exhausted (which is exactly when
    auto reset must run).

    A missing, non-numeric, or already elapsed reset time is not a cooldown.
    ``now`` is passed in so one clock reading classifies every record in a
    selection: re-reading the clock per record could split a tier mid-scan.
    """
    if record.get("last_status") != _POOL_STATUS_EXHAUSTED:
        return False
    reset_at = _numeric(record.get("last_error_reset_at"))
    return reset_at is not None and reset_at > now


def _pool_priority(record: dict) -> float:
    """Sort key for a pooled record: its ``priority``, normalized to a number."""
    priority = _numeric(record.get("priority"))
    return _DEFAULT_POOL_PRIORITY if priority is None else priority


def _select_pool_record(pool_records: list) -> dict | None:
    """Pick the pooled record to read usage from, or None if none qualifies.

    Prefers records that are not in an ``exhausted`` cooldown, ordered by
    ascending priority; falls back to the cooled-down ones under the same rule.
    False sorts before True, so the cooldown flag leads the key and demotes a
    whole tier. ``min`` keeps the first of equal-key records, so ordering is
    stable.
    """
    selectable = [record for record in pool_records if _pool_record_selectable(record)]
    if not selectable:
        return None
    now = time.time()
    return min(
        selectable,
        key=lambda record: (
            _pool_record_in_cooldown(record, now=now),
            _pool_priority(record),
        ),
    )


def _codex_record(raw: dict) -> dict:
    """Return the Codex credential record from supported auth.json layouts.

    Hermes may nest credentials under ``providers/openai-codex`` or store a
    prioritized credential list under ``credential_pool/openai-codex``. The Codex
    CLI keeps ``tokens`` at the top level. Only the pooled layout is projected
    onto a record carrying ``tokens``; the other two are returned unchanged,
    since they may legitimately omit ``refresh_token``/``account_id`` or carry a
    top-level API key instead of ``tokens``.

    Raise RuntimeError when a non-empty pool yields no selectable record.
    """
    providers = raw.get("providers")
    if isinstance(providers, dict) and isinstance(
        providers.get(_HERMES_CODEX_PROVIDER), dict
    ):
        return providers[_HERMES_CODEX_PROVIDER]

    pool = raw.get("credential_pool")
    pool_records = pool.get(_HERMES_CODEX_PROVIDER) if isinstance(pool, dict) else None
    if (
        isinstance(pool, dict)
        and _HERMES_CODEX_PROVIDER in pool
        and not isinstance(pool_records, list)
    ):
        raise RuntimeError("Codex credential pool is not a list")
    if isinstance(pool_records, list) and pool_records:
        # A non-empty pool that yields nothing is a selection failure, not an
        # absent pool: falling through would report that the auth store holds
        # no usable token while the tokens sit right there, excluded by rule.
        # Keep identifiers out of the message -- it may reach shared logs.
        record = _select_pool_record(pool_records)
        if record is None:
            raise RuntimeError(
                "Codex credential pool selection found no usable credential "
                f"among {len(pool_records)} records"
            )
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


def _active_auth() -> tuple[str, str | None]:
    """Return the active access token and optional ChatGPT account identifier."""
    auth = _load_auth()
    tokens = auth.get("tokens") or {}
    access_token = tokens.get("access_token") or auth.get("OPENAI_API_KEY")
    if not access_token:
        raise RuntimeError("auth.json has no usable access token")
    return access_token, tokens.get("account_id")


def _auth_headers(access_token: str, account_id: str | None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "hermes-usage-hook",
    }
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id
    return headers


def _request_json(
    method: str,
    url: str,
    *,
    access_token: str,
    account_id: str | None,
    payload: dict | None = None,
) -> dict:
    """Send one authenticated request and return a JSON object without retries."""
    headers = _auth_headers(access_token, account_id)
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        if payload is None:
            response = client.request(method, url, headers=headers)
        else:
            response = client.request(method, url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
    if not isinstance(result, dict):
        raise RuntimeError("Codex backend returned a non-object JSON response")
    return result


def _call_usage(access_token: str, account_id: str | None) -> dict:
    return _request_json(
        "GET",
        USAGE_URL,
        access_token=access_token,
        account_id=account_id,
    )


def list_rate_limit_reset_credits() -> dict:
    """GET the detailed reset-credit collection using active Codex OAuth."""
    access_token, account_id = _active_auth()
    return _request_json(
        "GET",
        RESET_CREDITS_URL,
        access_token=access_token,
        account_id=account_id,
    )


def consume_rate_limit_reset_credit(
    redeem_request_id: str, credit_id: str | None
) -> dict:
    """POST one idempotent consume attempt; never generate or retry IDs here."""
    access_token, account_id = _active_auth()
    payload = {"redeem_request_id": redeem_request_id}
    if credit_id is not None:
        payload["credit_id"] = credit_id
    return _request_json(
        "POST",
        CONSUME_RESET_CREDIT_URL,
        access_token=access_token,
        account_id=account_id,
        payload=payload,
    )


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
        # Clamp remaining into [0, 100]: an over-exhausted window can report
        # used_percent > 100, and a negative remaining would otherwise be
        # rejected by weekly_remaining() exactly when a reset is most needed.
        windows[_label_window(snap.get("limit_window_seconds", 0))] = {
            "used_percent": used,
            "remaining_percent": max(0, min(100, 100 - used)),
            "reset_at": reset_at,
            "reset_in_min": (
                max(0, round((reset_at - time.time()) / 60)) if reset_at else None
            ),
        }
    credits = raw.get("credits") or {}
    reset_credits = raw.get("rate_limit_reset_credits") or {}
    return {
        "provider": "Codex",
        "plan_type": raw.get("plan_type"),
        "windows": windows,
        "credits_balance": credits.get("balance"),
        "reset_credits_available": reset_credits.get("available_count"),
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
    access_token, account_id = _active_auth()
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
