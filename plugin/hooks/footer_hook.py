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
import unicodedata

from ..autoreset import AutoResetStateStore, maybe_autoreset
from ..usage import format_summary, get_usage_for_model

# Coordinator statuses that do no filesystem work and never persist a notice, so
# the footer can skip the locked notice-store reads entirely for these.
_NO_NOTICE_STATUSES = frozenset({"disabled", "not_codex", "invalid_config"})

# Keep this small and explicit to mirror the host's intentional-silence filter.
# Importing the host helper would couple the standalone plugin to host internals.
_SILENCE_MARKERS = frozenset({"[SILENT]", "SILENT", "NO_REPLY", "NO REPLY"})
_SILENCE_MARKER_MAX_LENGTH = 64


def _canonical_silence_marker(text: str) -> str:
    return " ".join(text.strip().upper().split())


def _strip_edge_silence_punctuation(text: str) -> str:
    """Strip stray edge punctuation while preserving square brackets."""
    start = 0
    end = len(text)
    while (
        start < end
        and text[start] not in "[]"
        and unicodedata.category(text[start]).startswith("P")
    ):
        start += 1
    while (
        end > start
        and text[end - 1] not in "[]"
        and unicodedata.category(text[end - 1]).startswith("P")
    ):
        end -= 1
    return text[start:end].strip()


def _is_silence_marker(text: object) -> bool:
    """Return whether the whole reply is a host intentional-silence marker."""
    if not isinstance(text, str):
        return False
    stripped = text.strip()
    if not stripped or len(stripped) > _SILENCE_MARKER_MAX_LENGTH:
        return False
    exact = _canonical_silence_marker(stripped)
    without_edge_punctuation = _strip_edge_silence_punctuation(stripped)
    if exact in _SILENCE_MARKERS:
        return True
    return (
        without_edge_punctuation != stripped
        and _canonical_silence_marker(without_edge_punctuation) in _SILENCE_MARKERS
    )


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
        store = AutoResetStateStore()
        notice = store.pop_notice(session_id)
        return notice if notice is not None else store.pop_fallback_notice(session_id)
    except Exception as exc:  # noqa: BLE001 - footer must remain best-effort
        print(f"[hermes-usage-hook] auto reset notice skipped: {exc}", file=sys.stderr)
        return None


def append_usage_footer(response_text: str, **kwargs) -> str | None:
    """Append usage, preserve silence markers, or return None for no change.

    Detects the provider from the current reply's ``model`` and fetches that
    provider's usage, rendering its ``5h`` and ``weekly`` windows. Intentional
    silence markers are returned unchanged to stop subsequent transform hooks;
    an unrecognized model or fetch failure returns None.
    """
    if not response_text:
        return None
    if _is_silence_marker(response_text):
        # A non-empty string wins the host's transform hook chain. Returning the
        # marker unchanged prevents a later transformer from appending content
        # that would make the host's intentional-silence filter miss it.
        return response_text
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
            # Skip the locked notice-store reads when auto reset never ran: these
            # states persist no notice, so polling would only add filesystem I/O
            # to every reply for deployments that never enabled the feature.
            if reset_result.status not in _NO_NOTICE_STATUSES:
                notice = _pop_notice(session_id)
            if (
                notice is None
                and reset_result.status in {"reset", "already_redeemed"}
                and not reset_result.notice_persisted
            ):
                notice = reset_result.message
        except Exception as exc:  # noqa: BLE001 - preserve normal footer behavior
            print(f"[hermes-usage-hook] auto reset skipped: {exc}", file=sys.stderr)
        footer = format_summary(usage)
        if notice:
            footer = f"{footer}\n{notice}"
    except Exception as exc:  # noqa: BLE001 - never break the reply
        print(f"[hermes-usage-hook] skipped: {exc}", file=sys.stderr)
        return None
    return f"{response_text}\n\n───\n{footer}"
