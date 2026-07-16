"""Profile-safe Hermes home resolution for plugin-owned files.

Prefers the official ``hermes_constants.get_hermes_home()`` (which honors the
active profile, the ``HERMES_HOME`` override, and platform defaults) and only
falls back to a bare ``HERMES_HOME`` lookup when that module is absent, so both
the installed plugin and standalone tests resolve a usable home.
"""

from __future__ import annotations

import os
from importlib import import_module
from pathlib import Path


def resolve_hermes_home(home: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the Hermes home directory.

    An injected ``home`` takes precedence over everything so callers can pin the
    location (tests, or the coordinator threading its own store home). Otherwise
    delegate to ``hermes_constants.get_hermes_home()``; fall back to the
    ``HERMES_HOME`` environment variable only when that module itself is missing
    so an unrelated ``ModuleNotFoundError`` still surfaces.
    """
    if home is not None:
        return Path(home)
    try:
        module = import_module("hermes_constants")
    except ModuleNotFoundError as exc:
        if exc.name != "hermes_constants":
            raise
        return Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
    return Path(module.get_hermes_home())
