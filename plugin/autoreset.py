"""Configuration and coordination primitives for Codex auto reset."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from . import autoreset_audit
from .hermes_home import resolve_hermes_home
from .providers.codex_usage import (
    consume_rate_limit_reset_credit,
    list_rate_limit_reset_credits,
)
from .usage import get_usage_for_model, matches_codex_model

logger = logging.getLogger(__name__)

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
        raise ValueError(f"plugins.entries.{PLUGIN_ID}.auto_reset must be a mapping")
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
    remaining = weekly_remaining(usage)
    if remaining is None:
        return False
    credit_count = _usage_credit_count(usage)
    if credit_count is None:
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
    """Resolve the plugin's Hermes home via the one profile-safe resolver.

    A stable internal seam so state, locks, notices, and history share one home;
    the resolution rules live in ``resolve_hermes_home()``.
    """
    return resolve_hermes_home()


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

    fallback_notices = state.get("fallback_notices")
    cleaned_fallbacks = {}
    if isinstance(fallback_notices, dict):
        for session_id, notice in fallback_notices.items():
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
                cleaned_fallbacks[session_id] = {
                    "message": message,
                    "created_at": created_at,
                }
    cleaned["fallback_notices"] = cleaned_fallbacks

    return cleaned


def _clean_notices(state: dict) -> dict:
    cleaned: dict = {"version": STATE_VERSION}
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
        self.notices_path = self.home / "state" / PLUGIN_ID / "autoreset-notices.json"
        self.lock_path = self.home / "state" / PLUGIN_ID / "autoreset.lock"
        self.notices_lock_path = (
            self.home / "state" / PLUGIN_ID / "autoreset-notices.lock"
        )
        self.clock = clock

    @staticmethod
    def empty() -> dict:
        return {"version": STATE_VERSION, "pending": None}

    @staticmethod
    def empty_notices() -> dict:
        return {"version": STATE_VERSION, "notices": {}}

    def _quarantine(self) -> Path:
        stamp = int(self.clock())
        candidate = self.path.with_name(f"autoreset.corrupt.{stamp}.json")
        suffix = 1
        while candidate.exists():
            candidate = self.path.with_name(f"autoreset.corrupt.{stamp}.{suffix}.json")
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

    def _write_json(self, path: Path, state: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent
        )
        temp_path = Path(temp_name)
        try:
            try:
                os.fchmod(descriptor, 0o600)
            except (AttributeError, OSError):
                pass
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(state, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            try:
                path.chmod(0o600)
            except OSError:
                pass
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

    def write(self, state: dict) -> None:
        self._write_json(self.path, _clean_state(state))

    def _load_notices(self) -> dict:
        if not self.notices_path.exists():
            return self.empty_notices()
        try:
            loaded = json.loads(self.notices_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict) or loaded.get("version") != STATE_VERSION:
                raise ValueError("unsupported or malformed auto-reset notices")
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            return self.empty_notices()
        return _clean_notices(loaded)

    def _write_notices(self, state: dict) -> None:
        self._write_json(self.notices_path, _clean_notices(state))

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
        with acquire_notice_lock(home=self.home, now=timestamp) as acquired:
            if not acquired:
                return False
            state = self._load_notices()
            notices = self._prune_notices(state, timestamp)
            notices[session_id] = {"message": message, "created_at": timestamp}
            self._write_notices(state)
            return True

    def pop_notice(self, session_id: str, *, now: float | None = None) -> str | None:
        if not session_id:
            return None
        timestamp = self.clock() if now is None else now
        with acquire_notice_lock(home=self.home, now=timestamp) as acquired:
            if not acquired:
                return None
            state = self._load_notices()
            notices = self._prune_notices(state, timestamp)
            notice = notices.pop(session_id, None)
            self._write_notices(state)
            if notice is None:
                return None
            message = notice.get("message")
            return message if isinstance(message, str) else None

    @staticmethod
    def _prune_fallback_notices(state: dict, now: float) -> dict:
        notices = state.get("fallback_notices")
        if not isinstance(notices, dict):
            notices = {}
        state["fallback_notices"] = {
            session_id: notice
            for session_id, notice in notices.items()
            if isinstance(notice, dict)
            and isinstance(notice.get("created_at"), (int, float))
            and now - notice["created_at"] <= NOTICE_TTL_SECONDS
        }
        return state["fallback_notices"]

    def queue_fallback_notice_locked(
        self, state: dict, session_id: str, message: str, *, now: float
    ) -> bool:
        """Persist terminal state and its notice in one coordinator-locked write."""
        notice_persisted = bool(session_id)
        if notice_persisted:
            notices = self._prune_fallback_notices(state, now)
            notices[session_id] = {"message": message, "created_at": now}
        self.write(state)
        return notice_persisted

    def pop_fallback_notice(
        self, session_id: str, *, now: float | None = None
    ) -> str | None:
        if not session_id:
            return None
        timestamp = self.clock() if now is None else now
        with acquire_autoreset_lock(home=self.home, now=timestamp) as acquired:
            if not acquired:
                return None
            state = self.load()
            notices = self._prune_fallback_notices(state, timestamp)
            notice = notices.pop(session_id, None)
            self.write(state)
            if notice is None:
                return None
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


def _lock_identity(path: Path) -> tuple[int, int] | None:
    """Return filesystem identity so stale reclaim cannot target a replacement."""
    try:
        stat_result = path.stat()
    except OSError:
        return None
    return stat_result.st_dev, stat_result.st_ino


def _reclaim_guard_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.reclaim")


def _try_create_lock(
    path: Path, owner: str, now: float, *, ignore_reclaim_guard: bool = False
) -> bool:
    guard_path = _reclaim_guard_path(path)
    if not ignore_reclaim_guard and guard_path.exists():
        return False
    try:
        path.mkdir()
    except FileExistsError:
        return False
    if not ignore_reclaim_guard and guard_path.exists():
        try:
            path.rmdir()
        except OSError:
            pass
        return False
    metadata_path = path / "owner.json"
    try:
        descriptor = os.open(metadata_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"owner": owner, "pid": os.getpid(), "created_at": now}, handle)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        try:
            _remove_lock_dir(path)
        except OSError:
            pass
        return False
    return True


def _reclaim_stale_lock(
    path: Path,
    owner: str,
    *,
    expected_identity: tuple[int, int],
    now: float,
) -> bool:
    guard_path = _reclaim_guard_path(path)
    try:
        guard_path.mkdir()
    except (FileExistsError, OSError):
        return False
    try:
        if _lock_identity(path) != expected_identity or not _lock_is_stale(path, now):
            return False
        stale_path = path.with_name(f"{path.name}.stale.{os.getpid()}.{owner}")
        try:
            os.rename(path, stale_path)
        except (FileNotFoundError, FileExistsError, OSError):
            return False
        try:
            _remove_lock_dir(stale_path)
        except OSError:
            return False
        return _try_create_lock(path, owner, now, ignore_reclaim_guard=True)
    finally:
        try:
            guard_path.rmdir()
        except OSError:
            pass


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
    observed_identity = _lock_identity(path)
    if (
        not acquired
        and observed_identity is not None
        and _lock_is_stale(path, timestamp)
    ):
        acquired = _reclaim_stale_lock(
            path,
            owner,
            expected_identity=observed_identity,
            now=timestamp,
        )
    try:
        yield acquired
    finally:
        if acquired:
            _release_owned_lock(path, owner)


@contextmanager
def acquire_notice_lock(
    *, home: Path | None = None, now: float | None = None
) -> Iterator[bool]:
    """Acquire the notice-file lock without touching the coordinator lock."""
    lock_home = Path(home) if home is not None else _hermes_home()
    path = lock_home / "state" / PLUGIN_ID / "autoreset-notices.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = time.time() if now is None else now
    owner = str(uuid4())
    acquired = _try_create_lock(path, owner, timestamp)
    observed_identity = _lock_identity(path)
    if (
        not acquired
        and observed_identity is not None
        and _lock_is_stale(path, timestamp)
    ):
        acquired = _reclaim_stale_lock(
            path,
            owner,
            expected_identity=observed_identity,
            now=timestamp,
        )
    try:
        yield acquired
    finally:
        if acquired:
            _release_owned_lock(path, owner)


COOLDOWN_RETRY_SECONDS = 60.0
COOLDOWN_EXHAUSTED_SECONDS = 5 * 60.0
COOLDOWN_SUCCESS_SECONDS = 5 * 60.0
TRANSIENT_HTTP_STATUS_CODES = frozenset({408, 409, 425, 429})


@dataclass(frozen=True)
class AutoResetResult:
    status: str
    before_remaining: int | float | None = None
    after_remaining: int | float | None = None
    before_credits: int | None = None
    after_credits: int | None = None
    after_usage: dict | None = None
    message: str | None = None
    notice_persisted: bool = False


def _usage_credit_count(usage: dict) -> int | None:
    count = usage.get("reset_credits_available")
    if isinstance(count, bool) or not isinstance(count, int):
        return None
    return count


def _set_cooldown(
    state: dict, *, now: float, seconds: float, reason: str, clear_pending: bool
) -> None:
    state["cooldown_until"] = now + seconds
    state["cooldown_reason"] = reason
    if clear_pending:
        state["pending"] = None


def _clear_cooldown(state: dict) -> None:
    state.pop("cooldown_until", None)
    state.pop("cooldown_reason", None)


def _is_deterministic_auth_or_validation_error(exc: Exception) -> bool:
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    status_code = exc.response.status_code
    return 400 <= status_code < 500 and status_code not in TRANSIENT_HTTP_STATUS_CODES


def _pending_record(state: dict) -> dict | None:
    pending = state.get("pending")
    if not isinstance(pending, dict) or pending.get("status") != "pending":
        return None
    request_id = pending.get("redeem_request_id")
    credit_id = pending.get("credit_id")
    if not isinstance(request_id, str) or not request_id:
        return None
    if not isinstance(credit_id, str) or not credit_id:
        return None
    return pending


def _notice_message(
    *,
    status: str,
    before_remaining: int | float | None,
    after_remaining: int | float | None,
    before_credits: int | None,
    after_credits: int | None,
) -> str:
    if (
        before_remaining is not None
        and after_remaining is not None
        and before_credits is not None
        and after_credits is not None
    ):
        return (
            "Codex auto reset | "
            f"weekly {before_remaining:g}% → {after_remaining:g}% | "
            f"reset credits {before_credits} → {after_credits}"
        )
    if status == "reset":
        return "Codex auto reset | reset accepted; usage refresh unavailable"
    return "Codex auto reset | reset already redeemed; usage refresh unavailable"


def maybe_autoreset(
    *,
    model: str | None,
    usage: dict | None = None,
    session_id: str = "",
    turn_id: str = "",
    config: AutoResetConfig | None = None,
    store: Any = None,
    usage_fetcher: Callable[[], dict] | None = None,
    credit_lister: Callable[[], dict] | None = None,
    consumer: Callable[[str, str | None], dict | None] | None = None,
    uuid_factory: Callable[[], object] | None = None,
    lock_factory: Callable[[], AbstractContextManager[bool]] | None = None,
    clock: Callable[[], float] = time.time,
    audit_log: Any = None,
) -> AutoResetResult:
    """Attempt one synchronous, fail-closed, idempotent Codex auto reset."""
    del turn_id  # Reserved for future non-sensitive audit correlation.
    audit = audit_log if audit_log is not None else autoreset_audit
    try:
        effective = config if config is not None else load_autoreset_config()
        if not effective.valid:
            return AutoResetResult("invalid_config", message=effective.error)
        if not effective.enabled:
            return AutoResetResult("disabled")
        if not matches_codex_model(model):
            return AutoResetResult("not_codex")

        fetch_usage = usage_fetcher or (lambda: get_usage_for_model(model) or {})
        list_credits = credit_lister or list_rate_limit_reset_credits
        consume = consumer or consume_rate_limit_reset_credit
        make_uuid = uuid_factory or uuid4
        state_store = store or AutoResetStateStore(clock=clock)

        initial_usage = usage
        if initial_usage is None:
            now = clock()
            try:
                initial_usage = fetch_usage()
            except Exception as exc:
                make_lock = lock_factory or (
                    lambda: acquire_autoreset_lock(home=state_store.home, now=now)
                )
                with make_lock() as acquired:
                    if not acquired:
                        return AutoResetResult("busy", message=str(exc))
                    state = state_store.load()
                    _set_cooldown(
                        state,
                        now=now,
                        seconds=COOLDOWN_RETRY_SECONDS,
                        reason="transient",
                        clear_pending=False,
                    )
                    state_store.write(state)
                return AutoResetResult("transient", message=str(exc))
        if not isinstance(initial_usage, dict):
            return AutoResetResult("ineligible")
        before_remaining = weekly_remaining(initial_usage)
        before_credits = _usage_credit_count(initial_usage)
        now = clock()
        prelock_state = state_store.load()
        prelock_pending = _pending_record(prelock_state)
        if state_store.cooldown_active(prelock_state, now=now):
            return AutoResetResult(
                "cooldown",
                before_remaining=before_remaining,
                before_credits=before_credits,
            )
        if prelock_pending is not None:
            retry_after = prelock_pending.get("retry_after")
            if isinstance(retry_after, (int, float)) and now < retry_after:
                return AutoResetResult(
                    "cooldown",
                    before_remaining=before_remaining,
                    before_credits=before_credits,
                )
        elif not is_eligible(model=model, usage=initial_usage, config=effective):
            return AutoResetResult(
                "ineligible",
                before_remaining=before_remaining,
                before_credits=before_credits,
            )

        make_lock = lock_factory or (
            lambda: acquire_autoreset_lock(home=state_store.home, now=now)
        )
        with make_lock() as acquired:
            if not acquired:
                return AutoResetResult(
                    "busy",
                    before_remaining=before_remaining,
                    before_credits=before_credits,
                )

            state = state_store.load()
            if state_store.cooldown_active(state, now=now):
                return AutoResetResult(
                    "cooldown",
                    before_remaining=before_remaining,
                    before_credits=before_credits,
                )
            pending = _pending_record(state)
            if pending is not None:
                retry_after = pending.get("retry_after")
                if isinstance(retry_after, (int, float)) and now < retry_after:
                    return AutoResetResult(
                        "cooldown",
                        before_remaining=before_remaining,
                        before_credits=before_credits,
                    )

            try:
                live_usage = fetch_usage()
            except Exception as exc:
                _set_cooldown(
                    state,
                    now=now,
                    seconds=COOLDOWN_RETRY_SECONDS,
                    reason="transient",
                    clear_pending=False,
                )
                state_store.write(state)
                return AutoResetResult("transient", message=str(exc))
            if not isinstance(live_usage, dict):
                return AutoResetResult("ineligible")
            live_remaining = weekly_remaining(live_usage)
            live_credits = _usage_credit_count(live_usage)
            if pending is None and not is_eligible(
                model=model, usage=live_usage, config=effective
            ):
                return AutoResetResult(
                    "ineligible",
                    before_remaining=live_remaining,
                    before_credits=live_credits,
                )

            if pending is None:
                before_remaining = weekly_remaining(live_usage)
                before_credits = _usage_credit_count(live_usage)
                try:
                    details = list_credits()
                except Exception as exc:
                    _set_cooldown(
                        state,
                        now=now,
                        seconds=COOLDOWN_RETRY_SECONDS,
                        reason="transient",
                        clear_pending=False,
                    )
                    state_store.write(state)
                    return AutoResetResult("transient", message=str(exc))
                selected = (
                    select_earliest_available_credit(details)
                    if isinstance(details, dict)
                    else None
                )
                if selected is None:
                    _set_cooldown(
                        state,
                        now=now,
                        seconds=COOLDOWN_EXHAUSTED_SECONDS,
                        reason="no_credit",
                        clear_pending=True,
                    )
                    state_store.write(state)
                    return AutoResetResult(
                        "no_credit",
                        before_remaining=before_remaining,
                        before_credits=before_credits,
                    )
                request_id = str(make_uuid())
                credit_id = selected["id"]
                pending = {
                    "redeem_request_id": request_id,
                    "credit_id": credit_id,
                    "status": "pending",
                    "created_at": now,
                    "updated_at": now,
                    "retry_after": now,
                    "before_remaining": before_remaining,
                    "before_credits": before_credits,
                }
                state["pending"] = pending
                _clear_cooldown(state)
                state_store.write(state)
            else:
                request_id = pending["redeem_request_id"]
                credit_id = pending["credit_id"]
                before_remaining = pending.get("before_remaining")
                before_credits = pending.get("before_credits")

            try:
                response = consume(request_id, credit_id)
            except Exception as exc:
                if _is_deterministic_auth_or_validation_error(exc):
                    _set_cooldown(
                        state,
                        now=now,
                        seconds=COOLDOWN_EXHAUSTED_SECONDS,
                        reason="auth_or_validation_error",
                        clear_pending=True,
                    )
                    state_store.write(state)
                    return AutoResetResult(
                        "auth_or_validation_error",
                        before_remaining=before_remaining,
                        before_credits=before_credits,
                        message=str(exc),
                    )
                pending["updated_at"] = now
                pending["retry_after"] = now + COOLDOWN_RETRY_SECONDS
                pending["status"] = "pending"
                state["pending"] = pending
                state_store.write(state)
                return AutoResetResult(
                    "pending",
                    before_remaining=before_remaining,
                    before_credits=before_credits,
                    message=str(exc),
                )

            code = None
            if isinstance(response, dict):
                # Coalesce so a JSON-null "code" still falls back to "status";
                # dict.get's default only fires when the key is absent.
                code = response.get("code") or response.get("status")
            if code in {"reset", "already_redeemed"}:
                after_usage = None
                after_remaining = None
                after_credits = None
                try:
                    refreshed = fetch_usage()
                    if isinstance(refreshed, dict):
                        after_usage = refreshed
                        after_remaining = weekly_remaining(refreshed)
                        after_credits = _usage_credit_count(refreshed)
                except Exception:
                    pass
                message = _notice_message(
                    status=code,
                    before_remaining=before_remaining,
                    after_remaining=after_remaining,
                    before_credits=before_credits,
                    after_credits=after_credits,
                )
                _set_cooldown(
                    state,
                    now=now,
                    seconds=COOLDOWN_SUCCESS_SECONDS,
                    reason="success",
                    clear_pending=True,
                )
                notice_persisted = state_store.queue_fallback_notice_locked(
                    state, session_id, message, now=now
                )
                # Best-effort local history: any failure here must not change the
                # reset outcome or notice, and the exception detail (which may
                # carry backend data) must never reach the log.
                try:
                    event = audit.build_success_event(
                        redeem_request_id=request_id,
                        observed_at=now,
                        backend_status=code,
                        weekly_before=before_remaining,
                        weekly_after=after_remaining,
                        credits_before=before_credits,
                        credits_after=after_credits,
                    )
                    audit.append_success_event(event, home=state_store.home)
                except Exception:  # noqa: BLE001 - history append is best-effort
                    logger.warning("auto-reset history append failed")
                return AutoResetResult(
                    code,
                    before_remaining=before_remaining,
                    after_remaining=after_remaining,
                    before_credits=before_credits,
                    after_credits=after_credits,
                    after_usage=after_usage,
                    message=message,
                    notice_persisted=notice_persisted,
                )

            if code in {"nothing_to_reset", "no_credit"}:
                _set_cooldown(
                    state,
                    now=now,
                    seconds=COOLDOWN_EXHAUSTED_SECONDS,
                    reason=code,
                    clear_pending=True,
                )
                state_store.write(state)
                return AutoResetResult(
                    code,
                    before_remaining=before_remaining,
                    before_credits=before_credits,
                )

            pending["updated_at"] = now
            pending["retry_after"] = now + COOLDOWN_EXHAUSTED_SECONDS
            pending["status"] = "pending"
            state["pending"] = pending
            _set_cooldown(
                state,
                now=now,
                seconds=COOLDOWN_EXHAUSTED_SECONDS,
                reason="unknown",
                clear_pending=False,
            )
            state_store.write(state)
            return AutoResetResult(
                "unknown",
                before_remaining=before_remaining,
                before_credits=before_credits,
            )
    except Exception as exc:
        return AutoResetResult("error", message=str(exc))
