"""Tests for the profile-scoped, offline auto-reset history CLI."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import types
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from plugin import autoreset, autoreset_cli, autoreset_lock
from plugin.autoreset_audit import AutoResetAuditLog, build_success_event


def _event(
    index: int,
    *,
    observed_at: float | None = None,
    backend_status: str = "reset",
    trigger: str = "pre_llm_call",
    before_remaining: int | float | None = 0,
    after_remaining: int | float | None = 100,
    before_credits: int | None = 3,
    after_credits: int | None = 2,
) -> dict:
    return build_success_event(
        redeem_request_id=f"request-{index}",
        observed_at=1_721_000_000 + index if observed_at is None else observed_at,
        backend_status=backend_status,
        trigger=trigger,
        before_remaining=before_remaining,
        after_remaining=after_remaining,
        before_credits=before_credits,
        after_credits=after_credits,
    )


def _write_events(home, events: list[dict], *, malformed: bytes = b"") -> None:
    store = AutoResetAuditLog(home=home)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"".join(
        json.dumps(event, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
        for event in events
    )
    store.path.write_bytes(payload + malformed)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="usage-hook")
    autoreset_cli.register_cli(parser)
    return parser


def _run(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    return args.func(args)


def test_history_defaults_to_last_twenty_oldest_to_newest(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    events = [_event(index) for index in range(25)]
    _write_events(tmp_path, events)

    assert _run(["history", "--json"]) == 0

    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert output == events[-20:]


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "text"])
def test_last_requires_positive_integer(value):
    with pytest.raises(SystemExit) as raised:
        _parser().parse_args(["history", "--last", value])

    assert raised.value.code == 2


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("1s", 1), ("2m", 120), ("3h", 10_800), ("4d", 345_600)],
)
def test_since_accepts_positive_s_m_h_d_durations(value, seconds):
    args = _parser().parse_args(["history", "--since", value])

    assert args.since == seconds


@pytest.mark.parametrize("value", ["0s", "-1h", "1", "1w", "1.5h", "S"])
def test_since_rejects_non_positive_or_unsupported_durations(value):
    with pytest.raises(SystemExit) as raised:
        _parser().parse_args(["history", "--since", value])

    assert raised.value.code == 2


def test_since_rejects_duration_too_large_for_timedelta(capsys):
    with pytest.raises(SystemExit) as raised:
        _parser().parse_args(
            ["history", "--since", "999999999999999999999999999d"]
        )

    assert raised.value.code == 2
    assert "Traceback" not in capsys.readouterr().err


def test_since_filters_before_last_limit(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    now = datetime(2026, 7, 15, 12, tzinfo=timezone.utc).timestamp()
    events = [_event(index, observed_at=now - age) for index, age in enumerate((14_400, 7_200, 3_600, 60))]
    _write_events(tmp_path, events)
    monkeypatch.setattr(autoreset_cli, "_now_utc", lambda: datetime.fromtimestamp(now, timezone.utc))

    assert _run(["history", "--since", "3h", "--last", "2", "--json"]) == 0

    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert output == events[-2:]


def test_human_output_uses_local_timezone_and_question_marks(monkeypatch, tmp_path, capsys):
    if not hasattr(time, "tzset"):
        pytest.skip("host timezone switching is unavailable")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    # POSIX TZ offsets use the inverse sign: UTC+08 means eight hours west.
    monkeypatch.setenv("TZ", "UTC+08")
    time.tzset()
    event = _event(
        1,
        observed_at=datetime(2026, 7, 15, 12, 30, tzinfo=timezone.utc).timestamp(),
        backend_status="already_redeemed",
        trigger="transform_llm_output",
        before_remaining=None,
        after_remaining=87,
        before_credits=2,
        after_credits=None,
    )
    _write_events(tmp_path, [event])

    try:
        assert _run(["history"]) == 0
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()

    captured = capsys.readouterr()
    assert captured.out == (
        "2026-07-15 04:30:00 UTC | already_redeemed | transform_llm_output | "
        "weekly ? → 87 | credits 2 → ?\n"
    )
    assert captured.err == ""


def test_json_output_is_compact_jsonl_in_stored_utc(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    events = [_event(1), _event(2, backend_status="already_redeemed")]
    _write_events(tmp_path, events)

    assert _run(["history", "--json"]) == 0

    captured = capsys.readouterr()
    expected = "".join(
        json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n"
        for event in events
    )
    assert captured.out == expected
    assert '"observed_at":"2024-07-14T23:33:' in captured.out
    assert captured.err == ""


def test_missing_file_human_message_and_exit_zero(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    assert _run(["history"]) == 0

    captured = capsys.readouterr()
    assert captured.out == "No Codex auto-reset history found.\n"
    assert captured.err == ""


def test_missing_file_json_is_silent_and_exit_zero(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    assert _run(["history", "--json"]) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_malformed_lines_warn_only_on_stderr_without_raw_content(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    secret = b'not-json-with-secret-request-id\n'
    event = _event(1)
    _write_events(tmp_path, [event], malformed=secret)

    assert _run(["history", "--json"]) == 0

    captured = capsys.readouterr()
    assert captured.out == json.dumps(event, separators=(",", ":")) + "\n"
    assert captured.err == "Skipped 1 malformed auto-reset history line.\n"
    assert "secret-request-id" not in captured.out + captured.err


def test_unreadable_file_returns_one_without_traceback_or_secret_content(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    secret = "credential-secret-in-path"

    def unreadable(_self):
        raise PermissionError(f"denied /private/{secret}")

    monkeypatch.setattr(AutoResetAuditLog, "read_events", unreadable)

    assert _run(["history"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Unable to read Codex auto-reset history.\n"
    assert secret not in captured.err
    assert "Traceback" not in captured.err


def test_busy_coordinator_lock_returns_one_without_reading_history(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    reads = []

    @contextmanager
    def busy_lock(**_kwargs):
        yield False

    def forbidden_read(_self):
        reads.append(True)
        raise AssertionError("history was read without the coordinator lock")

    monkeypatch.setattr(autoreset_cli, "acquire_autoreset_lock", busy_lock)
    monkeypatch.setattr(AutoResetAuditLog, "read_events", forbidden_read)

    assert _run(["history"]) == 1

    captured = capsys.readouterr()
    assert reads == []
    assert captured.out == ""
    assert captured.err == "Codex auto-reset history is busy; try again.\n"


def test_clean_cli_import_never_imports_codex_transport_stack():
    script = r'''
import builtins
import sys

forbidden = (
    "httpx",
    "plugin.autoreset",
    "plugin.usage",
    "plugin.providers",
)
real_import = builtins.__import__


def guarded_import(name, *args, **kwargs):
    if any(name == item or name.startswith(f"{item}.") for item in forbidden):
        raise AssertionError(f"forbidden import: {name}")
    return real_import(name, *args, **kwargs)


builtins.__import__ = guarded_import
import plugin.autoreset_cli

loaded = sorted(
    name
    for name in sys.modules
    if any(name == item or name.startswith(f"{item}.") for item in forbidden)
)
assert loaded == [], loaded
'''

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=__file__.rsplit("/tests/", 1)[0],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_cli_handler_never_calls_codex_transport(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_events(tmp_path, [_event(1)])
    forbidden = []

    def network_call(*_args, **_kwargs):
        forbidden.append(True)
        raise AssertionError("offline history attempted a Codex transport call")

    from plugin.providers import codex_usage

    for name in (
        "_resolve_codex_auth",
        "get_codex_usage",
        "list_rate_limit_reset_credits",
        "consume_rate_limit_reset_credit",
    ):
        if hasattr(codex_usage, name):
            monkeypatch.setattr(codex_usage, name, network_call)

    assert _run(["history", "--json"]) == 0

    assert forbidden == []
    assert capsys.readouterr().err == ""


def test_autoreset_and_cli_use_same_lock_primitive():
    from plugin.autoreset_lock import acquire_autoreset_lock

    assert autoreset.acquire_autoreset_lock is acquire_autoreset_lock
    assert autoreset_cli.acquire_autoreset_lock is acquire_autoreset_lock


def test_all_state_surfaces_use_authoritative_named_profile_without_env(
    monkeypatch, tmp_path, capsys
):
    selected = tmp_path / "profiles" / "named"
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setitem(
        sys.modules,
        "hermes_constants",
        types.SimpleNamespace(get_hermes_home=lambda: selected),
    )

    state_store = autoreset.AutoResetStateStore(clock=lambda: 1_000.0)
    audit_store = AutoResetAuditLog()

    assert state_store.home == selected
    assert audit_store.home == selected
    with autoreset_lock.acquire_autoreset_lock(now=1_000.0) as acquired:
        assert acquired
        assert (
            selected / "state" / "hermes-usage-hook" / "autoreset.lock"
        ).is_dir()

    event = _event(31)
    _write_events(selected, [event])
    assert _run(["history", "--json"]) == 0
    assert capsys.readouterr().out == json.dumps(
        event, separators=(",", ":"), ensure_ascii=False
    ) + "\n"


def test_real_plugin_root_registration_and_cli_handler_make_no_transport_calls(
    tmp_path
):
    event = _event(41)
    _write_events(tmp_path, [event])
    script = r'''
import argparse
import httpx

import plugin
from plugin.providers import codex_usage

calls = []


def forbidden(*args, **kwargs):
    calls.append((args, kwargs))
    raise AssertionError("forbidden auth/transport call")


for name in (
    "_resolve_codex_auth",
    "get_codex_usage",
    "list_rate_limit_reset_credits",
    "consume_rate_limit_reset_credit",
):
    if hasattr(codex_usage, name):
        setattr(codex_usage, name, forbidden)
for owner in (httpx, httpx.Client):
    for name in ("get", "post", "request"):
        if hasattr(owner, name):
            setattr(owner, name, forbidden)


class Context:
    def __init__(self):
        self.cli = None

    def register_hook(self, *_args, **_kwargs):
        pass

    def register_cli_command(self, **kwargs):
        self.cli = kwargs


ctx = Context()
plugin.register(ctx)
assert ctx.cli is not None
parser = argparse.ArgumentParser(prog="usage-hook")
ctx.cli["setup_fn"](parser)
args = parser.parse_args(["history", "--json"])
assert ctx.cli["handler_fn"](args) == 0
assert calls == [], calls
'''
    env = os.environ.copy()
    env["HERMES_HOME"] = str(tmp_path)

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=__file__.rsplit("/tests/", 1)[0],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == json.dumps(
        event, separators=(",", ":"), ensure_ascii=False
    ) + "\n"
    assert completed.stderr == ""
