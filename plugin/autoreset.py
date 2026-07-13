"""Configuration and coordination primitives for Codex auto reset."""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from uuid import uuid4

from .usage import matches_codex_model

PLUGIN_ID = "hermes-usage-hook"
ENV_ENABLED = "CODEX_ENABLE_AUTORESET"
ENV_THRESHOLD = "CODEX_AUTORESET_THRESHOLD"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True)
class AutoResetConfig:
    """Effective auto-reset settings, including fail-closed validation state."""

    enabled: bool
    threshold: int
    valid: bool = True
    error: str | None = None


def _load_hermes_config() -> dict:
    """Load Hermes config lazily so standalone tests need no Hermes runtime."""
    try:
        config_module = import_module("hermes_cli.config")
    except ImportError:
        return {}
    loaded = config_module.load_config() or {}
    return loaded if isinstance(loaded, dict) else {}


def _invalid(error: str) -> AutoResetConfig:
    return AutoResetConfig(enabled=False, threshold=0, valid=False, error=error)


def _plugin_autoreset(config: dict) -> dict:
    plugins = config.get("plugins")
    if plugins is None:
        return {}
    if not isinstance(plugins, dict):
        raise ValueError("plugins must be a mapping")

    entries = plugins.get("entries")
    if entries is None:
        return {}
    if not isinstance(entries, dict):
        raise ValueError("plugins.entries must be a mapping")

    entry = entries.get(PLUGIN_ID)
    if entry is None:
        return {}
    if not isinstance(entry, dict):
        raise ValueError(f"plugins.entries.{PLUGIN_ID} must be a mapping")

    auto_reset = entry.get("auto_reset")
    if auto_reset is None:
        return {}
    if not isinstance(auto_reset, dict):
        raise ValueError(
            f"plugins.entries.{PLUGIN_ID}.auto_reset must be a mapping"
        )
    return auto_reset


def _parse_env_boolean(value: object) -> bool:
    if not isinstance(value, str):
        raise ValueError(f"{ENV_ENABLED} must be a string boolean")
    normalized = value.strip().casefold()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(f"{ENV_ENABLED} has an invalid boolean value")


def _parse_env_threshold(value: object) -> int:
    if not isinstance(value, str):
        raise ValueError(f"{ENV_THRESHOLD} must be an integer string")
    normalized = value.strip()
    if not normalized.isdecimal():
        raise ValueError(f"{ENV_THRESHOLD} must be an integer from 0 to 99")
    threshold = int(normalized)
    if threshold > 99:
        raise ValueError(f"{ENV_THRESHOLD} must be an integer from 0 to 99")
    return threshold


def _parse_plugin_boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("plugin auto_reset.enabled must be a boolean")
    return value


def _parse_plugin_threshold(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("plugin auto_reset.threshold must be an integer from 0 to 99")
    if not 0 <= value <= 99:
        raise ValueError("plugin auto_reset.threshold must be an integer from 0 to 99")
    return value


def load_autoreset_config(
    *, env: Mapping[str, str] | None = None, config: dict | None = None
) -> AutoResetConfig:
    """Resolve env overrides, canonical plugin config, then safe defaults.

    Explicit invalid values fail closed instead of falling through to a
    lower-precedence source.
    """
    source_env: Mapping[str, str] = os.environ if env is None else env
    source_config = _load_hermes_config() if config is None else config

    try:
        plugin = _plugin_autoreset(source_config)

        if ENV_ENABLED in source_env:
            enabled = _parse_env_boolean(source_env[ENV_ENABLED])
        elif "enabled" in plugin:
            enabled = _parse_plugin_boolean(plugin["enabled"])
        else:
            enabled = False

        if ENV_THRESHOLD in source_env:
            threshold = _parse_env_threshold(source_env[ENV_THRESHOLD])
        elif "threshold" in plugin:
            threshold = _parse_plugin_threshold(plugin["threshold"])
        else:
            threshold = 0
    except (TypeError, ValueError) as exc:
        return _invalid(str(exc))

    return AutoResetConfig(enabled=enabled, threshold=threshold)


def weekly_remaining(usage: dict) -> int | float | None:
    """Return only the normalized weekly remaining percentage, never a proxy."""
    windows = usage.get("windows")
    if not isinstance(windows, dict):
        return None
    weekly = windows.get("weekly")
    if not isinstance(weekly, dict):
        return None
    remaining = weekly.get("remaining_percent")
    if isinstance(remaining, bool) or not isinstance(remaining, (int, float)):
        return None
    if not 0 <= remaining <= 100:
        return None
    return remaining


def is_eligible(*, model: str | None, usage: dict, config: AutoResetConfig) -> bool:
    """Evaluate pure Codex weekly reset eligibility without side effects."""
    if not config.valid or not config.enabled or not matches_codex_model(model):
        return False
    if (
        isinstance(config.threshold, bool)
        or not isinstance(config.threshold, int)
        or not 0 <= config.threshold <= 99
    ):
        return False
    remaining = weekly_remaining(usage)
    if remaining is None:
        return False
    credit_count = usage.get("reset_credits_available")
    if isinstance(credit_count, bool) or not isinstance(credit_count, int):
        return False
    return credit_count > 0 and remaining <= config.threshold


def _parse_expiry(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("credit expiry must be an ISO-8601 string or null")
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("credit expiry must include a timezone")
    return parsed.astimezone(timezone.utc)


def select_earliest_available_credit(payload: dict) -> dict | None:
    """Choose the usable available credit with the earliest real expiry."""
    available_count = payload.get("available_count")
    if (
        isinstance(available_count, bool)
        or not isinstance(available_count, int)
        or available_count <= 0
    ):
        return None
    credits = payload.get("credits")
    if not isinstance(credits, list):
        return None

    candidates: list[tuple[bool, datetime, dict]] = []
    for row in credits:
        if not isinstance(row, dict) or row.get("status") != "available":
            continue
        credit_id = row.get("id")
        if not isinstance(credit_id, str) or not credit_id:
            continue
        try:
            expiry = _parse_expiry(row.get("expires_at"))
        except (TypeError, ValueError, OverflowError):
            continue
        candidates.append(
            (
                expiry is None,
                expiry or datetime.max.replace(tzinfo=timezone.utc),
                row,
            )
        )

    if not candidates:
        return None
    return min(candidates, key=lambda candidate: candidate[:2])[2]


STATE_VERSION = 1
LOCK_STALE_SECONDS = 120.0
NOTICE_TTL_SECONDS = 24 * 60 * 60

_PENDING_FIELDS = frozenset(
    {
        "redeem_request_id",
        "credit_id",
        "status",
        "created_at",
        "updated_at",
        "retry_after",
        "before_remaining",
        "before_credits",
    }
)


class CorruptStateError(RuntimeError):
    """Raised after corrupt state has been quarantined for fail-closed handling."""


def _hermes_home() -> Path:
    """Return the active profile's Hermes home without importing Hermes."""
    return Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()


def _clean_state(state: dict) -> dict:
    cleaned: dict = {"version": STATE_VERSION}

    pending = state.get("pending")
    if isinstance(pending, dict):
        cleaned["pending"] = {
            key: value
            for key, value in pending.items()
            if key in _PENDING_FIELDS
            and isinstance(value, (str, int, float))
            and not isinstance(value, bool)
        }
    elif pending is None:
        cleaned["pending"] = None

    cooldown_until = state.get("cooldown_until")
    if isinstance(cooldown_until, (int, float)) and not isinstance(
        cooldown_until, bool
    ):
        cleaned["cooldown_until"] = cooldown_until
    cooldown_reason = state.get("cooldown_reason")
    if isinstance(cooldown_reason, str):
        cleaned["cooldown_reason"] = cooldown_reason

    notices = state.get("notices")
    clean_notices = {}
    if isinstance(notices, dict):
        for session_id, notice in notices.items():
            if not isinstance(session_id, str) or not session_id:
                continue
            if not isinstance(notice, dict):
                continue
            message = notice.get("message")
            created_at = notice.get("created_at")
            if (
                isinstance(message, str)
                and isinstance(created_at, (int, float))
                and not isinstance(created_at, bool)
            ):
                clean_notices[session_id] = {
                    "message": message,
                    "created_at": created_at,
                }
    cleaned["notices"] = clean_notices
    return cleaned


class AutoResetStateStore:
    """Atomic profile-local persistence for safe auto-reset coordination state."""

    def __init__(
        self,
        *,
        home: Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.home = Path(home) if home is not None else _hermes_home()
        self.path = self.home / "state" / PLUGIN_ID / "autoreset.json"
        self.lock_path = self.home / "state" / PLUGIN_ID / "autoreset.lock"
        self.clock = clock

    @staticmethod
    def empty() -> dict:
        return {"version": STATE_VERSION, "pending": None, "notices": {}}

    def _quarantine(self) -> Path:
        stamp = int(self.clock())
        candidate = self.path.with_name(f"autoreset.corrupt.{stamp}.json")
        suffix = 1
        while candidate.exists():
            candidate = self.path.with_name(
                f"autoreset.corrupt.{stamp}.{suffix}.json"
            )
            suffix += 1
        os.replace(self.path, candidate)
        return candidate

    def load(self) -> dict:
        if not self.path.exists():
            return self.empty()
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict) or loaded.get("version") != STATE_VERSION:
                raise ValueError("unsupported or malformed auto-reset state")
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            try:
                quarantined = self._quarantine()
            except OSError:
                quarantined = self.path
            raise CorruptStateError(
                f"corrupt auto-reset state quarantined at {quarantined}"
            ) from exc
        return _clean_state(loaded)

    def write(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        cleaned = _clean_state(state)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=".autoreset.", suffix=".tmp", dir=self.path.parent
        )
        temp_path = Path(temp_name)
        try:
            try:
                os.fchmod(descriptor, 0o600)
            except (AttributeError, OSError):
                pass
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(cleaned, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
            try:
                self.path.chmod(0o600)
            except OSError:
                pass
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def cooldown_active(state: dict, *, now: float) -> bool:
        deadline = state.get("cooldown_until")
        return (
            isinstance(deadline, (int, float))
            and not isinstance(deadline, bool)
            and now < deadline
        )

    @staticmethod
    def _prune_notices(state: dict, now: float) -> dict:
        notices = state.get("notices")
        if not isinstance(notices, dict):
            notices = {}
        state["notices"] = {
            session_id: notice
            for session_id, notice in notices.items()
            if isinstance(notice, dict)
            and isinstance(notice.get("created_at"), (int, float))
            and now - notice["created_at"] <= NOTICE_TTL_SECONDS
        }
        return state["notices"]

    def queue_notice(
        self, session_id: str, message: str, *, now: float | None = None
    ) -> bool:
        if not session_id:
            return False
        timestamp = self.clock() if now is None else now
        state = self.load()
        notices = self._prune_notices(state, timestamp)
        notices[session_id] = {"message": message, "created_at": timestamp}
        self.write(state)
        return True

    def pop_notice(self, session_id: str, *, now: float | None = None) -> str | None:
        if not session_id:
            return None
        timestamp = self.clock() if now is None else now
        state = self.load()
        notices = self._prune_notices(state, timestamp)
        notice = notices.pop(session_id, None)
        if notice is None:
            return None
        self.write(state)
        message = notice.get("message")
        return message if isinstance(message, str) else None


def _lock_metadata(path: Path) -> dict:
    try:
        loaded = json.loads((path / "owner.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _lock_is_stale(path: Path, now: float) -> bool:
    metadata = _lock_metadata(path)
    created_at = metadata.get("created_at")
    if not isinstance(created_at, (int, float)) or isinstance(created_at, bool):
        try:
            created_at = path.stat().st_mtime
        except OSError:
            return False
    return now - created_at >= LOCK_STALE_SECONDS


def _remove_lock_dir(path: Path) -> None:
    try:
        (path / "owner.json").unlink()
    except FileNotFoundError:
        pass
    try:
        path.rmdir()
    except FileNotFoundError:
        pass


def _try_create_lock(path: Path, owner: str, now: float) -> bool:
    try:
        path.mkdir()
    except FileExistsError:
        return False
    metadata_path = path / "owner.json"
    descriptor = os.open(metadata_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump({"owner": owner, "pid": os.getpid(), "created_at": now}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    return True


def _reclaim_stale_lock(path: Path, owner: str) -> bool:
    stale_path = path.with_name(f"{path.name}.stale.{os.getpid()}.{owner}")
    try:
        os.rename(path, stale_path)
    except (FileNotFoundError, FileExistsError, OSError):
        return False
    try:
        _remove_lock_dir(stale_path)
    except OSError:
        return False
    return True


def _release_owned_lock(path: Path, owner: str) -> None:
    if _lock_metadata(path).get("owner") != owner:
        return
    try:
        _remove_lock_dir(path)
    except OSError:
        pass


@contextmanager
def acquire_autoreset_lock(
    *, home: Path | None = None, now: float | None = None
) -> Iterator[bool]:
    """Acquire the cross-process lock, reclaiming at most one stale holder."""
    lock_home = Path(home) if home is not None else _hermes_home()
    path = lock_home / "state" / PLUGIN_ID / "autoreset.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = time.time() if now is None else now
    owner = str(uuid4())
    acquired = _try_create_lock(path, owner, timestamp)
    if not acquired and _lock_is_stale(path, timestamp):
        if _reclaim_stale_lock(path, owner):
            acquired = _try_create_lock(path, owner, timestamp)
    try:
        yield acquired
    finally:
        if acquired:
            _release_owned_lock(path, owner)
