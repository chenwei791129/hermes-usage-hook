"""Tests for install.py: config enablement and plugin-directory copy.

These exercise our own installer logic (idempotency, preserving existing config
keys, overwrite-on-reinstall) — not pyyaml itself. install.py lives at the repo
root, so add the repo root to sys.path to import it.

Run the suite with pyyaml available (install.py imports it):

    uv run --with pytest --with httpx --with pyyaml python -m pytest tests -v
"""

from __future__ import annotations

import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import install  # noqa: E402

# The installer derives the name from the manifest; tests assert against that
# same source of truth rather than re-encoding the literal.
NAME = install.read_plugin_name(install.PLUGIN_SRC)


def test_read_plugin_name_matches_manifest():
    assert NAME == "hermes-usage-hook"


def test_enable_plugin_creates_config_when_absent(tmp_path):
    config = tmp_path / "config.yaml"
    install.enable_plugin(config, NAME)
    data = yaml.safe_load(config.read_text())
    assert data["plugins"]["enabled"] == [NAME]


def test_enable_plugin_preserves_existing_content(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {"gateway": {"port": 8080}, "plugins": {"enabled": ["other-plugin"]}}
        )
    )
    install.enable_plugin(config, NAME)
    data = yaml.safe_load(config.read_text())
    assert data["gateway"] == {"port": 8080}
    assert data["plugins"]["enabled"] == ["other-plugin", NAME]


def test_enable_plugin_is_idempotent(tmp_path):
    config = tmp_path / "config.yaml"
    install.enable_plugin(config, NAME)
    install.enable_plugin(config, NAME)
    data = yaml.safe_load(config.read_text())
    assert data["plugins"]["enabled"].count(NAME) == 1


def test_install_plugin_dir_copies_and_overwrites(tmp_path):
    hermes_home = tmp_path / "hermes"
    dest = install.install_plugin_dir(install.PLUGIN_SRC, hermes_home, NAME)
    assert (dest / "plugin.yaml").exists()
    assert (dest / "hooks" / "footer_hook.py").exists()
    # Re-running overwrites in place without nesting or error.
    dest_again = install.install_plugin_dir(install.PLUGIN_SRC, hermes_home, NAME)
    assert dest_again == dest
    assert (dest_again / "plugin.yaml").exists()
    assert not (dest_again / "plugin").exists()


def test_install_plugin_dir_replaces_prior_symlink(tmp_path):
    # A prior manual symlink install (per the README) must be unlinked, not
    # recursed into, before copying — otherwise shutil.rmtree would fail.
    hermes_home = tmp_path / "hermes"
    plugins = hermes_home / "plugins"
    plugins.mkdir(parents=True)
    (plugins / NAME).symlink_to(install.PLUGIN_SRC, target_is_directory=True)
    dest = install.install_plugin_dir(install.PLUGIN_SRC, hermes_home, NAME)
    assert dest.is_dir() and not dest.is_symlink()
    assert (dest / "plugin.yaml").exists()
