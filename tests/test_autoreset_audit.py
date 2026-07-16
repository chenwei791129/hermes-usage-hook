"""Tests for the best-effort auto-reset success history module.

``tests/conftest.py`` puts the repo root on ``sys.path`` so the plugin's
``plugin.hermes_home`` and ``plugin.autoreset_audit`` modules (which ship under
``plugin/``) import as a package.
"""

from __future__ import annotations

import json
import sys
import types

import pytest

from plugin import autoreset_audit
from plugin import hermes_home

# 2026-07-14T09:12:00Z as epoch seconds (UTC).
_OBSERVED_EPOCH = 1_784_020_320.0
_OBSERVED_RFC3339 = "2026-07-14T09:12:00Z"


# --- Requirement: History resolves the Hermes home via the profile-safe API ---


def test_injected_home_takes_precedence(tmp_path):
    # An explicit home wins over both the module and the environment.
    assert hermes_home.resolve_hermes_home(tmp_path) == tmp_path


def test_uses_get_hermes_home_when_module_importable(monkeypatch, tmp_path):
    fake = types.ModuleType("hermes_constants")
    fake.get_hermes_home = lambda: tmp_path / "profile-home"
    monkeypatch.setitem(sys.modules, "hermes_constants", fake)

    assert hermes_home.resolve_hermes_home() == tmp_path / "profile-home"


def test_falls_back_to_env_when_module_absent(monkeypatch, tmp_path):
    monkeypatch.delitem(sys.modules, "hermes_constants", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "env-home"))

    assert hermes_home.resolve_hermes_home() == tmp_path / "env-home"


# --- Requirement: Events are privacy-minimized flat records -------------------


def _build(**overrides):
    kwargs = {
        "redeem_request_id": "req-1",
        "observed_at": _OBSERVED_EPOCH,
        "backend_status": "reset",
        "weekly_before": 4,
        "weekly_after": 100,
        "credits_before": 3,
        "credits_after": 2,
    }
    kwargs.update(overrides)
    return autoreset_audit.build_success_event(**kwargs)


def test_build_success_event_is_a_flat_privacy_minimized_record():
    event = _build()

    assert event == {
        "event_id": (
            "sha256:9456bdfa12ea76959c94a3572f5d91c73d838622df0a8d9b4e815c276c6b7880"
        ),
        "observed_at": _OBSERVED_RFC3339,
        "backend_status": "reset",
        "weekly_before": 4,
        "weekly_after": 100,
        "credits_before": 3,
        "credits_after": 2,
    }
    # The raw redeem request ID never lands in the record.
    assert "req-1" not in json.dumps(event)


def test_build_success_event_accepts_already_redeemed():
    assert _build(backend_status="already_redeemed")["backend_status"] == (
        "already_redeemed"
    )


@pytest.mark.parametrize("bad_request_id", ["", None, 123])
def test_build_success_event_rejects_empty_request_id(bad_request_id):
    with pytest.raises(ValueError):
        _build(redeem_request_id=bad_request_id)


@pytest.mark.parametrize("bad_status", ["nothing_to_reset", "", "RESET", None])
def test_build_success_event_rejects_invalid_backend_status(bad_status):
    with pytest.raises(ValueError):
        _build(backend_status=bad_status)


@pytest.mark.parametrize(
    "bad_observed_at", [float("nan"), float("inf"), float("-inf"), "now", None]
)
def test_build_success_event_rejects_non_finite_observed_at(bad_observed_at):
    with pytest.raises(ValueError):
        _build(observed_at=bad_observed_at)


@pytest.mark.parametrize(
    ("input_value", "stored_value"),
    [(4, 4), (101, None), (True, None), (float("nan"), None), ("5", None)],
)
def test_weekly_snapshot_coercion(input_value, stored_value):
    event = _build(weekly_before=input_value)
    assert event["weekly_before"] == stored_value


# --- Requirement: best-effort append, deduplicated by event_id ----------------


def _history_path(home):
    return home / "logs" / autoreset_audit._HISTORY_FILENAME


def test_append_writes_one_line_to_the_history_file(tmp_path):
    event = _build()

    assert autoreset_audit.append_success_event(event, home=tmp_path) is True

    lines = _history_path(tmp_path).read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == event


def test_append_creates_the_logs_directory_when_missing(tmp_path):
    assert not (tmp_path / "logs").exists()

    autoreset_audit.append_success_event(_build(), home=tmp_path)

    assert _history_path(tmp_path).exists()


def test_append_skips_duplicate_event_id(tmp_path):
    event = _build()

    assert autoreset_audit.append_success_event(event, home=tmp_path) is True
    assert autoreset_audit.append_success_event(event, home=tmp_path) is False

    lines = _history_path(tmp_path).read_text().splitlines()
    assert len(lines) == 1


def test_append_writes_compact_json(tmp_path):
    autoreset_audit.append_success_event(_build(), home=tmp_path)

    raw = _history_path(tmp_path).read_text().splitlines()[0]
    # Compact separators: no spaces after ':' or ','.
    assert ", " not in raw and ": " not in raw


def test_append_succeeds_even_when_chmod_fails(monkeypatch, tmp_path):
    def boom(*_args, **_kwargs):
        raise PermissionError("chmod not supported")

    monkeypatch.setattr(autoreset_audit.os, "chmod", boom)

    assert autoreset_audit.append_success_event(_build(), home=tmp_path) is True
    assert _history_path(tmp_path).exists()


# --- Requirement: lenient read that skips malformed lines ---------------------


def test_read_events_returns_empty_list_when_file_missing(tmp_path):
    assert autoreset_audit.read_events(home=tmp_path) == []


def test_read_events_skips_malformed_lines_and_keeps_append_order(tmp_path, caplog):
    valid_first = _build(redeem_request_id="req-1")
    valid_second = _build(redeem_request_id="req-2")
    path = _history_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(valid_first)
        + "\n"
        + "{ SECRET-BROKEN-JSON not-parseable\n"
        + json.dumps({"observed_at": _OBSERVED_RFC3339})  # missing event_id
        + "\n"
        + json.dumps(valid_second)
        + "\n"
    )

    with caplog.at_level(0):
        events = autoreset_audit.read_events(home=tmp_path)

    assert [event["event_id"] for event in events] == [
        valid_first["event_id"],
        valid_second["event_id"],
    ]
    # The raw malformed line content must never surface in logs.
    assert "SECRET-BROKEN-JSON" not in caplog.text


def test_read_events_skips_a_non_utf8_line_without_discarding_history(tmp_path):
    # A single non-UTF-8 byte must skip only its line, not raise
    # UnicodeDecodeError and hide every valid event (which would also block
    # future appends, since the dedup scan reads through the same path).
    valid = _build(redeem_request_id="req-1")
    path = _history_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(
        json.dumps(valid).encode("utf-8")
        + b"\n"
        + b"\xff\xfe not valid utf-8\n"
        + json.dumps(_build(redeem_request_id="req-2")).encode("utf-8")
        + b"\n"
    )

    events = autoreset_audit.read_events(home=tmp_path)

    assert len(events) == 2


def test_append_still_works_when_file_has_a_non_utf8_line(tmp_path):
    path = _history_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff\xfe corrupt\n")

    assert autoreset_audit.append_success_event(_build(), home=tmp_path) is True
    assert len(autoreset_audit.read_events(home=tmp_path)) == 1
