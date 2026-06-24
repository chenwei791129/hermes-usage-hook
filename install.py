#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""One-command installer for the hermes-usage-hook plugin.

Run from the repo root:

    uv run install.py

It copies the ``plugin/`` directory to ``$HERMES_HOME/plugins/hermes-usage-hook/``
(``HERMES_HOME`` defaults to ``~/.hermes``) and adds ``hermes-usage-hook`` to the
``plugins.enabled`` list in ``$HERMES_HOME/config.yaml``, creating the config
file when absent. Re-running overwrites the installed directory and never adds a
duplicate ``plugins.enabled`` entry, preserving other keys and values (comments
and formatting in an existing config.yaml are normalized by the YAML writer).
Restart Hermes afterwards for the footer to appear.
"""

from __future__ import annotations

import os
import shutil
import signal
import sys
from pathlib import Path

import yaml

# The plugin ships under plugin/ next to this script.
PLUGIN_SRC = Path(__file__).resolve().parent / "plugin"
# Hermes on-disk layout under $HERMES_HOME.
PLUGINS_SUBDIR = "plugins"
CONFIG_FILENAME = "config.yaml"


def read_plugin_name(src: Path) -> str:
    """Return the plugin ``name`` from ``src/plugin.yaml`` (the source of truth)."""
    manifest = src / "plugin.yaml"
    if not manifest.is_file():
        raise FileNotFoundError(f"plugin manifest not found: {manifest}")
    data = yaml.safe_load(manifest.read_text())
    name = data.get("name") if isinstance(data, dict) else None
    if not name:
        raise ValueError(f"plugin manifest missing 'name': {manifest}")
    return name


def resolve_hermes_home() -> Path:
    """Return the Hermes home dir from ``HERMES_HOME`` (default ``~/.hermes``)."""
    home = os.environ.get("HERMES_HOME", "").strip()
    return Path(home).expanduser() if home else Path.home() / ".hermes"


def install_plugin_dir(src: Path, hermes_home: Path, name: str) -> Path:
    """Copy ``src`` to ``<hermes_home>/plugins/<name>``, overwriting it.

    Returns the destination directory. Only the plugin's own destination is
    removed on overwrite — never its parent. A prior symlink install (per the
    README's manual symlink option) is unlinked rather than recursed into.
    """
    if not src.is_dir():
        raise FileNotFoundError(f"plugin source directory not found: {src}")
    dest = hermes_home / PLUGINS_SUBDIR / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_symlink() or dest.exists():
        if dest.is_dir() and not dest.is_symlink():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    shutil.copytree(src, dest)
    return dest


def enable_plugin(config_path: Path, name: str) -> None:
    """Add ``name`` to ``plugins.enabled`` in ``config_path`` (create if absent).

    Preserves any other keys and existing enabled plugins, and is idempotent —
    a name already present is not duplicated.
    """
    data = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text()) or {}
        if isinstance(loaded, dict):
            data = loaded
    plugins = data.get("plugins")
    if not isinstance(plugins, dict):
        plugins = {}
        data["plugins"] = plugins
    enabled = plugins.get("enabled")
    if not isinstance(enabled, list):
        enabled = []
        plugins["enabled"] = enabled
    if name not in enabled:
        enabled.append(name)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    # Write atomically so an interrupted run can't truncate the user's config.
    tmp = config_path.with_name(config_path.name + ".tmp")
    tmp.write_text(rendered)
    os.replace(tmp, config_path)


def main() -> int:
    hermes_home = resolve_hermes_home()
    name = read_plugin_name(PLUGIN_SRC)
    dest = install_plugin_dir(PLUGIN_SRC, hermes_home, name)
    config_path = hermes_home / CONFIG_FILENAME
    enable_plugin(config_path, name)
    print(f"Installed plugin to: {dest}")
    print(f"Enabled '{name}' in: {config_path}")
    print("Restart Hermes for the usage footer to appear.")
    return 0


def _handle_sigterm(signum, frame):
    sys.exit(128 + signum)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _handle_sigterm)
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
