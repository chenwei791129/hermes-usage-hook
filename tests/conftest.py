"""Put the repo root on sys.path so tests can import the plugin as a package.

The plugin ships under ``plugin/`` and uses package-relative imports internally
(matching how Hermes' loader imports it, with package context). pytest imports
this conftest before collecting any test module, so adding the repo root here
makes the ``plugin`` package — and its ``plugin.usage``, ``plugin.providers``,
and ``plugin.hooks.footer_hook`` submodules — importable from the tests.
"""

import os
import sys
import types

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


@pytest.fixture
def fake_hermes_constants(monkeypatch):
    """Install a fake ``hermes_constants`` module for the profile-safe branch.

    Returns a callable that registers a stand-in module whose
    ``get_hermes_home()`` yields the given home, so tests can exercise
    ``resolve_hermes_home()``'s official-module path without a Hermes runtime.
    The callable returns the installed home for convenience.
    """

    def _install(home):
        module = types.ModuleType("hermes_constants")
        module.get_hermes_home = lambda: home
        monkeypatch.setitem(sys.modules, "hermes_constants", module)
        return home

    return _install
