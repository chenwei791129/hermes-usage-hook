"""Lazy, stdlib-only active Hermes profile resolution."""

from __future__ import annotations

import os
from importlib import import_module
from pathlib import Path


def resolve_hermes_home(home: Path | None = None) -> Path:
    """Return an injected home or Hermes' authoritative active profile home."""
    if home is not None:
        return Path(home)
    try:
        constants = import_module("hermes_constants")
    except ModuleNotFoundError as exc:
        if exc.name != "hermes_constants":
            raise
    else:
        return Path(constants.get_hermes_home())
    return Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
