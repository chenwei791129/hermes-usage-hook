"""Hermes gateway hook: report Codex 5h usage on every ``agent:end``.

Gateway hooks only run in messaging gateway mode (Telegram/Discord/Slack/...).
The handler function must be named ``handle``. Place this file and ``HOOK.yaml``
together under ``~/.hermes/hooks/codex-usage-notify/``.

Reuses the notifier in ``plugin_hook`` so both hooks share one code path.
"""

from __future__ import annotations

import asyncio
import os
import sys

# Resolve the shared modules whether installed beside the hook or under ~/.hermes/lib.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser("~/.hermes/lib"))

from codex_usage import get_codex_usage  # noqa: E402
from plugin_hook import _notify  # noqa: E402
from usage import format_summary  # noqa: E402


async def handle(event_type: str, context: dict):
    """Fire-and-forget observer; failures are swallowed so the agent is safe."""
    try:
        # get_codex_usage is sync; run it off the event loop.
        usage = await asyncio.to_thread(get_codex_usage)
        await _notify(format_summary(usage))
    except Exception as exc:  # noqa: BLE001 - observer hook must not propagate
        print(f"[codex-usage-hook] skipped: {exc}", file=sys.stderr)
