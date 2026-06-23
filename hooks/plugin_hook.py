"""Hermes plugin hook: report Codex 5h usage when a conversation ends.

Registers an ``on_session_end`` hook, which fires at the end of every
conversation in both CLI and gateway modes. On each end it fetches the current
Codex rate-limit usage and sends a one-line summary.

Install: copy this file (and ``codex_usage.py``) into your Hermes plugins
directory so ``register`` is discovered. See the project README for paths.

Notifier selection (env ``CODEX_USAGE_NOTIFIER``):
    macos    macOS desktop notification via osascript (default on darwin)
    webhook  HTTP POST a JSON {"text": ...} to ``CODEX_USAGE_WEBHOOK_URL``
    stdout   print to stdout (handy while developing)
"""

from __future__ import annotations

import asyncio
import os
import sys

# Make the shared module importable regardless of where the plugin lives.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser("~/.hermes/lib"))

from codex_usage import get_codex_usage  # noqa: E402
from usage import format_summary  # noqa: E402


def register(ctx):
    """Hermes plugin entry point."""
    ctx.register_hook("on_session_end", on_session_end)


async def on_session_end(session_id=None, completed=None, **kwargs):
    """Fire-and-forget: never raise, so a failure can't break the agent."""
    try:
        # get_codex_usage is sync; run it off the event loop.
        usage = await asyncio.to_thread(get_codex_usage)
        await _notify(format_summary(usage))
    except Exception as exc:  # noqa: BLE001 - observer hook must not propagate
        print(f"[codex-usage-hook] skipped: {exc}", file=sys.stderr)


async def _notify(text: str) -> None:
    notifier = os.environ.get("CODEX_USAGE_NOTIFIER") or (
        "macos" if sys.platform == "darwin" else "stdout"
    )
    if notifier == "macos":
        await _notify_macos(text)
    elif notifier == "webhook":
        await _notify_webhook(text)
    else:
        print(text)


async def _notify_macos(text: str) -> None:
    # Escape double quotes for the AppleScript string literal.
    safe = text.replace('"', '\\"')
    proc = await asyncio.create_subprocess_exec(
        "osascript",
        "-e",
        f'display notification "{safe}" with title "Hermes / Codex"',
    )
    await proc.wait()


async def _notify_webhook(text: str) -> None:
    import httpx

    url = os.environ.get("CODEX_USAGE_WEBHOOK_URL")
    if not url:
        raise RuntimeError("CODEX_USAGE_WEBHOOK_URL is not set")
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(url, json={"text": text})
