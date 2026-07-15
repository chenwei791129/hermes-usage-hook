"""Network-free cross-process coordinator lock for Codex auto reset."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

PLUGIN_ID = "hermes-usage-hook"
LOCK_STALE_SECONDS = 120.0


def _hermes_home() -> Path:
    """Return the active profile's Hermes home without importing Hermes."""
    return Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()


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
