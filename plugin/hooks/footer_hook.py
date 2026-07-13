"""Hermes plugin hooks for usage footers and opt-in Codex auto reset.

Detects the provider from the reply's ``model`` (Codex or MiniMax) and appends
that provider's usage — a ``5h`` line plus a ``weekly`` line when available; an
unrecognized model leaves the reply unchanged.

Registers exactly two synchronous hooks:

* ``transform_llm_output`` replaces the final response text just before Hermes
  delivers it, so usage and auto-reset audit lines ride the normal platform
  delivery path with no per-platform API code, bot tokens, or chat_id handling.
* ``pre_llm_call`` invokes the same Codex auto-reset coordinator before a model
  request, then returns ``None`` so it never injects prompt context.

Both handlers are synchronous on purpose: Hermes consumes hook return values
directly and does not await coroutine results.

Auto reset is optional and disabled by default. The preflight hook performs no
network work while disabled; when enabled, the footer passes its already-fetched
usage to the coordinator, renders refreshed usage after a reset, and appends one
matching one-shot notice below the normal usage summary.

Caveat: in streaming deployments the response body is already sent before this
hook runs, so the rewrite may not take effect, and the footer may not appear.
"""

from __future__ import annotations

import sys

from ..autoreset import AutoResetStateStore, maybe_autoreset
from ..usage import format_summary, get_usage_for_model


def register(ctx):
    """Hermes plugin entry point."""
    ctx.register_hook("transform_llm_output", append_usage_footer)
    ctx.register_hook("pre_llm_call", codex_autoreset_preflight)


def codex_autoreset_preflight(**kwargs) -> None:
    """Run opt-in Codex auto reset before a request without prompt injection."""
    try:
        maybe_autoreset(
            model=kwargs.get("model"),
            session_id=kwargs.get("session_id") or "",
            turn_id=kwargs.get("turn_id") or "",
        )
    except Exception as exc:  # noqa: BLE001 - never break the provider request
        print(f"[hermes-usage-hook] auto reset skipped: {exc}", file=sys.stderr)
    return None


def _pop_notice(session_id: str) -> str | None:
    if not session_id:
        return None
    try:
        return AutoResetStateStore().pop_notice(session_id)
    except Exception as exc:  # noqa: BLE001 - footer must remain best-effort
        print(f"[hermes-usage-hook] auto reset notice skipped: {exc}", file=sys.stderr)
        return None


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
        model = kwargs.get("model")
        session_id = kwargs.get("session_id") or ""
        usage = get_usage_for_model(model)
        if usage is None:
            return None
        notice = None
        try:
            reset_result = maybe_autoreset(
                model=model,
                usage=usage,
                session_id=session_id,
            )
            if reset_result.after_usage is not None:
                usage = reset_result.after_usage
            notice = _pop_notice(session_id) or reset_result.message
        except Exception as exc:  # noqa: BLE001 - preserve normal footer behavior
            print(f"[hermes-usage-hook] auto reset skipped: {exc}", file=sys.stderr)
        footer = format_summary(usage)
        if notice:
            footer = f"{footer}\n{notice}"
    except Exception as exc:  # noqa: BLE001 - never break the reply
        print(f"[hermes-usage-hook] skipped: {exc}", file=sys.stderr)
        return None
    return f"{response_text}\n\n───\n{footer}"
