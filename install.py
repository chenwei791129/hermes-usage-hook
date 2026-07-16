#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""One-command installer for the hermes-usage-hook plugin.

The script exposes an argparse CLI with two modes:

* ``install`` (the default when no subcommand is given) — install the plugin.
  By default it downloads the latest GitHub release of the source repo and
  installs the ``plugin/`` directory found in its source tarball. ``--local``
  installs from a local directory instead; ``--version`` pins a release tag;
  ``--ref`` installs a branch/tag/commit source tarball (e.g. ``--ref main``
  for the latest unreleased ``main``).
* ``remove`` — delete the installed plugin directory and disable it in
  ``config.yaml``, with an optional ``--version`` guard.

Run from the repo root (local install) or directly from the raw URL:

    uv run install.py --local
    uv run https://raw.githubusercontent.com/chenwei791129/hermes-usage-hook/main/install.py

The plugin is installed to ``$HERMES_HOME/plugins/hermes-usage-hook/``
(``HERMES_HOME`` defaults to ``~/.hermes``; ``--hermes-home`` overrides it) and
``hermes-usage-hook`` is added to the ``plugins.enabled`` list in
``$HERMES_HOME/config.yaml`` (created when absent). Download and extraction use
only the Python standard library; ``pyyaml`` is the sole runtime dependency.
Restart Hermes afterwards for the footer to appear.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import yaml

# The plugin name is a fixed identifier, never read from a file beside the
# script — so non-local modes (default release install, --version, remove) work
# when the script is run standalone from its raw URL with no adjacent plugin/.
PLUGIN_NAME = "hermes-usage-hook"
# Default source repository for release downloads (overridable with --repo).
DEFAULT_REPO = "chenwei791129/hermes-usage-hook"
# A local --local install with no path falls back to the plugin/ next to the
# script; this is the only path that touches files adjacent to the script.
PLUGIN_SRC = Path(__file__).resolve().parent / "plugin"
# Hermes on-disk layout under $HERMES_HOME.
PLUGINS_SUBDIR = "plugins"
CONFIG_FILENAME = "config.yaml"


def resolve_hermes_home(override: str | None = None) -> Path:
    """Return the Hermes home dir.

    Precedence: ``--hermes-home`` override > ``HERMES_HOME`` env var > ``~/.hermes``.
    """
    if override and override.strip():
        return Path(override).expanduser()
    home = os.environ.get("HERMES_HOME", "").strip()
    return Path(home).expanduser() if home else Path.home() / ".hermes"


def install_plugin_dir(src: Path, hermes_home: Path, name: str) -> Path:
    """Copy ``src`` to ``<hermes_home>/plugins/<name>``, overwriting it.

    Returns the destination directory. Only the plugin's own destination is
    removed on overwrite — never its parent. A prior symlink install (per the
    README's manual symlink option) is unlinked rather than recursed into.
    """
    if not src.is_dir():
        raise FileNotFoundError(f"plugin source directory not found: {src}")
    dest = hermes_home / PLUGINS_SUBDIR / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_symlink() or dest.exists():
        if dest.is_dir() and not dest.is_symlink():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    shutil.copytree(src, dest)
    return dest


def remove_plugin_dir(dest: Path) -> bool:
    """Delete the installed plugin directory (or symlink) at ``dest``.

    Idempotent: a missing destination is a no-op. A prior symlink install is
    unlinked rather than recursed into. Returns ``True`` if something existed
    and was removed, ``False`` if there was nothing to remove.
    """
    if dest.is_symlink():
        dest.unlink()
        return True
    if dest.is_dir():
        shutil.rmtree(dest)
        return True
    if dest.exists():
        dest.unlink()
        return True
    return False


def read_installed_version(dest: Path) -> str | None:
    """Return the ``version`` from ``dest/plugin.yaml``, or ``None`` if absent.

    Reads only the already-installed directory — never a file beside the
    script — so the remove version guard works for standalone URL invocations.
    """
    manifest = dest / "plugin.yaml"
    if not manifest.is_file():
        return None
    data = yaml.safe_load(manifest.read_text())
    if isinstance(data, dict):
        version = data.get("version")
        return None if version is None else str(version)
    return None


def _normalize_version(version: str | None) -> str | None:
    """Normalize a version/tag for comparison, dropping a single leading ``v``."""
    if version is None:
        return None
    v = str(version).strip()
    return v[1:] if v.startswith("v") else v


def enable_plugin(config_path: Path, name: str) -> None:
    """Add ``name`` to ``plugins.enabled`` in ``config_path`` (create if absent).

    Preserves any other keys and existing enabled plugins, and is idempotent —
    a name already present is not duplicated.
    """
    data = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text()) or {}
        if isinstance(loaded, dict):
            data = loaded
    plugins = data.get("plugins")
    if not isinstance(plugins, dict):
        plugins = {}
        data["plugins"] = plugins
    enabled = plugins.get("enabled")
    if not isinstance(enabled, list):
        enabled = []
        plugins["enabled"] = enabled
    if name not in enabled:
        enabled.append(name)
    _write_config_atomically(config_path, data)


def disable_plugin(config_path: Path, name: str) -> None:
    """Remove ``name`` from ``plugins.enabled`` in ``config_path``.

    Idempotent and non-destructive: a missing config, missing ``plugins.enabled``
    list, or an entry already absent is a no-op. Other keys and values are
    preserved; the file is only rewritten (atomically) when the entry was
    actually present.
    """
    if not config_path.exists():
        return
    loaded = yaml.safe_load(config_path.read_text()) or {}
    if not isinstance(loaded, dict):
        return
    plugins = loaded.get("plugins")
    if not isinstance(plugins, dict):
        return
    enabled = plugins.get("enabled")
    if not isinstance(enabled, list) or name not in enabled:
        return
    plugins["enabled"] = [item for item in enabled if item != name]
    _write_config_atomically(config_path, loaded)


def _write_config_atomically(config_path: Path, data: dict) -> None:
    """Serialize ``data`` to ``config_path`` atomically.

    Writes to a sibling temp file then ``os.replace`` so an interrupted run
    cannot truncate the user's existing config.
    """
    config_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    tmp = config_path.with_name(config_path.name + ".tmp")
    tmp.write_text(rendered)
    os.replace(tmp, config_path)


_USER_AGENT = "hermes-usage-hook-installer"
_GITHUB_API = "https://api.github.com"


class InstallerError(Exception):
    """A user-facing installer failure (release resolution, download, extract).

    Raised with a readable message; ``main`` prints it and exits non-zero.
    Release-source messages point the user to ``--local`` as a fallback.
    """


def _candidate_tags(version: str) -> list[str]:
    """Return the bare and ``v``-prefixed tag candidates to try for ``version``.

    Built on ``_normalize_version`` so the leading-``v`` rule lives in one place.
    """
    bare = _normalize_version(version) or version.strip()
    return [bare, f"v{bare}"]


def _http_get(url: str, *, accept_json: bool = False, verbose: bool = False) -> bytes:
    """GET ``url`` with the installer's User-Agent and return the response body."""
    headers = {"User-Agent": _USER_AGENT}
    if accept_json:
        headers["Accept"] = "application/vnd.github+json"
    if verbose:
        print(f"GET {url}", file=sys.stderr)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        return resp.read()


def ref_tarball_url(repo: str, ref: str) -> str:
    """Return the source-tarball URL for a branch, tag, or commit SHA.

    Unlike ``resolve_release`` (which goes through the Releases API), this points
    straight at GitHub's ``/tarball/{ref}`` endpoint so an unreleased ref such as
    ``main`` can be installed. The ref is used verbatim, matching how
    ``resolve_release`` passes tags through unencoded.
    """
    return f"{_GITHUB_API}/repos/{repo}/tarball/{ref}"


def resolve_release(
    repo: str, version: str | None = None, verbose: bool = False
) -> dict:
    """Resolve a GitHub release for ``repo`` and return its parsed JSON.

    With no ``version`` the latest release is used. With a ``version`` the tag
    is tried both with and without a leading ``v``. Any failure raises
    ``InstallerError`` with a message that points to ``--local``.
    """
    if version:
        urls = [
            f"{_GITHUB_API}/repos/{repo}/releases/tags/{tag}"
            for tag in _candidate_tags(version)
        ]
        not_found = f"no release found for version {version!r} in {repo}"
    else:
        urls = [f"{_GITHUB_API}/repos/{repo}/releases/latest"]
        not_found = f"failed to resolve the latest release from {repo}"

    last_404: urllib.error.HTTPError | None = None
    for url in urls:
        try:
            data = _http_get(url, accept_json=True, verbose=verbose)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                last_404 = exc
                continue
            raise InstallerError(
                f"failed to resolve a release from {repo}: HTTP {exc.code}; use "
                f"--local to install from a local directory"
            ) from exc
        except urllib.error.URLError as exc:
            raise InstallerError(
                f"failed to reach GitHub while resolving a release from {repo}: "
                f"{exc.reason}; use --local to install from a local directory"
            ) from exc
        return json.loads(data)
    raise InstallerError(
        f"{not_found}; use --local to install from a local directory"
    ) from last_404


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    """Extract ``tar`` into ``dest``, rejecting members that escape ``dest``.

    Every member (and link target) is validated *before* anything is written,
    so a malicious tarball with ``..`` or absolute paths writes nothing at all.
    """
    dest = dest.resolve()

    def escapes(path: Path) -> bool:
        return path != dest and dest not in path.parents

    for member in tar.getmembers():
        target = (dest / member.name).resolve()
        if escapes(target):
            raise InstallerError(f"unsafe path in release tarball: {member.name!r}")
        if member.issym() or member.islnk():
            link_target = (target.parent / member.linkname).resolve()
            if escapes(link_target):
                raise InstallerError(
                    f"unsafe link in release tarball: {member.name!r} -> "
                    f"{member.linkname!r}"
                )
    # Use the stdlib 'data' filter where available (3.12+) for defense in depth
    # and to opt into the 3.14 default early; our manual checks cover 3.10/3.11.
    if sys.version_info >= (3, 12):
        tar.extractall(dest, filter="data")
    else:
        tar.extractall(dest)


def locate_plugin_dir(extract_root: Path) -> Path:
    """Return the ``plugin/`` directory inside an extracted release tree.

    GitHub source tarballs wrap the repo in a single ``<owner>-<repo>-<sha>/``
    directory, so the plugin lives one level down; the extract root itself is
    also checked for robustness. Raises ``InstallerError`` when not found.
    """
    extract_root = Path(extract_root)
    candidates = [extract_root]
    candidates.extend(p for p in sorted(extract_root.iterdir()) if p.is_dir())
    for base in candidates:
        plugin = base / "plugin"
        if (plugin / "plugin.yaml").is_file():
            return plugin
    raise InstallerError(
        "no plugin/ directory found in the release tarball; use --local to "
        "install from a local directory"
    )


def download_and_locate_plugin(
    tarball_url: str, workdir: Path, verbose: bool = False
) -> Path:
    """Download ``tarball_url`` into ``workdir``, extract it, and return ``plugin/``.

    Download and extraction failures raise ``InstallerError`` pointing to
    ``--local``. ``workdir`` is the caller-owned temporary directory.
    """
    workdir = Path(workdir)
    if verbose:
        print(f"Downloading {tarball_url}", file=sys.stderr)
    try:
        data = _http_get(tarball_url, verbose=verbose)
    except urllib.error.HTTPError as exc:
        raise InstallerError(
            f"failed to download release tarball from {tarball_url}: HTTP "
            f"{exc.code}; use --local to install from a local directory"
        ) from exc
    except urllib.error.URLError as exc:
        raise InstallerError(
            f"failed to download release tarball from {tarball_url}: "
            f"{exc.reason}; use --local to install from a local directory"
        ) from exc
    tar_path = workdir / "release.tar.gz"
    tar_path.write_bytes(data)
    extract_dir = workdir / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(tar_path, mode="r:*") as tar:
            _safe_extract(tar, extract_dir)
    except tarfile.TarError as exc:
        raise InstallerError(
            f"failed to extract release tarball: {exc}; use --local to install "
            f"from a local directory"
        ) from exc
    if verbose:
        print(f"Extracted to {extract_dir}", file=sys.stderr)
    return locate_plugin_dir(extract_dir)


def cmd_install(args: argparse.Namespace) -> int:
    """Install the plugin (release download by default, or ``--local``).

    Source precedence: ``--local`` (a local directory) else the GitHub release
    (``--version`` tag or latest). The resolved plugin directory is copied to
    ``<hermes_home>/plugins/hermes-usage-hook/`` and, unless ``--no-enable``,
    ``hermes-usage-hook`` is added to ``plugins.enabled``. ``--dry-run`` prints
    the plan and returns without any network or filesystem changes.
    """
    hermes_home = resolve_hermes_home(args.hermes_home)
    dest = hermes_home / PLUGINS_SUBDIR / PLUGIN_NAME
    config_path = hermes_home / CONFIG_FILENAME

    if args.local is not None:
        src = Path(args.local).expanduser()
        source_desc = f"local directory {src}"
    elif args.ref:
        source_desc = f"GitHub ref {args.ref!r} of {args.repo}"
    elif args.version:
        source_desc = f"GitHub release {args.version!r} of {args.repo}"
    else:
        source_desc = f"latest GitHub release of {args.repo}"

    if args.dry_run:
        print("Dry run — no changes will be made.")
        print(f"Would install from: {source_desc}")
        print(f"Would install to:   {dest}")
        if args.no_enable:
            print("Would not modify config.yaml (--no-enable).")
        else:
            print(f"Would enable '{PLUGIN_NAME}' in: {config_path}")
        return 0

    if args.local is not None:
        if not src.is_dir():
            raise InstallerError(
                f"local plugin directory not found: {src}; pass an existing "
                f"--local PATH (or omit --local to install from a GitHub release)"
            )
        installed = install_plugin_dir(src, hermes_home, PLUGIN_NAME)
    else:
        if args.ref:
            tarball_url = ref_tarball_url(args.repo, args.ref)
        else:
            release = resolve_release(args.repo, args.version, verbose=args.verbose)
            tarball_url = release.get("tarball_url")
            if not tarball_url:
                raise InstallerError(
                    f"release for {args.repo} has no source tarball; use --local "
                    f"to install from a local directory"
                )
            if args.verbose:
                print(
                    f"Resolved release tag: {release.get('tag_name')}",
                    file=sys.stderr,
                )
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = download_and_locate_plugin(
                tarball_url, Path(tmp), verbose=args.verbose
            )
            installed = install_plugin_dir(plugin_dir, hermes_home, PLUGIN_NAME)

    print(f"Installed plugin to: {installed}")
    if args.no_enable:
        print("Skipped config.yaml (--no-enable).")
    else:
        enable_plugin(config_path, PLUGIN_NAME)
        print(f"Enabled '{PLUGIN_NAME}' in: {config_path}")
    print("Restart Hermes for the usage footer to appear.")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    """Remove the installed plugin directory and disable it in config.yaml.

    Both actions are idempotent. ``--version`` acts as a guard: the installed
    ``plugin.yaml`` version must match (ignoring a leading ``v``) or nothing is
    deleted; a missing install with ``--version`` is also an error.
    ``--dry-run`` prints the plan without deleting anything.
    """
    hermes_home = resolve_hermes_home(args.hermes_home)
    dest = hermes_home / PLUGINS_SUBDIR / PLUGIN_NAME
    config_path = hermes_home / CONFIG_FILENAME

    if args.version:
        if not dest.exists():
            raise InstallerError(
                f"cannot version-check: no installed plugin found at {dest}"
            )
        installed = read_installed_version(dest)
        if installed is None:
            raise InstallerError(
                f"cannot determine the installed version from {dest}/plugin.yaml; "
                f"nothing removed (re-run remove without --version to force)"
            )
        if _normalize_version(installed) != _normalize_version(args.version):
            raise InstallerError(
                f"installed version {installed!r} does not match requested "
                f"version {args.version!r}; nothing removed"
            )

    if args.dry_run:
        print("Dry run — no changes will be made.")
        print(f"Would remove: {dest}")
        if args.no_enable:
            print("Would not modify config.yaml (--no-enable).")
        else:
            print(f"Would disable '{PLUGIN_NAME}' in: {config_path}")
        return 0

    if remove_plugin_dir(dest):
        print(f"Removed plugin directory: {dest}")
    else:
        print(f"No plugin directory to remove at: {dest}")
    if args.no_enable:
        print("Skipped config.yaml (--no-enable).")
    else:
        disable_plugin(config_path, PLUGIN_NAME)
        print(f"Disabled '{PLUGIN_NAME}' in: {config_path}")
    return 0


def _add_install_args(parser: argparse.ArgumentParser) -> None:
    """Add install-mode flags (``--local``/``--version``/``--repo``) to ``parser``.

    ``--local`` and ``--version`` are mutually exclusive: a local directory has
    no release-version concept, so supplying both exits non-zero via argparse.
    """
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--local",
        nargs="?",
        const=str(PLUGIN_SRC),
        default=None,
        metavar="PATH",
        help="install from a local directory (defaults to the plugin/ next to "
        "this script when no PATH is given)",
    )
    source.add_argument(
        "--version",
        default=None,
        metavar="TAG",
        help="install a specific GitHub release tag instead of the latest",
    )
    source.add_argument(
        "--ref",
        default=None,
        metavar="BRANCH_OR_SHA",
        help="install from a branch, tag, or commit SHA's source tarball "
        "(e.g. --ref main for the latest unreleased main) instead of a release",
    )
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        metavar="OWNER/NAME",
        help=f"source repository for release downloads (default: {DEFAULT_REPO})",
    )


# Shared-flag defaults, applied in parse_args() rather than via set_defaults so
# they cannot clobber a value given before the subcommand (see parse_args).
_SHARED_DEFAULTS = {
    "dry_run": False,
    "no_enable": False,
    "verbose": False,
    "hermes_home": None,
}


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse CLI: ``install`` (default) and ``remove`` subcommands.

    Shared flags live on a parent parser reused by the top-level parser (so a
    bare ``install.py --dry-run`` works without naming the subcommand) and by
    both subparsers. ``set_defaults(func=...)`` with ``subparsers.required =
    False`` makes a missing subcommand behave as ``install``.

    The shared flags use ``default=argparse.SUPPRESS`` so that when a flag is
    given *before* the subcommand (e.g. ``install.py --dry-run remove``) the
    subparser does not re-apply a default that overwrites the value already
    parsed. ``parse_args`` fills the resulting absent attributes afterwards.
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--hermes-home",
        default=argparse.SUPPRESS,
        metavar="PATH",
        help="Hermes home dir; overrides HERMES_HOME (default: ~/.hermes)",
    )
    common.add_argument(
        "--no-enable",
        action="store_true",
        default=argparse.SUPPRESS,
        help="do not modify config.yaml (only copy/remove the plugin directory)",
    )
    common.add_argument(
        "--dry-run",
        action="store_true",
        default=argparse.SUPPRESS,
        help="print the actions that would be taken without changing anything",
    )
    common.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS,
        help="emit diagnostic detail (release tag, tarball URL, extraction path)",
    )

    parser = argparse.ArgumentParser(
        prog="install.py",
        parents=[common],
        description="Install or remove the hermes-usage-hook plugin.",
    )
    _add_install_args(parser)
    parser.set_defaults(func=cmd_install)

    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = False

    install_p = subparsers.add_parser(
        "install",
        parents=[common],
        help="install the plugin (default when no subcommand is given)",
    )
    _add_install_args(install_p)
    install_p.set_defaults(func=cmd_install)

    remove_p = subparsers.add_parser(
        "remove",
        parents=[common],
        help="remove the installed plugin",
    )
    remove_p.add_argument(
        "--version",
        default=None,
        metavar="TAG",
        help="version guard: remove only if the installed version matches TAG",
    )
    remove_p.set_defaults(func=cmd_remove)

    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse ``argv`` and fill shared-flag defaults left absent by SUPPRESS.

    Shared flags use ``default=argparse.SUPPRESS`` (see ``build_parser``) so an
    omitted flag is missing from the namespace rather than reset; this fills the
    canonical default for any that ended up absent, giving callers a complete
    namespace regardless of where (or whether) the flags appeared.
    """
    args = build_parser().parse_args(argv)
    for key, value in _SHARED_DEFAULTS.items():
        if not hasattr(args, key):
            setattr(args, key, value)
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return args.func(args)
    except InstallerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _handle_sigterm(signum, frame):
    sys.exit(128 + signum)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _handle_sigterm)
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
