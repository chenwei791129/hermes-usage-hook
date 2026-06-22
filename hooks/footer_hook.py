"""Hermes plugin hook: append Codex 5h usage as a footer to each reply.

Registers ``transform_llm_output``, which replaces the final response text just
before Hermes delivers it. Because the footer rides on Hermes' normal delivery
path, it is automatically routed back to whatever platform the user is on
(Telegram -> that chat, Discord -> that channel) with no per-platform API code,
no bot tokens, and no chat_id handling. This is the recommended way to send the
usage to the user's current platform.

The handler is synchronous on purpose: Hermes consumes the return value as a
plain string (``isinstance(result, str)``) and keeps the first non-empty string,
so an async handler returning a coroutine would be silently ignored.

Caveat: in streaming deployments the response body is already sent before this
hook runs, so the rewrite may not take effect. If the footer never appears, use
the agent:end gateway hook instead (see README).
"""

from __future__ import annotations

import os
import sys

# Make the shared module importable regardless of where the plugin lives.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser("~/.hermes/lib"))

from codex_usage import format_summary, get_codex_usage  # noqa: E402


def register(ctx):
    """Hermes plugin entry point."""
    ctx.register_hook("transform_llm_output", append_usage_footer)


def append_usage_footer(response_text: str, **kwargs) -> str | None:
    """Append the usage footer; return None to leave the response unchanged."""
    if not response_text:
        return None
    try:
        footer = format_summary(get_codex_usage())
    except Exception as exc:  # noqa: BLE001 - never break the reply
        print(f"[codex-usage-hook] skipped: {exc}", file=sys.stderr)
        return None
    return f"{response_text}\n\n───\n\U0001f9ee {footer}"
