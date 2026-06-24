"""Hermes plugin hook: append the current provider's usage as a reply footer.

Detects the provider from the reply's ``model`` (Codex or MiniMax) and appends
that provider's usage — a ``5h`` line plus a ``weekly`` line when available; an
unrecognized model leaves the reply unchanged.

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
hook runs, so the rewrite may not take effect, and the footer may not appear.
"""

from __future__ import annotations

import os
import sys

# Make the shared module importable regardless of where the plugin lives.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser("~/.hermes/lib"))

from usage import format_summary, get_usage_for_model  # noqa: E402


def register(ctx):
    """Hermes plugin entry point."""
    ctx.register_hook("transform_llm_output", append_usage_footer)


def append_usage_footer(response_text: str, **kwargs) -> str | None:
    """Append the usage footer; return None to leave the response unchanged.

    Detects the provider from the current reply's ``model`` and fetches that
    provider's usage, rendering its ``5h`` and ``weekly`` windows. An
    unrecognized model, or any fetch failure, leaves the reply unchanged
    (returns None).
    """
    if not response_text:
        return None
    try:
        usage = get_usage_for_model(kwargs.get("model"))
        if usage is None:
            return None
        footer = format_summary(usage)
    except Exception as exc:  # noqa: BLE001 - never break the reply
        print(f"[hermes-usage-hook] skipped: {exc}", file=sys.stderr)
        return None
    return f"{response_text}\n\n───\n\U0001f9ee {footer}"
