"""Tests for the footer model-display setting resolved from the plugin entry."""

from __future__ import annotations

import sys
import types

import pytest

from plugin import footer_config

_PREFIX = "[hermes-usage-hook]"


def _config_with_footer(footer):
    return {"plugins": {"entries": {"hermes-usage-hook": {"footer": footer}}}}


def _warning_lines(capsys) -> list[str]:
    return [line for line in capsys.readouterr().err.splitlines() if line]


@pytest.mark.parametrize(
    ("footer", "expected", "warns"),
    [
        ({}, False, False),
        ({"show_model": True}, True, False),
        ({"show_model": False}, False, False),
        ({"show_model": "true"}, False, True),
        ({"show_model": 1}, False, True),
        ({"show_model": None}, False, False),
    ],
    ids=["absent", "true", "false", "quoted-string", "integer", "null"],
)
def test_show_model_value_resolution(capsys, footer, expected, warns):
    result = footer_config.load_show_model(config=_config_with_footer(footer))

    assert result is expected
    lines = _warning_lines(capsys)
    if warns:
        assert len(lines) == 1
        assert lines[0].startswith(_PREFIX)
        assert "footer.show_model" in lines[0]
    else:
        assert lines == []


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"plugins": None},
        {"plugins": {"entries": None}},
        {"plugins": {"entries": {"hermes-usage-hook": None}}},
        _config_with_footer(None),
    ],
    ids=["no-plugins", "null-plugins", "null-entries", "null-entry", "null-footer"],
)
def test_absent_or_null_parents_disable_without_warning(capsys, config):
    assert footer_config.load_show_model(config=config) is False
    assert _warning_lines(capsys) == []


def test_non_mapping_footer_fails_closed_naming_footer_key(capsys):
    result = footer_config.load_show_model(config=_config_with_footer("on"))

    assert result is False
    lines = _warning_lines(capsys)
    assert len(lines) == 1
    assert lines[0].startswith(_PREFIX)
    assert "plugins.entries.hermes-usage-hook.footer " in lines[0]


def test_list_entries_fails_closed_naming_entries_key(capsys):
    result = footer_config.load_show_model(config={"plugins": {"entries": []}})

    assert result is False
    lines = _warning_lines(capsys)
    assert len(lines) == 1
    assert lines[0].startswith(_PREFIX)
    assert "plugins.entries " in lines[0]


def _install_hermes_config(monkeypatch, load_config):
    package = types.ModuleType("hermes_cli")
    module = types.ModuleType("hermes_cli.config")
    module.__dict__["load_config"] = load_config
    package.__dict__["config"] = module
    monkeypatch.setitem(sys.modules, "hermes_cli", package)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", module)


def test_load_config_failure_fails_closed_with_one_warning(monkeypatch, capsys):
    def exploding_load_config():
        raise RuntimeError("config.yaml unreadable")

    _install_hermes_config(monkeypatch, exploding_load_config)

    assert footer_config.load_show_model() is False
    lines = _warning_lines(capsys)
    assert len(lines) == 1
    assert lines[0].startswith(_PREFIX)


def test_default_source_reads_host_load_config(monkeypatch, capsys):
    _install_hermes_config(
        monkeypatch, lambda: _config_with_footer({"show_model": True})
    )

    assert footer_config.load_show_model() is True
    assert _warning_lines(capsys) == []


def test_missing_host_config_module_disables_without_warning(monkeypatch, capsys):
    # A None entry in sys.modules makes the import raise ImportError.
    monkeypatch.setitem(sys.modules, "hermes_cli.config", None)

    assert footer_config.load_show_model() is False
    assert _warning_lines(capsys) == []


def test_environment_variables_are_ignored(monkeypatch, capsys):
    for name in ("CODEX_SHOW_MODEL", "HERMES_USAGE_HOOK_SHOW_MODEL", "SHOW_MODEL"):
        monkeypatch.setenv(name, "true")

    assert footer_config.load_show_model(config={}) is False
    assert _warning_lines(capsys) == []
