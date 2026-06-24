"""Provider detection, dispatch, and summary formatting for usage footers.

Holds the ordered provider registry: each entry pairs a case-insensitive
matcher against the response ``model`` name with a fetcher that returns the
shared normalized usage structure

    {"provider": str, "plan_type": str | None,
     "windows": {"5h": {"used_percent", "remaining_percent", "reset_in_min"},
                 "weekly": {...}}}

``get_usage_for_model`` returns the first matching provider's usage, or ``None``
when no provider matches. ``format_summary`` renders that structure into a
provider-labeled footer: one line for the ``5h`` window and, when present, a
second line for the ``weekly`` window, with reset times produced by the shared
``_format_duration`` formatter.
"""

from __future__ import annotations

from .providers import codex_usage, minimax_usage

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


_MINUTES_PER_HOUR = 60
_MINUTES_PER_DAY = 60 * 24


def _format_duration(minutes: int) -> str:
    """Render a whole-minute count as a compact human-readable duration.

    Shared by every window so reset times format identically:
    ``<60`` -> ``<m>m`` (``0`` -> ``0m``), ``60..<1440`` -> ``<h>h<m>m``,
    ``>=1440`` -> ``<d>d<h>h`` (the hours segment is dropped when zero).
    """
    if minutes < _MINUTES_PER_HOUR:
        return f"{minutes}m"
    if minutes < _MINUTES_PER_DAY:
        hours, mins = divmod(minutes, _MINUTES_PER_HOUR)
        return f"{hours}h{mins}m"
    days, remainder = divmod(minutes, _MINUTES_PER_DAY)
    hours = remainder // _MINUTES_PER_HOUR
    return f"{days}d{hours}h" if hours else f"{days}d"


def _format_window(provider: str | None, label: str, window: dict) -> str:
    """Render one ``<provider> <label> | used X%, left Y%`` line.

    Appends ` (resets in <duration>)` via the shared duration formatter when the
    window carries a ``reset_in_min``; omits the clause when it is absent.
    """
    reset_in_min = window.get("reset_in_min")
    reset_clause = (
        f" (resets in {_format_duration(reset_in_min)})"
        if reset_in_min is not None
        else ""
    )
    return (
        f"{provider} {label} | used {window.get('used_percent')}%, "
        f"left {window.get('remaining_percent')}%{reset_clause}"
    )


def format_summary(usage: dict) -> str:
    """Build a provider-labeled, multi-line summary, one line per window.

    Consumes only the normalized structure. The ``5h`` window renders first; a
    ``weekly`` window, when present, renders as a second line joined by a
    newline. Reset times on both lines use the shared :func:`_format_duration`
    formatter. ``| plan <plan_type>`` is appended to the ``5h`` line only when a
    plan is present. When the ``5h`` window is missing, reports unavailability
    and renders no ``weekly`` line.
    """
    provider = usage.get("provider")
    windows = usage.get("windows", {})
    window_5h = windows.get("5h", {})
    if not window_5h:
        return f"{provider} usage: 5h window unavailable"

    line_5h = _format_window(provider, "5h", window_5h)
    plan_type = usage.get("plan_type")
    if plan_type:
        line_5h += f" | plan {plan_type}"

    lines = [line_5h]
    window_weekly = windows.get("weekly", {})
    if window_weekly:
        lines.append(_format_window(provider, "weekly", window_weekly))
    return "\n".join(lines)
