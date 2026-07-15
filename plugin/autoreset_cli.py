"""Native, profile-scoped CLI for reading Codex auto-reset audit history."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone

from .autoreset_audit import AutoResetAuditLog
from .hermes_home import resolve_hermes_home
from .autoreset_lock import acquire_autoreset_lock

_DURATION_PATTERN = re.compile(r"([1-9][0-9]*)([smhd])\Z")
_DURATION_MULTIPLIERS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_MAX_TIMEDELTA_SECONDS = timedelta.max.days * 86400 + timedelta.max.seconds


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _duration_seconds(value: str) -> int:
    match = _DURATION_PATTERN.fullmatch(value)
    if match is None:
        raise argparse.ArgumentTypeError(
            "must be a positive integer followed by s, m, h, or d"
        )
    amount, unit = match.groups()
    seconds = int(amount) * _DURATION_MULTIPLIERS[unit]
    if seconds > _MAX_TIMEDELTA_SECONDS:
        raise argparse.ArgumentTypeError("duration is too large")
    return seconds


def register_cli(parser: argparse.ArgumentParser) -> None:
    """Register the single offline ``history`` subcommand."""
    subs = parser.add_subparsers(dest="usage_hook_action")
    history = subs.add_parser(
        "history", help="Show successful Codex auto-reset history"
    )
    history.add_argument("--last", type=_positive_int, default=20)
    history.add_argument("--since", type=_duration_seconds)
    history.add_argument("--json", action="store_true", dest="json_output")
    parser.set_defaults(func=usage_hook_command)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(f"{value[:-1]}+00:00")


def _display(value: object) -> str:
    return "?" if value is None else str(value)


def _human_line(event: dict) -> str:
    observed = _parse_utc(event["observed_at"]).astimezone()
    before = event["before"]
    after = event["after"]
    return (
        f"{observed.strftime('%Y-%m-%d %H:%M:%S %Z')} | "
        f"{event['backend_status']} | {event['trigger']} | "
        f"weekly {_display(before['weekly_remaining_percent'])} → "
        f"{_display(after['weekly_remaining_percent'])} | "
        f"credits {_display(before['reset_credits'])} → "
        f"{_display(after['reset_credits'])}"
    )


def usage_hook_command(args: argparse.Namespace) -> int:
    """Read and render local audit history while holding the coordinator lock."""
    if getattr(args, "usage_hook_action", None) != "history":
        print("usage-hook: error: history subcommand required", file=sys.stderr)
        return 2

    home = resolve_hermes_home()
    try:
        with acquire_autoreset_lock(home=home) as acquired:
            if not acquired:
                print("Codex auto-reset history is busy; try again.", file=sys.stderr)
                return 1
            events, malformed = AutoResetAuditLog(home=home).read_events()
    except OSError:
        print("Unable to read Codex auto-reset history.", file=sys.stderr)
        return 1

    since = getattr(args, "since", None)
    if since is not None:
        try:
            threshold = _now_utc() - timedelta(seconds=since)
        except OverflowError:
            # A window wider than representable time keeps every event.
            threshold = datetime.min.replace(tzinfo=timezone.utc)
        events = [
            event for event in events if _parse_utc(event["observed_at"]) >= threshold
        ]
    events = events[-args.last :]

    if malformed:
        suffix = "line" if malformed == 1 else "lines"
        print(
            f"Skipped {malformed} malformed auto-reset history {suffix}.",
            file=sys.stderr,
        )

    if args.json_output:
        for event in events:
            print(json.dumps(event, separators=(",", ":"), ensure_ascii=False))
    elif not events:
        print("No Codex auto-reset history found.")
    else:
        for event in events:
            print(_human_line(event))
    return 0
