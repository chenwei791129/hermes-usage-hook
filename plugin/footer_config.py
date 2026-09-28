"""Footer display settings read from the plugin's own Hermes config entry.

The only setting is ``plugins.entries.hermes-usage-hook.footer.show_model``. It
is re-read through the host ``load_config()`` on every call, accepts only a YAML
boolean, treats ``null`` as absent, and never reads environment variables. Any
malformed value fails closed to ``False`` with one stderr warning.
"""

from __future__ import annotations

import sys
from importlib import import_module

from .autoreset import PLUGIN_ID

# Keys walked from the config root down to the ``show_model`` value.
_KEY_PATH = ("plugins", "entries", PLUGIN_ID, "footer", "show_model")


def _warn(message: str) -> None:
    """Write one best-effort diagnostic; a broken stderr must not raise."""
    try:
        print(f"[{PLUGIN_ID}] footer config warning: {message}", file=sys.stderr)
    except Exception:  # noqa: BLE001 - diagnostics must not alter the outcome
        pass


def _load_hermes_config() -> object:
    """Load Hermes config lazily; a missing host module means an empty config."""
    try:
        config_module = import_module("hermes_cli.config")
    except ImportError:
        return {}
    return config_module.load_config() or {}


def load_show_model(config: object | None = None) -> bool:
    """Return whether the footer should render the ``Model <model>`` line."""
    if config is None:
        try:
            config = _load_hermes_config()
        except Exception as exc:  # noqa: BLE001 - fail closed on any load error
            _warn(f"load_config() failed ({type(exc).__name__}); show_model disabled")
            return False

    value = config
    for depth, key in enumerate(_KEY_PATH):
        if not isinstance(value, dict):
            location = ".".join(_KEY_PATH[:depth]) or "config"
            _warn(f"{location} must be a mapping; show_model disabled")
            return False
        value = value.get(key)
        if value is None:
            return False
    if not isinstance(value, bool):
        _warn(f"{'.'.join(_KEY_PATH)} must be a boolean; show_model disabled")
        return False
    return value
