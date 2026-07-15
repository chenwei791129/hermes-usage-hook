"""Privacy-minimized schema and persistence for Codex auto-reset audit events."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from .hermes_home import resolve_hermes_home

logger = logging.getLogger(__name__)

AUDIT_SCHEMA_VERSION = 1
AUDIT_EVENT_TYPE = "codex_autoreset_succeeded"
AUDIT_FILENAME = "hermes-usage-hook-autoreset.jsonl"
_ALLOWED_STATUSES = frozenset({"reset", "already_redeemed"})
_ALLOWED_TRIGGERS = frozenset({"pre_llm_call", "transform_llm_output", "unknown"})
_EVENT_ID_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_EVENT_KEYS = frozenset(
    {
        "schema_version",
        "event_type",
        "event_id",
        "observed_at",
        "backend_status",
        "trigger",
        "before",
        "after",
    }
)
_SNAPSHOT_KEYS = frozenset({"weekly_remaining_percent", "reset_credits"})


def audit_event_id(redeem_request_id: str) -> str:
    """Hash a raw redeem request ID for stable, privacy-safe deduplication."""
    if not isinstance(redeem_request_id, str) or not redeem_request_id:
        raise ValueError("redeem request id must be a non-empty string")
    return "sha256:" + hashlib.sha256(redeem_request_id.encode("utf-8")).hexdigest()


def _percentage(value: object) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("weekly remaining percentage must be a number or null")
    if not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError("weekly remaining percentage must be finite and from 0 to 100")
    return value


def _credits(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("reset credits must be a non-negative integer or null")
    return value


def coerce_percentage(value: object) -> int | float | None:
    """Return the value when it passes the percentage rules, else None."""
    try:
        return _percentage(value)
    except ValueError:
        return None


def coerce_credits(value: object) -> int | None:
    """Return the value when it passes the credits rules, else None."""
    try:
        return _credits(value)
    except ValueError:
        return None


def _observed_at(value: object) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("observed_at must be an RFC 3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError as exc:
        raise ValueError("observed_at must be an RFC 3339 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("observed_at must be an RFC 3339 UTC timestamp")
    return value


def _snapshot(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != _SNAPSHOT_KEYS:
        raise ValueError("before and after must contain exactly the approved fields")
    snapshot = cast(dict[str, object], value)
    return {
        "weekly_remaining_percent": _percentage(snapshot["weekly_remaining_percent"]),
        "reset_credits": _credits(snapshot["reset_credits"]),
    }


def validate_event(event: dict) -> dict:
    """Validate and copy one supported event without passing extra data through."""
    if not isinstance(event, dict) or set(event) != _EVENT_KEYS:
        raise ValueError("audit event must contain exactly the approved fields")
    if event["schema_version"] != AUDIT_SCHEMA_VERSION or isinstance(
        event["schema_version"], bool
    ):
        raise ValueError("unsupported audit schema version")
    if event["event_type"] != AUDIT_EVENT_TYPE:
        raise ValueError("unsupported audit event type")
    event_id = event["event_id"]
    if not isinstance(event_id, str) or _EVENT_ID_PATTERN.fullmatch(event_id) is None:
        raise ValueError("malformed audit event id")
    if event["backend_status"] not in _ALLOWED_STATUSES:
        raise ValueError("unsupported backend status")
    if event["trigger"] not in _ALLOWED_TRIGGERS:
        raise ValueError("unsupported trigger")

    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "event_type": AUDIT_EVENT_TYPE,
        "event_id": event_id,
        "observed_at": _observed_at(event["observed_at"]),
        "backend_status": event["backend_status"],
        "trigger": event["trigger"],
        "before": _snapshot(event["before"]),
        "after": _snapshot(event["after"]),
    }


def build_success_event(
    *,
    redeem_request_id: str,
    observed_at: float,
    backend_status: str,
    trigger: str,
    before_remaining: int | float | None,
    after_remaining: int | float | None,
    before_credits: int | None,
    after_credits: int | None,
) -> dict:
    """Build and validate one schema-v1 successful auto-reset event."""
    if isinstance(observed_at, bool) or not isinstance(observed_at, (int, float)):
        raise ValueError("observed_at must be a finite timestamp")
    if not math.isfinite(observed_at):
        raise ValueError("observed_at must be a finite timestamp")
    try:
        timestamp = (
            datetime.fromtimestamp(observed_at, timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("observed_at must be a finite timestamp") from exc

    return validate_event(
        {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "event_type": AUDIT_EVENT_TYPE,
            "event_id": audit_event_id(redeem_request_id),
            "observed_at": timestamp,
            "backend_status": backend_status,
            "trigger": trigger,
            "before": {
                "weekly_remaining_percent": before_remaining,
                "reset_credits": before_credits,
            },
            "after": {
                "weekly_remaining_percent": after_remaining,
                "reset_credits": after_credits,
            },
        }
    )


def _write_all(descriptor: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("audit append made no write progress")
        remaining = remaining[written:]


def _ensure_owner_only(descriptor: int, path: Path) -> None:
    try:
        os.fchmod(descriptor, 0o600)
    except (AttributeError, OSError):
        path.chmod(0o600)
    if os.fstat(descriptor).st_mode & 0o777 != 0o600:
        # chmod reported success but had no effect: this filesystem cannot
        # represent owner-only modes (the spec requires 0600 only where
        # supported), so raising here would permanently disable the audit.
        logger.warning("audit file mode is not owner-only")


class AutoResetAuditLog:
    """Profile-scoped append-only JSONL storage for successful reset events."""

    def __init__(self, *, home: Path | None = None) -> None:
        self.home = resolve_hermes_home(home)
        self.path = self.home / "logs" / AUDIT_FILENAME

    def append_once(self, event: dict) -> bool:
        """Durably append a supported event unless its event ID already exists."""
        normalized = validate_event(event)
        line = (
            json.dumps(normalized, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
            + b"\n"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            _ensure_owner_only(descriptor, self.path)
            existing = self.path.read_bytes()
            raw_lines = existing.splitlines()
            trailing = None
            if existing and not existing.endswith(b"\n"):
                trailing = raw_lines.pop()

            for raw_line in raw_lines:
                try:
                    candidate = validate_event(json.loads(raw_line))
                except (TypeError, ValueError, UnicodeError, json.JSONDecodeError):
                    continue
                if candidate["event_id"] == normalized["event_id"]:
                    os.fsync(descriptor)
                    return False

            if trailing is not None:
                try:
                    candidate = validate_event(json.loads(trailing))
                except (TypeError, ValueError, UnicodeError, json.JSONDecodeError):
                    candidate = None
                if (
                    candidate is not None
                    and candidate["event_id"] == normalized["event_id"]
                ):
                    _write_all(descriptor, b"\n")
                    os.fsync(descriptor)
                    return False

            payload = (b"\n" if trailing is not None else b"") + line
            _write_all(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return True

    def read_events(self) -> tuple[list[dict], int]:
        """Return valid supported events in file order and a skipped-line count."""
        if not self.path.exists():
            return [], 0
        contents = self.path.read_bytes()
        raw_lines = contents.splitlines()
        valid: list[dict] = []
        malformed = 0
        if contents and not contents.endswith(b"\n"):
            raw_lines = raw_lines[:-1]
            malformed += 1
        for raw_line in raw_lines:
            try:
                candidate = validate_event(json.loads(raw_line))
            except (TypeError, ValueError, UnicodeError, json.JSONDecodeError):
                malformed += 1
                continue
            valid.append(candidate)
        return valid, malformed
