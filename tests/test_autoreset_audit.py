"""Tests for the privacy-minimized Codex auto-reset audit history."""

from __future__ import annotations

import hashlib
import json
import math
import os
import types
from typing import cast

import pytest

from plugin import autoreset_audit, hermes_home
from plugin.autoreset_audit import (
    AUDIT_EVENT_TYPE,
    AUDIT_SCHEMA_VERSION,
    AutoResetAuditLog,
    audit_event_id,
    build_success_event,
    validate_event,
)


def _success_event(**overrides):
    values = {
        "redeem_request_id": "request-uuid",
        "observed_at": 1_721_000_000.125,
        "backend_status": "reset",
        "trigger": "pre_llm_call",
        "before_remaining": 0,
        "after_remaining": 100,
        "before_credits": 3,
        "after_credits": 2,
    }
    values.update(overrides)
    return build_success_event(**values)


def test_success_event_has_exact_schema_and_values():
    event = _success_event()

    assert event == {
        "schema_version": 1,
        "event_type": "codex_autoreset_succeeded",
        "event_id": "sha256:" + hashlib.sha256(b"request-uuid").hexdigest(),
        "observed_at": "2024-07-14T23:33:20.125000Z",
        "backend_status": "reset",
        "trigger": "pre_llm_call",
        "before": {"weekly_remaining_percent": 0, "reset_credits": 3},
        "after": {"weekly_remaining_percent": 100, "reset_credits": 2},
    }
    assert set(event) == {
        "schema_version",
        "event_type",
        "event_id",
        "observed_at",
        "backend_status",
        "trigger",
        "before",
        "after",
    }
    assert set(event["before"]) == {"weekly_remaining_percent", "reset_credits"}
    assert set(event["after"]) == {"weekly_remaining_percent", "reset_credits"}


def test_event_schema_omits_every_raw_identifier():
    serialized = json.dumps(_success_event(), sort_keys=True)

    assert "request-uuid" not in serialized
    for forbidden in (
        "redeem_request_id",
        "credit_id",
        "session_id",
        "turn_id",
        "user_id",
        "account_id",
        "model",
        "prompt",
        "response",
        "credential",
        "backend_body",
    ):
        assert forbidden not in serialized


def test_audit_event_id_rejects_empty_or_non_string_values():
    for value in ("", None, 7):
        with pytest.raises(ValueError):
            audit_event_id(cast(str, value))


@pytest.mark.parametrize("backend_status", ["", "success", "failed", None])
def test_event_rejects_unsupported_backend_status(backend_status):
    with pytest.raises(ValueError):
        _success_event(backend_status=backend_status)


@pytest.mark.parametrize("trigger", ["", "footer_hook", "manual", None])
def test_event_rejects_unsupported_trigger(trigger):
    with pytest.raises(ValueError):
        _success_event(trigger=trigger)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observed_at", True),
        ("before_remaining", True),
        ("after_remaining", False),
        ("before_credits", True),
        ("after_credits", False),
    ],
)
def test_event_rejects_bool_as_number(field, value):
    with pytest.raises(ValueError):
        _success_event(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [("before_credits", -1), ("after_credits", -1)],
)
def test_event_rejects_negative_credits(field, value):
    with pytest.raises(ValueError):
        _success_event(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("before_remaining", math.nan),
        ("before_remaining", math.inf),
        ("after_remaining", -math.inf),
    ],
)
def test_event_rejects_non_finite_percentages(field, value):
    with pytest.raises(ValueError):
        _success_event(**{field: value})


@pytest.mark.parametrize(
    "event_id",
    [
        "request-uuid",
        "sha256:",
        "sha256:" + "0" * 63,
        "sha256:" + "0" * 65,
        "sha256:" + "G" * 64,
        7,
    ],
)
def test_schema_rejects_malformed_event_ids(event_id):
    event = _success_event()
    event["event_id"] = event_id

    with pytest.raises(ValueError):
        validate_event(event)


def test_refresh_unavailable_event_has_nullable_after_fields():
    event = _success_event(after_remaining=None, after_credits=None)

    assert event["after"] == {
        "weekly_remaining_percent": None,
        "reset_credits": None,
    }
    assert event["schema_version"] == AUDIT_SCHEMA_VERSION
    assert event["event_type"] == AUDIT_EVENT_TYPE


def _compact_line(event):
    return json.dumps(event, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"


def test_first_append_writes_one_compact_json_line_and_fsyncs(monkeypatch, tmp_path):
    event = _success_event()
    store = AutoResetAuditLog(home=tmp_path)
    real_open = os.open
    real_write = os.write
    real_fsync = os.fsync
    opened = []
    writes = []
    fsyncs = []

    def recording_open(path, flags, mode=0o777):
        opened.append((path, flags, mode))
        return real_open(path, flags, mode)

    def recording_write(descriptor, data):
        writes.append(bytes(data))
        return real_write(descriptor, data)

    def recording_fsync(descriptor):
        fsyncs.append(descriptor)
        return real_fsync(descriptor)

    monkeypatch.setattr(autoreset_audit.os, "open", recording_open)
    monkeypatch.setattr(autoreset_audit.os, "write", recording_write)
    monkeypatch.setattr(autoreset_audit.os, "fsync", recording_fsync)

    assert store.append_once(event) is True

    assert store.path.read_bytes() == _compact_line(event)
    assert len(opened) == 1
    _, flags, mode = opened[0]
    assert flags & os.O_APPEND
    assert flags & os.O_CREAT
    assert flags & os.O_WRONLY
    assert not flags & os.O_TRUNC
    assert mode == 0o600
    assert writes == [_compact_line(event)]
    assert len(fsyncs) == 1


def test_duplicate_event_id_is_a_noop(tmp_path):
    event = _success_event()
    store = AutoResetAuditLog(home=tmp_path)
    store.path.parent.mkdir(parents=True)
    unsupported = {**event, "schema_version": 999}
    store.path.write_bytes(_compact_line(unsupported))

    assert store.append_once(event) is True
    after_first = store.path.read_bytes()
    assert store.append_once(event) is False
    assert store.path.read_bytes() == after_first
    assert after_first.count(_compact_line(event)) == 1


def test_audit_file_mode_is_owner_only(tmp_path):
    store = AutoResetAuditLog(home=tmp_path)

    assert store.append_once(_success_event()) is True

    assert store.path.stat().st_mode & 0o777 == 0o600


def test_append_completes_short_os_writes(monkeypatch, tmp_path):
    store = AutoResetAuditLog(home=tmp_path)
    event = _success_event()
    real_write = os.write
    calls = []

    def short_write(descriptor, data):
        chunk = bytes(data[:3])
        calls.append(chunk)
        return real_write(descriptor, chunk)

    monkeypatch.setattr(autoreset_audit.os, "write", short_write)

    assert store.append_once(event) is True

    assert len(calls) > 1
    assert store.path.read_bytes() == _compact_line(event)


def test_partial_trailing_line_gets_only_newline_then_valid_event(tmp_path):
    store = AutoResetAuditLog(home=tmp_path)
    store.path.parent.mkdir(parents=True)
    partial = b'{"partial":"raw-secret"'
    store.path.write_bytes(partial)
    event = _success_event()

    assert store.append_once(event) is True

    assert store.path.read_bytes() == partial + b"\n" + _compact_line(event)


def test_valid_json_without_trailing_newline_is_malformed_and_preserved(tmp_path):
    store = AutoResetAuditLog(home=tmp_path)
    store.path.parent.mkdir(parents=True)
    unterminated_event = _success_event(redeem_request_id="unterminated")
    unterminated = _compact_line(unterminated_event).removesuffix(b"\n")
    store.path.write_bytes(unterminated)
    next_event = _success_event(redeem_request_id="next")

    assert store.read_events() == ([], 1)
    assert store.append_once(next_event) is True

    assert store.path.read_bytes() == unterminated + b"\n" + _compact_line(next_event)
    assert store.read_events() == ([unterminated_event, next_event], 0)


def test_retry_of_complete_same_event_missing_only_newline_finishes_once(
    monkeypatch, tmp_path
):
    store = AutoResetAuditLog(home=tmp_path)
    store.path.parent.mkdir(parents=True)
    event = _success_event(redeem_request_id="same-event-crash")
    unterminated = _compact_line(event).removesuffix(b"\n")
    store.path.write_bytes(unterminated)
    real_fsync = os.fsync
    fsyncs = []

    def recording_fsync(descriptor):
        fsyncs.append(descriptor)
        return real_fsync(descriptor)

    monkeypatch.setattr(autoreset_audit.os, "fsync", recording_fsync)

    assert store.read_events() == ([], 1)
    assert store.append_once(event) is False

    assert store.path.read_bytes() == _compact_line(event)
    assert store.read_events() == ([event], 0)
    assert len(fsyncs) == 1


def test_visible_matching_line_retries_fsync_before_dedup_success(
    monkeypatch, tmp_path
):
    store = AutoResetAuditLog(home=tmp_path)
    event = _success_event(redeem_request_id="fsync-retry")
    real_fsync = os.fsync
    attempts = 0

    def fail_once(descriptor):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("simulated fsync failure")
        return real_fsync(descriptor)

    monkeypatch.setattr(autoreset_audit.os, "fsync", fail_once)

    with pytest.raises(OSError, match="simulated fsync failure"):
        store.append_once(event)
    assert store.path.read_bytes() == _compact_line(event)

    assert store.append_once(event) is False
    assert attempts == 2
    assert store.read_events() == ([event], 0)


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "fchmod"),
    reason="owner-only POSIX mode enforcement is unavailable",
)
def test_existing_permissive_file_is_owner_only_before_write(monkeypatch, tmp_path):
    store = AutoResetAuditLog(home=tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_bytes(b"existing\n")
    store.path.chmod(0o644)
    real_chmod = autoreset_audit.Path.chmod
    real_write = os.write

    def unavailable_fchmod(descriptor, mode):
        raise AttributeError("fchmod unavailable")

    def checked_write(descriptor, data):
        assert store.path.stat().st_mode & 0o777 == 0o600
        return real_write(descriptor, data)

    monkeypatch.setattr(autoreset_audit.os, "fchmod", unavailable_fchmod)
    monkeypatch.setattr(autoreset_audit.os, "write", checked_write)
    monkeypatch.setattr(autoreset_audit.Path, "chmod", real_chmod)

    assert store.append_once(_success_event()) is True
    assert store.path.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "fchmod"),
    reason="owner-only POSIX mode enforcement is unavailable",
)
def test_permission_enforcement_failure_prevents_write(monkeypatch, tmp_path):
    store = AutoResetAuditLog(home=tmp_path)
    store.path.parent.mkdir(parents=True)
    original = b"existing\n"
    store.path.write_bytes(original)
    store.path.chmod(0o644)

    def failed_mode_change(*args, **kwargs):
        raise OSError("mode change denied")

    monkeypatch.setattr(autoreset_audit.os, "fchmod", failed_mode_change)
    monkeypatch.setattr(autoreset_audit.Path, "chmod", failed_mode_change)

    with pytest.raises(OSError, match="mode change denied"):
        store.append_once(_success_event())

    assert store.path.read_bytes() == original


def test_append_never_calls_replace_truncate_unlink_or_rename(monkeypatch, tmp_path):
    store = AutoResetAuditLog(home=tmp_path)

    def destructive(*args, **kwargs):
        raise AssertionError("append-only storage called a destructive operation")

    for name in ("replace", "truncate", "unlink", "rename"):
        monkeypatch.setattr(autoreset_audit.os, name, destructive)
    for name in ("replace", "unlink", "rename"):
        monkeypatch.setattr(autoreset_audit.Path, name, destructive)

    assert store.append_once(_success_event()) is True


def test_read_events_returns_valid_events_and_malformed_count(tmp_path):
    store = AutoResetAuditLog(home=tmp_path)
    first = _success_event()
    second = _success_event(
        redeem_request_id="second-request", backend_status="already_redeemed"
    )
    store.path.parent.mkdir(parents=True)
    store.path.write_bytes(_compact_line(first) + b"not-json\n" + _compact_line(second))

    assert store.read_events() == ([first, second], 1)


def test_reader_skips_unknown_schema_and_event_type(tmp_path):
    store = AutoResetAuditLog(home=tmp_path)
    event = _success_event()
    unknown_schema = {**event, "schema_version": 2}
    unknown_type = {**event, "event_type": "future_event"}
    store.path.parent.mkdir(parents=True)
    store.path.write_bytes(
        _compact_line(unknown_schema) + _compact_line(event) + _compact_line(unknown_type)
    )

    assert store.read_events() == ([event], 2)


def test_reader_never_returns_or_logs_malformed_raw_content(caplog, tmp_path):
    store = AutoResetAuditLog(home=tmp_path)
    secret = "raw-request-secret"
    store.path.parent.mkdir(parents=True)
    store.path.write_text(f'{{"redeem_request_id":"{secret}"\n', encoding="utf-8")

    result = store.read_events()

    assert result == ([], 1)
    assert secret not in repr(result)
    assert secret not in caplog.text


def test_default_path_uses_injected_profile_home_logs_directory(monkeypatch, tmp_path):
    fake_constants = types.SimpleNamespace(get_hermes_home=lambda: tmp_path)
    imported = []

    def fake_import(name):
        imported.append(name)
        assert name == "hermes_constants"
        return fake_constants

    monkeypatch.setattr(hermes_home, "import_module", fake_import)

    store = AutoResetAuditLog()

    assert imported == ["hermes_constants"]
    assert store.path == tmp_path / "logs" / "hermes-usage-hook-autoreset.jsonl"


def test_profile_home_falls_back_to_explicit_env_without_hermes_constants(
    monkeypatch, tmp_path
):
    def missing_constants(name):
        raise ModuleNotFoundError(name=name)

    monkeypatch.setattr(hermes_home, "import_module", missing_constants)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    store = AutoResetAuditLog()

    assert store.home == tmp_path
    assert store.path == tmp_path / "logs" / "hermes-usage-hook-autoreset.jsonl"
