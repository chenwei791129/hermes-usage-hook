"""Hermes plugin root entry point.

Hermes' loader discovers this directory via ``plugin.yaml`` and imports the
plugin root package to obtain ``register(ctx)``. The hook implementation lives
in ``hooks/footer_hook.py`` (already covered by the test suite); this module
only puts the plugin root on ``sys.path`` so ``usage`` and ``providers`` resolve
from the plugin's own directory, then re-exports ``register`` from there.
"""

from __future__ import annotations

import os
import sys

# Make this plugin's own modules importable from the installed directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hooks.footer_hook import register  # noqa: E402

__all__ = ["register"]
