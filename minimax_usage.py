#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27"]
# ///
"""Fetch MiniMax (international) rate-limit usage.

Resolves the MiniMax API token (``MINIMAX_API_KEY`` env first, then the Hermes
home ``.env`` file), calls the ``token_plan/remains`` endpoint, and normalizes
the per-model interval (5h) and weekly windows into the shared usage structure
shared with ``codex_usage``. Pure API key auth -- no OAuth refresh.

Run standalone for a quick check:

    uv run minimax_usage.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

USAGE_URL = "https://www.minimax.io/v1/token_plan/remains"
HTTP_TIMEOUT = 30.0

# MiniMax reports remaining time in milliseconds; convert to whole minutes.
_MS_PER_MIN = 60_000


def _env_path() -> Path:
    """Locate the Hermes home .env, honoring HERMES_HOME like Hermes does."""
    home = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
    return Path(home) / ".env"


def _read_token_from_env_file(path: Path) -> str | None:
    """Return MINIMAX_API_KEY from a minimal KEY=VALUE .env file, or None.

    Only the first ``MINIMAX_API_KEY`` assignment is honored; surrounding single
    or double quotes are stripped. Missing or unreadable files yield None so the
    caller can decide how to fail.
    """
    try:
        text = path.read_text()
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() != "MINIMAX_API_KEY":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        value = value.strip()
        return value or None
    return None


def _resolve_token() -> str:
    """Resolve the MiniMax bearer token: env var first, then home .env fallback.

    Raises when neither source yields a non-empty token. A blank/whitespace env
    value is treated as unset so it falls through to the .env file rather than
    producing a broken Authorization header.
    """
    env_value = (os.environ.get("MINIMAX_API_KEY") or "").strip()
    if env_value:
        return env_value
    path = _env_path()
    file_value = _read_token_from_env_file(path)
    if file_value:
        return file_value
    raise RuntimeError(
        f"MINIMAX_API_KEY not found in environment or {path}; "
        "set it to query MiniMax usage"
    )


def _window(remaining_percent: int, remains_time_ms: int) -> dict:
    """Map a MiniMax remaining-percent + remaining-time pair to a usage window."""
    return {
        "used_percent": 100 - remaining_percent,
        "remaining_percent": remaining_percent,
        "reset_in_min": round(remains_time_ms / _MS_PER_MIN),
    }


def _normalize(raw: dict) -> dict:
    """Reduce a token_plan/remains payload to the shared usage structure.

    Pure function: no network. Raises on a non-zero status code or a missing
    ``general`` model so the caller can swallow the failure and skip the footer.
    """
    base_resp = raw.get("base_resp") or {}
    if base_resp.get("status_code") != 0:
        raise RuntimeError(
            f"MiniMax token_plan/remains returned status_code {base_resp.get('status_code')}"
        )

    general = next(
        (
            entry
            for entry in (raw.get("model_remains") or [])
            if entry.get("model_name") == "general"
        ),
        None,
    )
    if general is None:
        raise RuntimeError("MiniMax token_plan/remains has no 'general' model entry")

    return {
        "provider": "MiniMax",
        "plan_type": None,
        "windows": {
            "5h": _window(
                general.get("current_interval_remaining_percent", 0),
                general.get("remains_time", 0),
            ),
            "weekly": _window(
                general.get("current_weekly_remaining_percent", 0),
                general.get("weekly_remains_time", 0),
            ),
        },
    }


def _call_usage(token: str) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "hermes-codex-usage-hook",
    }
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.get(USAGE_URL, headers=headers)
        resp.raise_for_status()
        return resp.json()


def get_minimax_usage() -> dict:
    """Return normalized MiniMax usage.

    Synchronous on purpose, mirroring ``codex_usage.get_codex_usage`` so the
    footer hook can fetch inline. Raises on unrecoverable errors (missing token,
    network failure, bad status); callers inside a hook wrap this in try/except.
    """
    return _normalize(_call_usage(_resolve_token()))


def _handle_sigterm(signum, frame):
    raise SystemExit(128 + signum)


if __name__ == "__main__":
    import signal

    # Deferred import avoids a circular import: usage imports this module at
    # top level, while this module only needs format_summary when run directly.
    from usage import format_summary

    signal.signal(signal.SIGTERM, _handle_sigterm)
    try:
        result = get_minimax_usage()
        print(json.dumps(result, indent=2))
        print(format_summary(result))
    except KeyboardInterrupt:
        raise SystemExit(130)  # 128 + SIGINT(2)
