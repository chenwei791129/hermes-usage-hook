"""Best-effort local history of successful Codex auto resets.

Events are flat, privacy-minimized JSON records appended one-per-line to
``<home>/logs/hermes-usage-hook-autoreset.jsonl``. Writing is best-effort and
deduplicated by a hash of the redeem request ID; reading is lenient and silently
skips any line that does not parse into a valid event.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from .hermes_home import resolve_hermes_home

_HISTORY_FILENAME = "hermes-usage-hook-autoreset.jsonl"
# Public so the renderer can defensively check a status read back from disk.
VALID_BACKEND_STATUSES = frozenset({"reset", "already_redeemed"})
# event_id is "sha256:" + 64 lowercase hex characters.
_EVENT_ID_HEX_LENGTH = 64


def _coerce_percent(value: object) -> int | float | None:
    """Return a 0..100 percentage, or None when the value is unusable."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or not 0 <= value <= 100:
        return None
    return value


def _coerce_credits(value: object) -> int | None:
    """Return a non-negative integer credit count, or None when unusable."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def build_success_event(
    *,
    redeem_request_id: object,
    observed_at: object,
    backend_status: object,
    weekly_before: object,
    weekly_after: object,
    credits_before: object,
    credits_after: object,
) -> dict:
    """Build one flat, privacy-minimized success event.

    The raw redeem request ID is hashed into ``event_id`` and never stored.
    ``observed_at`` is an epoch-seconds float. Invalid snapshot values degrade to
    ``null``; an empty request ID, an unknown backend status, or a non-finite
    ``observed_at`` raise ``ValueError``.
    """
    if not isinstance(redeem_request_id, str) or not redeem_request_id:
        raise ValueError("redeem_request_id must be a non-empty string")
    if backend_status not in VALID_BACKEND_STATUSES:
        raise ValueError("backend_status must be 'reset' or 'already_redeemed'")
    if (
        isinstance(observed_at, bool)
        or not isinstance(observed_at, (int, float))
        or not math.isfinite(observed_at)
    ):
        raise ValueError("observed_at must be a finite epoch timestamp")
    try:
        moment = datetime.fromtimestamp(observed_at, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("observed_at is out of range") from exc

    digest = hashlib.sha256(redeem_request_id.encode("utf-8")).hexdigest()
    return {
        "event_id": f"sha256:{digest}",
        "observed_at": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "backend_status": backend_status,
        "weekly_before": _coerce_percent(weekly_before),
        "weekly_after": _coerce_percent(weekly_after),
        "credits_before": _coerce_credits(credits_before),
        "credits_after": _coerce_credits(credits_after),
    }


def parse_rfc3339(value: object) -> datetime | None:
    """Parse an RFC 3339 timestamp into an aware UTC datetime, or None.

    Handles the ``Z`` suffix that ``datetime.fromisoformat`` rejects before
    Python 3.11, since the project supports 3.10.
    """
    if not isinstance(value, str) or not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_valid_event_id(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    hex_part = value[len("sha256:") :]
    return len(hex_part) == _EVENT_ID_HEX_LENGTH and all(
        char in "0123456789abcdef" for char in hex_part
    )


def _parse_event_line(line: str) -> dict | None:
    """Return a valid event dict for one file line, or None to skip it.

    Never emits the raw line into logs or exceptions: an unparsable or invalid
    line is silently discarded so malformed content cannot leak.
    """
    try:
        event = json.loads(line)
    except ValueError:
        return None
    if not isinstance(event, dict):
        return None
    if not _is_valid_event_id(event.get("event_id")):
        return None
    if parse_rfc3339(event.get("observed_at")) is None:
        return None
    return event


def _load_events(path: Path) -> list[dict]:
    """Return valid events from ``path`` in append order; missing file → [].

    Reads bytes and decodes each line independently so a single non-UTF-8 byte
    (from a manual edit or a partial multibyte write) skips only that line rather
    than raising ``UnicodeDecodeError`` and discarding the whole history — which
    would also block future appends, since the dedup scan reads through here.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    events = []
    for raw_line in raw.split(b"\n"):
        try:
            stripped = raw_line.decode("utf-8").strip()
        except UnicodeDecodeError:
            continue
        if not stripped:
            continue
        event = _parse_event_line(stripped)
        if event is not None:
            events.append(event)
    return events


def append_success_event(
    event: dict, *, home: str | os.PathLike[str] | None = None
) -> bool:
    """Append one event line, deduplicated by ``event_id``; True if written.

    Best-effort: the parent directory is created when missing, the file is
    opened append-only requesting mode ``0600`` (a failed ``chmod`` is ignored),
    and an ``event_id`` already present in the file is skipped (returns False).
    """
    path = resolve_hermes_home(home) / "logs" / _HISTORY_FILENAME
    existing = {existing_event["event_id"] for existing_event in _load_events(path)}
    if event["event_id"] in existing:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, separators=(",", ":")) + "\n"
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass  # Best-effort: filesystems without POSIX modes must still work.
        os.write(descriptor, line.encode("utf-8"))
    finally:
        os.close(descriptor)
    return True


def read_events(*, home: str | os.PathLike[str] | None = None) -> list[dict]:
    """Return valid history events in file append order (missing file → [])."""
    return _load_events(resolve_hermes_home(home) / "logs" / _HISTORY_FILENAME)
