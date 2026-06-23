"""Provider detection, dispatch, and summary formatting for usage footers.

Holds the ordered provider registry: each entry pairs a case-insensitive
matcher against the response ``model`` name with a fetcher that returns the
shared normalized usage structure

    {"provider": str, "plan_type": str | None,
     "windows": {"5h": {"used_percent", "remaining_percent", "reset_in_min"},
                 "weekly": {...}}}

``get_usage_for_model`` returns the first matching provider's usage, or ``None``
when no provider matches. ``format_summary`` renders that structure into the
one-line, provider-labeled footer.
"""

from __future__ import annotations

import codex_usage
import minimax_usage

# Model-name prefixes that identify Codex even without the literal "codex".
_CODEX_PREFIXES = ("gpt-", "o1", "o3", "o4")


def _matches_codex(model: str) -> bool:
    return "codex" in model or model.startswith(_CODEX_PREFIXES)


def _matches_minimax(model: str) -> bool:
    return "minimax" in model or "abab" in model


# Ordered registry: (provider name, matcher, fetcher). Fetchers are looked up
# on the module at call time so tests can monkeypatch them. Adding a provider is
# one new module plus one line here.
_REGISTRY = (
    ("Codex", _matches_codex, lambda: codex_usage.get_codex_usage()),
    ("MiniMax", _matches_minimax, lambda: minimax_usage.get_minimax_usage()),
)


def _lookup(model: str | None):
    """Return the registry entry matching ``model`` (case-insensitive), or None."""
    if not model:
        return None
    lowered = model.lower()
    for entry in _REGISTRY:
        _name, matches, _fetch = entry
        if matches(lowered):
            return entry
    return None


def _match_provider(model: str | None) -> str | None:
    """Return the provider name matching ``model`` (case-insensitive), or None."""
    entry = _lookup(model)
    return entry[0] if entry else None


def get_usage_for_model(model: str | None) -> dict | None:
    """Fetch normalized usage for ``model``'s provider, or None when unmatched."""
    entry = _lookup(model)
    return entry[2]() if entry else None


def format_summary(usage: dict) -> str:
    """Build a one-line, provider-labeled summary focused on the 5h window.

    Consumes only the normalized structure. Appends ``| plan <plan_type>`` when
    a plan is present and omits it otherwise; reports unavailability when the
    5h window is missing.
    """
    provider = usage.get("provider")
    window = usage.get("windows", {}).get("5h", {})
    if not window:
        return f"{provider} usage: 5h window unavailable"
    reset_in_min = window.get("reset_in_min")
    reset_clause = (
        f" (resets in {reset_in_min} min)" if reset_in_min is not None else ""
    )
    summary = (
        f"{provider} 5h | used {window.get('used_percent')}%, "
        f"left {window.get('remaining_percent')}%{reset_clause}"
    )
    plan_type = usage.get("plan_type")
    if plan_type:
        summary += f" | plan {plan_type}"
    return summary
