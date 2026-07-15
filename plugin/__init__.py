"""Hermes plugin root entry point.

Hermes' loader discovers this directory via ``plugin.yaml`` and imports the
plugin root package to obtain ``register(ctx)``. Hook imports remain lazy so
standalone offline submodules do not load network transports as a side effect.
"""

from __future__ import annotations


def register(ctx):
    """Load and invoke the Hermes hook registration entry point."""
    from .hooks.footer_hook import register as register_hooks

    return register_hooks(ctx)


__all__ = ["register"]
