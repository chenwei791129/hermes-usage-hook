"""Put the plugin root on sys.path so tests can import the plugin's modules.

The plugin ships under ``plugin/``; the tests live at the repo root and are not
part of the shipped plugin. pytest imports this conftest before collecting any
test module, so adding ``plugin/`` (and ``plugin/hooks/``) here makes ``usage``,
``providers``, and ``footer_hook`` importable without relying on the repo root
itself being on the import path.
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PLUGIN = os.path.join(_REPO_ROOT, "plugin")

for _path in (_PLUGIN, os.path.join(_PLUGIN, "hooks")):
    if _path not in sys.path:
        sys.path.insert(0, _path)
