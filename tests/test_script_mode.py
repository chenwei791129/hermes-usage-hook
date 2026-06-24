"""Regression tests: provider modules must stay runnable as standalone scripts.

The README documents running the fetchers directly (``python
plugin/providers/codex_usage.py``). Their ``if __name__ == "__main__":`` blocks
import the dispatch module via ``from plugin.usage import format_summary``;
``usage.py`` uses a package-relative import (``from .providers import ...``), so
the deferred import must resolve ``usage`` *with* package context. A plain
``from usage import ...`` would raise ``ImportError: attempted relative import
with no known parent package`` — this test guards against that regression.

The fetch itself needs network/credentials and is expected to fail in CI; we
only assert the module gets past its imports, never the relative-import error.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.mark.parametrize("module", ["codex_usage.py", "minimax_usage.py"])
def test_provider_runs_as_script_without_import_error(module):
    script = os.path.join(_REPO_ROOT, "plugin", "providers", module)
    proc = subprocess.run(
        [sys.executable, script],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    assert "attempted relative import with no known parent package" not in proc.stderr
    assert "No module named 'usage'" not in proc.stderr
