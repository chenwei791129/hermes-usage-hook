"""Put the repo root on sys.path so tests can import the plugin as a package.

The plugin ships under ``plugin/`` and uses package-relative imports internally
(matching how Hermes' loader imports it, with package context). pytest imports
this conftest before collecting any test module, so adding the repo root here
makes the ``plugin`` package — and its ``plugin.usage``, ``plugin.providers``,
and ``plugin.hooks.footer_hook`` submodules — importable from the tests.
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
