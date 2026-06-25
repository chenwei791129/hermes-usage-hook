"""Script-mode regression tests plus install.py CLI argument parsing.

Two concerns live here:

1. Provider modules must stay runnable as standalone scripts. The README
   documents running the fetchers directly (``python
   plugin/providers/codex_usage.py``). Their ``if __name__ == "__main__":``
   blocks import the dispatch module via ``from plugin.usage import
   format_summary``; ``usage.py`` uses a package-relative import (``from
   .providers import ...``), so the deferred import must resolve ``usage``
   *with* package context. A plain ``from usage import ...`` would raise
   ``ImportError: attempted relative import with no known parent package`` —
   the first test guards against that regression. The fetch itself needs
   network/credentials and is expected to fail in CI; we only assert the module
   gets past its imports, never the relative-import error.

2. ``install.py`` exposes an argparse CLI with an ``install`` mode (default when
   no subcommand is given) and a ``remove`` mode. The parser tests below cover
   subcommand routing, shared and mode-specific flags, and the ``--local`` /
   ``--version`` mutual exclusion — our own parser wiring, not argparse itself.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

import install

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


# ---------------------------------------------------------------------------
# install.py CLI argument parsing
# ---------------------------------------------------------------------------


def _parse(argv):
    # Use install.parse_args (not build_parser().parse_args directly) so the
    # tests exercise the same shared-flag default-filling that main() relies on.
    return install.parse_args(argv)


def test_no_subcommand_defaults_to_install():
    args = _parse([])
    assert args.func is install.cmd_install
    # No subcommand means the install-mode flags carry their defaults.
    assert args.local is None
    assert args.version is None
    assert args.repo == install.DEFAULT_REPO


def test_install_subcommand_routes_to_install():
    args = _parse(["install"])
    assert args.func is install.cmd_install


def test_remove_subcommand_routes_to_remove():
    args = _parse(["remove"])
    assert args.func is install.cmd_remove
    assert args.command == "remove"


def test_shared_flags_parse_without_subcommand():
    args = _parse(["--hermes-home", "/custom/home", "--no-enable", "--dry-run", "-v"])
    assert args.func is install.cmd_install
    assert args.hermes_home == "/custom/home"
    assert args.no_enable is True
    assert args.dry_run is True
    assert args.verbose is True


def test_shared_flags_parse_on_remove():
    args = _parse(
        ["remove", "--hermes-home", "/custom/home", "--no-enable", "--dry-run", "-v"]
    )
    assert args.func is install.cmd_remove
    assert args.hermes_home == "/custom/home"
    assert args.no_enable is True
    assert args.dry_run is True
    assert args.verbose is True


def test_shared_flags_before_subcommand_are_not_clobbered():
    # Regression: shared flags given BEFORE the subcommand must survive the
    # subparser pass (a SUPPRESS default bug previously reset --dry-run to False
    # for `install.py --dry-run remove`, turning a dry run into a real delete).
    args = _parse(["--dry-run", "--no-enable", "--hermes-home", "/x", "remove"])
    assert args.func is install.cmd_remove
    assert args.dry_run is True
    assert args.no_enable is True
    assert args.hermes_home == "/x"


def test_local_without_path_defaults_to_adjacent_plugin():
    args = _parse(["--local"])
    assert args.local == str(install.PLUGIN_SRC)


def test_local_with_explicit_path():
    args = _parse(["--local", "/some/where/plugin"])
    assert args.local == "/some/where/plugin"


def test_install_version_and_repo_flags():
    args = _parse(["--version", "0.2.0", "--repo", "owner/name"])
    assert args.version == "0.2.0"
    assert args.repo == "owner/name"


def test_remove_accepts_version():
    args = _parse(["remove", "--version", "0.2.0"])
    assert args.func is install.cmd_remove
    assert args.version == "0.2.0"


def test_remove_rejects_repo():
    # --repo is install-only; remove operates solely on the local installation.
    with pytest.raises(SystemExit):
        _parse(["remove", "--repo", "owner/name"])


def test_local_and_version_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        _parse(["--local", "--version", "0.2.0"])


def test_local_and_version_mutually_exclusive_on_install_subcommand():
    with pytest.raises(SystemExit):
        _parse(["install", "--local", "--version", "0.2.0"])
