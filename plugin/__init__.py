"""Hermes plugin root entry point.

Hermes' loader discovers this directory via ``plugin.yaml`` and imports the
plugin root package to obtain ``register(ctx)``. The hook implementation lives
in ``hooks/footer_hook.py`` (already covered by the test suite); this module
re-exports ``register`` from there via a package-relative import.
"""

from __future__ import annotations

from .hooks.footer_hook import register

__all__ = ["register"]
